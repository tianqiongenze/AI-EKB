import os
from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_a2a_supervision_scan_requires_auth(tmp_path: Path) -> None:
    os.environ["EKB_AUTH_TOKEN"] = "test-token"
    db_path = tmp_path / "a2a_supervision_auth.db"
    client = TestClient(create_app(db_path=str(db_path)))

    resp = client.post(
        "/a2a/supervision/scan",
        json={
            "lookback_limit": 100,
            "dead_event_threshold": 10,
            "failed_task_ratio_threshold": 0.2,
        },
    )
    assert resp.status_code == 401


def test_a2a_supervision_scan_returns_summary(tmp_path: Path) -> None:
    os.environ["EKB_AUTH_TOKEN"] = "test-token"
    db_path = tmp_path / "a2a_supervision_summary.db"
    client = TestClient(create_app(db_path=str(db_path)))
    headers = {"Authorization": "Bearer test-token"}

    scan_resp = client.post(
        "/a2a/supervision/scan",
        json={
            "lookback_limit": 100,
            "dead_event_threshold": 99999,
            "failed_task_ratio_threshold": 1.0,
        },
        headers=headers,
    )
    assert scan_resp.status_code == 200
    payload = scan_resp.json()
    assert payload["status"] in {"ok", "alert"}
    assert "summary" in payload
    assert "alert_count" in payload["summary"]
