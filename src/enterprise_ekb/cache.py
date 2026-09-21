"""Multi-level cache with hit-rate observability (review §10.1, P0 roadmap).

L1: in-process TTL+LRU dict (always on).
L2: Redis JSON cache (optional, `EKB_CACHE_BACKEND=redis`), graceful fallback.
Hit/miss counters are exported through /metrics so the 0% -> >=55% hit-rate
target from the architecture review is directly measurable.
Invalidation is prefix-based and wired to the domain write paths (and ready for
outbox-event-driven fan-out).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from enterprise_ekb.metrics import registry as metrics_registry

_DEFAULT_TTL = 60


def stable_key(*parts: Any) -> str:
    """Deterministic string key from arbitrary JSON-serializable parts."""
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MultiLevelCache:
    def __init__(
        self,
        l1_max_entries: int = 10_000,
        l1_ttl_seconds: int = 60,
        l2_ttl_seconds: int = 300,
        namespace: str = "ekb",
        redis_client: Any | None = None,
    ) -> None:
        self.l1_ttl_seconds = l1_ttl_seconds
        self.l2_ttl_seconds = l2_ttl_seconds
        self.namespace = namespace
        self._redis = redis_client
        self._lock = threading.Lock()
        self._l1: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._l1_max_entries = max(1, l1_max_entries)

    # -- key helpers --------------------------------------------------------

    def key(self, scope: str, *parts: Any) -> str:
        return f"{self.namespace}:cache:{scope}:{stable_key(parts)}"

    # -- core operations ----------------------------------------------------

    def get_json(self, cache_key: str) -> tuple[bool, Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._l1.get(cache_key)
            if entry is not None:
                expires, value_json = entry
                if expires > now:
                    self._l1.move_to_end(cache_key)
                    metrics_registry.inc("ekb_cache_hits_total", {"layer": "l1"})
                    return True, json.loads(value_json)
                self._l1.pop(cache_key, None)
        if self._redis is not None:
            try:
                raw = self._redis.get(cache_key)
            except Exception:
                raw = None
            if raw is not None:
                value = json.loads(raw)
                self._l1_put(cache_key, value, min(self.l1_ttl_seconds, self.l2_ttl_seconds))
                metrics_registry.inc("ekb_cache_hits_total", {"layer": "l2"})
                return True, value
        metrics_registry.inc("ekb_cache_misses_total", {})
        return False, None

    def set_json(self, cache_key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.l2_ttl_seconds
        self._l1_put(cache_key, value, min(self.l1_ttl_seconds, ttl))
        if self._redis is not None:
            with contextlib.suppress(Exception):
                self._redis.setex(cache_key, ttl, json.dumps(value, ensure_ascii=False))

    def get_or_load(
        self,
        cache_key: str,
        loader: Callable[[], Any],
        ttl_seconds: int | None = None,
    ) -> tuple[bool, Any]:
        hit, value = self.get_json(cache_key)
        if hit:
            return True, value
        value = loader()
        self.set_json(cache_key, value, ttl_seconds)
        return False, value

    def delete_prefix(self, prefix: str) -> int:
        """Invalidate L1 entries whose key contains `prefix`; returns removed count.

        Redis L2 entries rely on TTL (short) — prefix SCAN deletion is deferred
        to the event-driven invalidator to keep this path lock-free.
        """
        removed = 0
        with self._lock:
            for key in [k for k in self._l1 if prefix in k]:
                self._l1.pop(key, None)
                removed += 1
        if removed or self._redis is not None:
            metrics_registry.inc("ekb_cache_invalidations_total", {}, value=max(removed, 0))
        return removed

    # -- internals ----------------------------------------------------------

    def _l1_put(self, cache_key: str, value: Any, ttl_seconds: int) -> None:
        with self._lock:
            if len(self._l1) >= self._l1_max_entries:
                self._l1.popitem(last=False)
            self._l1[cache_key] = (time.monotonic() + ttl_seconds, json.dumps(value, ensure_ascii=False))
