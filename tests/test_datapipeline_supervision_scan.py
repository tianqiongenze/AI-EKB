import os
from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_datapipeline_supervision_scan_returns_result(tmp_path: Path) -> None:
    os.environ["EKB_AUTH_TOKEN"] = "pipeline-token"
    client = TestClient(create_app(db_path=str(tmp_path / "pipeline_supervision.db")))
    headers = {"Authorization": "Bearer pipeline-token"}

    resp = client.post(
        "/datapipeline/supervision/scan",
        json={
            "lookback_limit": 100,
            "dead_event_threshold": 99999,
            "missing_signal_threshold": 0,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] in {"ok", "alert"}
    assert "summary" in payload
