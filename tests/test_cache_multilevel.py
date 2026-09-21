from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app
from enterprise_ekb.cache import MultiLevelCache


def test_l1_hit_miss_and_metrics() -> None:
    cache = MultiLevelCache(l1_ttl_seconds=60, l2_ttl_seconds=300)
    key = cache.key("unit", "a", 1)

    hit, value = cache.get_json(key)
    assert hit is False and value is None

    cache.set_json(key, {"v": 42})
    hit, value = cache.get_json(key)
    assert hit is True and value == {"v": 42}


def test_invalidate_prefix_clears_entries() -> None:
    cache = MultiLevelCache()
    key = cache.key("domain:search", "manufacturing")
    cache.set_json(key, {"count": 0})
    assert cache.delete_prefix("domain:") >= 1
    hit, _ = cache.get_json(key)
    assert hit is False


def test_domain_search_reflects_upsert_with_cache_enabled(tmp_path: Path) -> None:
    # Cache enabled (in-process L1): search results must not go stale after upsert.
    client = TestClient(create_app(db_path=str(tmp_path / "cache.db")))

    first = client.get("/domain/capabilities/coverage")
    assert first.status_code == 200

    resp = client.post(
        "/domain/capabilities/bootstrap",
        json={"owner": "domain-pmo"},
    )
    assert resp.status_code == 200

    coverage_after = client.get("/domain/capabilities/coverage")
    assert coverage_after.status_code == 200
    summary = coverage_after.json()["summary"]
    assert summary["not_met"] == 0, "coverage must reflect bootstrap despite warm cache"

    search_after = client.post(
        "/domain/capabilities/search",
        json={"domain": "manufacturing", "limit": 50},
    )
    assert search_after.status_code == 200
    assert search_after.json()["count"] > 0


def test_policy_decision_cache_invalidated_by_promotion(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "policy-cache.db")))
    manifest = {
        "skill_name": "cache-skill",
        "version": "1.0.0",
        "description": "d",
        "owner": "owner-1",
        "allowed_tools": ["tool-a"],
        "allowed_domains": ["manufacturing"],
        "residency_scope": ["cn-north-1"],
        "risk_level": "low",
        "changelog": "init",
    }
    register = client.post("/skills/register", json=manifest)
    assert register.status_code == 200

    deny = client.post(
        "/mcp/invoke",
        json={
            "tenant_id": "group",
            "region_id": "cn-north-1",
            "plant_id": "plant-1",
            "user_or_agent_id": "agent-1",
            "skill_name": "cache-skill",
            "skill_version": "1.0.0",
            "tool_name": "tool-a",
            "domain": "manufacturing",
            "payload": {},
        },
    )
    assert deny.status_code == 403, "draft skill must be denied"

    for stage in ("review", "staging", "production"):
        promote = client.post(
            "/skills/promote",
            json={"skill_name": "cache-skill", "version": "1.0.0", "target_stage": stage},
        )
        assert promote.status_code == 200, f"promotion to {stage} failed"

    allow = client.post(
        "/mcp/invoke",
        json={
            "tenant_id": "group",
            "region_id": "cn-north-1",
            "plant_id": "plant-1",
            "user_or_agent_id": "agent-1",
            "skill_name": "cache-skill",
            "skill_version": "1.0.0",
            "tool_name": "tool-a",
            "domain": "manufacturing",
            "payload": {},
        },
    )
    assert allow.status_code == 200, "promoted skill must be allowed immediately (cache invalidated by epoch)"
