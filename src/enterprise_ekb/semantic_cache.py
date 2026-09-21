"""P1-7 LLM semantic cache (LCO ironrule: three semantic layers, this module owns L1+L2).

L1 exact layer: sha256(system_prompt + "\\x00" + user_prompt) -> answer, TTL + LRU.
L2 semantic layer: per-entry embedding vector with brute-force cosine similarity
against the query embedding; cosine >= similarity_threshold is a hit. Entry counts
are small in the single-replica control plane, so a linear scan is acceptable;
production multi-replica deployments should swap the scan for Milvus ANN search
(see DEFERRED note in :class:`SemanticCache`).

Hit/miss counters are exposed through :meth:`SemanticCache.stats` — the
Prometheus wiring (``llm_cache_hits_total{layer}`` / ``llm_cache_misses_total``)
is done by the observability layer / main wiring, per project convention that
this module stays infrastructure-free.

All entry points are defensive against ``None`` / empty-string inputs (CLC) and
the whole structure is guarded by a ``threading.Lock``.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

__all__ = ["SemanticCache"]


def _normalize(prompt: str | None) -> str:
    """Defensive normalization: ``None`` -> ``""`` (CLC: callers may pass None)."""
    return prompt if isinstance(prompt, str) else ""


def _cosine(a: list[float], b: list[float]) -> float:
    """Brute-force cosine similarity; 0.0 on dimension mismatch or zero norm."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class _Entry:
    """Immutable-ish cache entry; ``embedding`` is None when L2 is disabled."""

    __slots__ = ("answer", "created_at", "embedding")

    def __init__(self, answer: str, created_at: float, embedding: list[float] | None) -> None:
        self.answer = answer
        self.created_at = created_at
        self.embedding = embedding


class SemanticCache:
    """Two-layer (exact + semantic) in-process LLM response cache.

    DEFERRED: Redis/Milvus backing for cross-replica sharing and ANN search.
    The single-replica LAN deployment can rebuild warm state from traffic, and
    the exact layer is deterministic from (system_prompt, user_prompt) pairs.
    """

    def __init__(
        self,
        max_entries: int = 512,
        ttl_seconds: int = 3600,
        similarity_threshold: float = 0.92,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.similarity_threshold = float(similarity_threshold)
        self.embedding_fn = embedding_fn
        self._lock = threading.Lock()
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._hits_l1 = 0
        self._hits_l2 = 0
        self._misses = 0

    # -- keying -------------------------------------------------------------

    @staticmethod
    def _key(system_prompt: str, user_prompt: str) -> str:
        raw = (system_prompt + "\x00" + user_prompt).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # -- public API ----------------------------------------------------------

    def get(self, system_prompt: str | None, user_prompt: str | None) -> tuple[str, int] | None:
        """Return ``(answer, layer)`` on hit (layer 1 exact / 2 semantic), else ``None``."""
        sys_p = _normalize(system_prompt)
        usr_p = _normalize(user_prompt)
        key = self._key(sys_p, usr_p)
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is not None and self._fresh(entry, now):
                self._store.move_to_end(key)
                self._hits_l1 += 1
                return entry.answer, 1
            if entry is not None:
                self._store.pop(key, None)

            # L2 semantic layer — only when an embedding function is wired.
            if self.embedding_fn is None:
                self._misses += 1
                return None
            try:
                query_vec = self.embedding_fn(sys_p + "\x00" + usr_p)
            except Exception:
                # Embedding backend failure must never break the request path (RWT);
                # degrade to a miss rather than propagate.
                self._misses += 1
                return None
            if not query_vec:
                self._misses += 1
                return None
            best_key: str | None = None
            best_score = 0.0
            for cand_key, cand in self._store.items():
                if cand_key == key or cand.embedding is None or not self._fresh(cand, now):
                    continue
                score = _cosine(query_vec, cand.embedding)
                if score >= self.similarity_threshold and score >= best_score:
                    best_key = cand_key
                    best_score = score
            if best_key is None:
                self._misses += 1
                return None
            best = self._store[best_key]
            self._store.move_to_end(best_key)
            self._hits_l2 += 1
            return best.answer, 2

    def put(
        self,
        system_prompt: str | None,
        user_prompt: str | None,
        answer: str | None,
    ) -> None:
        """Store an answer under the exact key; computes the L2 vector when enabled."""
        if not isinstance(answer, str) or answer == "":
            return
        sys_p = _normalize(system_prompt)
        usr_p = _normalize(user_prompt)
        key = self._key(sys_p, usr_p)
        embedding: list[float] | None = None
        if self.embedding_fn is not None:
            try:
                embedding = self.embedding_fn(sys_p + "\x00" + usr_p) or None
            except Exception:
                embedding = None  # L2 disabled for this entry only.
        with self._lock:
            if len(self._store) >= self.max_entries and key not in self._store:
                self._store.popitem(last=False)  # LRU eviction.
            self._store[key] = _Entry(answer, time.monotonic(), embedding)

    def stats(self) -> dict[str, Any]:
        """Hit/miss counters + entry count; Prometheus export is wired upstream."""
        with self._lock:
            hits = self._hits_l1 + self._hits_l2
            total = hits + self._misses
            return {
                "hits_l1": self._hits_l1,
                "hits_l2": self._hits_l2,
                "misses": self._misses,
                "hit_rate": (hits / total) if total > 0 else 0.0,
                "entries": len(self._store),
                "l2_enabled": self.embedding_fn is not None,
                "similarity_threshold": self.similarity_threshold,
                "ttl_seconds": self.ttl_seconds,
                "max_entries": self.max_entries,
            }

    def clear(self) -> int:
        """Drop every cached entry; returns how many were removed (counters kept)."""
        with self._lock:
            removed = len(self._store)
            self._store.clear()
            return removed

    # -- internals -----------------------------------------------------------

    def _fresh(self, entry: _Entry, now: float) -> bool:
        return (now - entry.created_at) < self.ttl_seconds
