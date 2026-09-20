from pathlib import Path

import pytest
from litestar.testing import TestClient

from enterprise_ekb.app import create_app
from enterprise_ekb.retrieval import reciprocal_rank_fusion


def _capacity_payload() -> dict:
    return {"online_users": 100000, "active_ratio": 0.1, "cache_hit_ratio": 0.5, "complex_ratio": 0.3}


def test_capacity_estimate_requires_token_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "sec-token")
    monkeypatch.delenv("EKB_ENV", raising=False)
    client = TestClient(create_app(db_path=str(tmp_path / "cap-auth.db")))
    missing = client.post("/capacity/estimate", json=_capacity_payload())
    ok = client.post("/capacity/estimate", json=_capacity_payload(), headers={"Authorization": "Bearer sec-token"})
    assert missing.status_code == 401
    assert ok.status_code == 200


def test_capacity_estimate_cache_hits_visible_in_metrics(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "cap-cache.db")))
    payload = _capacity_payload()
    client.post("/capacity/estimate", json=payload)  # miss
    client.post("/capacity/estimate", json=payload)  # L1 hit
    metrics = client.get("/metrics").text
    assert 'ekb_cache_hits_total{layer="l1"}' in metrics


def test_audit_query_cached_and_consistent(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "audit-cache.db")))
    first = client.post("/audit/query", json={"limit": 5})
    second = client.post("/audit/query", json={"limit": 5})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()


def test_weighted_rrf_lets_stronger_leg_dominate() -> None:
    # a is rank1 on leg1 only; b is rank2 on leg2. Tripling leg2 flips the order.
    uniform = dict(reciprocal_rank_fusion([["a"], ["c", "b"]], k=60))
    weighted = dict(reciprocal_rank_fusion([["a"], ["c", "b"]], k=60, weights=[0.5, 3.0]))
    assert uniform["a"] > uniform["b"], "uniform weights keep a on top"
    assert weighted["b"] > weighted["a"], "2x weight on leg2 must promote b past a"


def test_async_facade_and_hot_handlers_are_native_async() -> None:
    import inspect

    from enterprise_ekb.api.context import build_context
    from enterprise_ekb.api import domain as domain_module
    from enterprise_ekb.async_facade import AsyncControlPlaneFacade

    ctx = build_context(__import__("enterprise_ekb.config", fromlist=["load_config"]).load_config(), ":memory:")
    handlers = domain_module.routes(ctx)
    by_name = {getattr(h, "fn", h).__name__: getattr(h, "fn", h) for h in handlers}
    assert asyncio.iscoroutinefunction(by_name["search_domain_capabilities"])
    assert asyncio.iscoroutinefunction(by_name["domain_capabilities_coverage"])

    async def _probe() -> dict:
        facade = AsyncControlPlaneFacade(ctx.store)
        return await facade.outbox_stats()

    assert asyncio.run(_probe())["pending"] >= 0


import asyncio  # noqa: E402
