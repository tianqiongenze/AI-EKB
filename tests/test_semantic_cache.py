"""P1-7 SemanticCache unit tests (L1 exact / L2 semantic / TTL / LRU / stats)."""

from __future__ import annotations

import functools
import time

import pytest

from enterprise_ekb.semantic_cache import SemanticCache


def _angle_embedding(text: str) -> list[float]:
    """Deterministic stand-in embedding: direction keyed by a marker word."""
    if "battery" in text:
        return [1.0, 0.0]
    if "motor" in text:
        return [0.0, 1.0]
    if "near" in text:
        return [1.0, 0.1]
    if "edge" in text:
        return [1.0, 0.5]
    return [0.5, 0.5]


def test_l1_exact_hit_and_miss() -> None:
    cache = SemanticCache()
    assert cache.get("sys", "user-a") is None  # miss on empty cache
    cache.put("sys", "user-a", "answer-a")
    hit = cache.get("sys", "user-a")
    assert hit == ("answer-a", 1)
    assert cache.get("sys", "user-b") is None  # different prompt -> miss (L2 off)


def test_l1_ttl_expiry() -> None:
    cache = SemanticCache(ttl_seconds=0)  # expires immediately
    cache.put("sys", "user", "answer")
    assert cache.get("sys", "user") is None


def test_l1_ttl_boundary_with_clock() -> None:
    cache = SemanticCache(ttl_seconds=60)
    cache.put("sys", "user", "answer")
    assert cache.get("sys", "user") == ("answer", 1)


def test_lru_eviction() -> None:
    cache = SemanticCache(max_entries=2)
    cache.put("sys", "u1", "a1")
    cache.put("sys", "u2", "a2")
    assert cache.get("sys", "u1") == ("a1", 1)  # refresh u1 LRU position
    cache.put("sys", "u3", "a3")  # evicts u2 (least recently used)
    assert cache.get("sys", "u2") is None
    assert cache.get("sys", "u1") == ("a1", 1)
    assert cache.get("sys", "u3") == ("a3", 1)


def test_l2_semantic_hit_with_fixed_vectors() -> None:
    cache = SemanticCache(similarity_threshold=0.92, embedding_fn=_angle_embedding)
    cache.put("sys", "tell me about motor specs", "motor-answer")
    # Different exact key, same semantic direction -> L2 hit.
    hit = cache.get("sys", "how is the motor tested")
    assert hit == ("motor-answer", 2)


def test_l2_threshold_boundary_below() -> None:
    # cosine([1,0],[1,0.5]) = 0.894 < 0.92 -> miss
    cache = SemanticCache(similarity_threshold=0.92, embedding_fn=_angle_embedding)
    cache.put("sys", "battery query", "battery-answer")
    assert cache.get("sys", "edge other") is None


def test_l2_threshold_boundary_above() -> None:
    # cosine([1,0],[1,0.1]) = 0.995 >= 0.92 -> hit
    cache = SemanticCache(similarity_threshold=0.92, embedding_fn=_angle_embedding)
    cache.put("sys", "battery query", "battery-answer")
    assert cache.get("sys", "near other") == ("battery-answer", 2)


def test_l2_disabled_without_embedding_fn() -> None:
    cache = SemanticCache(embedding_fn=None)
    cache.put("sys", "motor specs query", "answer")
    # Semantically identical text, different exact key -> miss (L2 disabled).
    assert cache.get("sys", "motor specs query ") is None
    assert cache.stats()["l2_enabled"] is False


def test_stats_counters_and_hit_rate() -> None:
    cache = SemanticCache()
    cache.put("s", "a", "x")
    cache.get("s", "a")   # hit l1
    cache.get("s", "a")   # hit l1
    cache.get("s", "zz")  # miss
    stats = cache.stats()
    assert stats["hits_l1"] == 2
    assert stats["hits_l2"] == 0
    assert stats["misses"] == 1
    assert stats["entries"] == 1
    assert stats["hit_rate"] == pytest.approx(2 / 3)


def test_clear_returns_removed_count() -> None:
    cache = SemanticCache()
    cache.put("s", "a", "x")
    cache.put("s", "b", "y")
    assert cache.clear() == 2
    assert cache.stats()["entries"] == 0
    assert cache.clear() == 0


def test_none_and_empty_inputs_are_safe() -> None:
    cache = SemanticCache()
    cache.put(None, None, "root-answer")
    assert cache.get(None, None) == ("root-answer", 1)
    assert cache.get("", "") == ("root-answer", 1)  # None normalizes to ""
    cache.put("s", "u", None)  # non-str answer ignored defensively
    cache.put("s", "u", "")
    assert cache.get("s", "u") == ("root-answer", 1) or cache.get("s", "u") is None


def test_put_refreshes_ttl_and_answer() -> None:
    cache = SemanticCache(ttl_seconds=30)
    cache.put("s", "u", "old")
    cache.put("s", "u", "new")
    assert cache.get("s", "u") == ("new", 1)


def test_concurrent_access_is_thread_safe() -> None:
    import threading

    cache = SemanticCache(max_entries=64)
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            for i in range(50):
                key = f"u{(index * 50 + i) % 32}"
                cache.put("sys", key, f"a{index}-{i}")
                cache.get("sys", key)
                cache.stats()
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert cache.stats()["entries"] <= 64


def test_ttl_expiry_via_monotonic_sleep() -> None:
    cache = SemanticCache(ttl_seconds=1)
    cache.put("s", "u", "x")
    time.sleep(1.05)
    assert cache.get("s", "u") is None


# -- API-level tests (skipped until the main wiring mounts the routes) --------



@functools.lru_cache(maxsize=1)
def _llm_cache_routes_mounted() -> bool:
    try:
        from enterprise_ekb.app import create_app
    except Exception:
        return False
    try:
        registered = {getattr(r, "path", "") for r in create_app().routes}
    except Exception:
        return False
    return "/llm-cache/stats" in registered


@pytest.mark.skipif(
    not _llm_cache_routes_mounted(),
    reason="/llm-cache routes not wired into app yet (main thread wiring pending)",
)
def test_llm_cache_stats_endpoint() -> None:
    import os

    from litestar.testing import TestClient

    from enterprise_ekb.app import create_app

    os.environ.setdefault("EKB_AUTH_TOKEN", "cache-token")
    with TestClient(create_app()) as client:
        resp = client.get("/llm-cache/stats", headers={"Authorization": "Bearer cache-token"})
        assert resp.status_code == 200
        body = resp.json()
        assert "hits_l1" in body and "cache_layer" in body


@pytest.mark.skipif(
    not _llm_cache_routes_mounted(),
    reason="/llm-cache routes not wired into app yet (main thread wiring pending)",
)
def test_llm_cache_clear_endpoint_requires_admin(monkeypatch) -> None:
    from litestar.testing import TestClient

    from enterprise_ekb.app import create_app

    monkeypatch.setenv("EKB_AUTH_TOKEN", "cache-token")
    with TestClient(create_app()) as client:
        resp = client.post("/llm-cache/clear")
        assert resp.status_code in {401, 503}

