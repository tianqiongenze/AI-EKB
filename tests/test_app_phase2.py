import os
from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_app_readyz_and_relay_and_audit(tmp_path: Path) -> None:
    os.environ.pop("EKB_AUTH_TOKEN", None)
    os.environ.pop("EKB_ENV", None)
    db_path = tmp_path / "phase2.db"
    client = TestClient(create_app(db_path=str(db_path)))

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    register_resp = client.post(
        "/skills/register",
        json={
            "skill_name": "qa-agent",
            "version": "1.0.0",
            "owner": "team-a",
            "risk_level": "low",
            "allowed_tools": ["qa.query"],
            "allowed_domains": ["quality"],
            "residency_scope": ["cn-north-1"],
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "changelog": "release",
        },
    )
    assert register_resp.status_code == 200

    client.post(
        "/skills/promote",
        json={"skill_name": "qa-agent", "version": "1.0.0", "target_stage": "review"},
    )
    client.post(
        "/skills/promote",
        json={"skill_name": "qa-agent", "version": "1.0.0", "target_stage": "staging"},
    )
    client.post(
        "/skills/promote",
        json={"skill_name": "qa-agent", "version": "1.0.0", "target_stage": "production"},
    )

    invoke_resp = client.post(
        "/mcp/invoke",
        json={
            "tenant_id": "group",
            "region_id": "cn-north-1",
            "plant_id": "plant-bj",
            "domain": "quality",
            "user_or_agent_id": "u-1",
            "skill_name": "qa-agent",
            "skill_version": "1.0.0",
            "tool_name": "qa.query",
            "payload": {"q": "test"},
        },
    )
    assert invoke_resp.status_code == 200

    audit_resp = client.post("/audit/query", json={"limit": 10})
    assert audit_resp.status_code == 200
    assert audit_resp.json()["count"] >= 1

    relay_resp = client.post("/events/relay", json={"batch_size": 100})
    assert relay_resp.status_code == 200
    assert relay_resp.json()["relay"]["published"] >= 1
    assert "processing" in relay_resp.json()["outbox"]
