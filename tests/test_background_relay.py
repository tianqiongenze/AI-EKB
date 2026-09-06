import time
from pathlib import Path

import pytest
from litestar.testing import TestClient

from enterprise_ekb.app import create_app


@pytest.fixture()
def background_relay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKB_RELAY_BACKGROUND_ENABLED", "true")
    monkeypatch.setenv("EKB_RELAY_INTERVAL_SECONDS", "0.2")
    monkeypatch.delenv("EKB_ENV", raising=False)


def test_background_relay_publishes_pending_events(background_relay_env, tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "bg-relay.db")))

    with client:
        resp = client.post(
            "/skills/register",
            json={
                "skill_name": "relay-skill",
                "version": "1.0.0",
                "owner": "owner-1",
                "description": "d",
                "allowed_tools": ["tool-a"],
                "allowed_domains": ["manufacturing"],
                "residency_scope": ["cn-north-1"],
                "risk_level": "low",
                "changelog": "init",
            },
        )
        assert resp.status_code == 200

        # The background loop claims and publishes without any manual /events/relay call.
        deadline = time.time() + 5
        stats = {}
        while time.time() < deadline:
            outbox = client.get("/readyz").json()["outbox"]
            if outbox["published"] > 0:
                stats = outbox
                break
            time.sleep(0.1)
        assert stats.get("published", 0) >= 1, f"background relay did not publish: {stats}"
        assert stats.get("pending", 0) == 0


def test_background_relay_disabled_by_default(tmp_path: Path) -> None:
    with TestClient(create_app(db_path=str(tmp_path / "relay-off.db"))) as client:
        client.post(
            "/skills/register",
            json={
                "skill_name": "relay-off-skill",
                "version": "1.0.0",
                "owner": "owner-1",
                "description": "d",
                "allowed_tools": ["tool-a"],
                "allowed_domains": ["manufacturing"],
                "residency_scope": ["cn-north-1"],
                "risk_level": "low",
                "changelog": "init",
            },
        )
        time.sleep(0.6)
        outbox = client.get("/readyz").json()["outbox"]
        assert outbox["pending"] >= 1, "without the flag the relay must stay manual"
