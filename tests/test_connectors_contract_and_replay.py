from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def _envelope(connector_system: str, idem: str) -> dict[str, object]:
    return {
        "connector_system": connector_system,
        "direction": "inbound",
        "tenant_id": "group",
        "region_id": "cn-north-1",
        "source_id": f"{connector_system}-source",
        "event_type": "order.created",
        "occurred_at": "2026-03-30T00:00:00Z",
        "idempotency_key": idem,
        "payload": {"order_id": "O-1001", "amount": 123.45},
        "metadata": {"schema_version": "1.0.0"},
    }


def test_connector_ingest_contract_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("EKB_CONNECTOR_ALLOWED_CIDRS", "10.0.0.0/8")
    client = TestClient(create_app(db_path=str(tmp_path / "connector_contract.db")))

    bad = _envelope("erp", "short")
    bad["idempotency_key"] = "x"
    bad_resp = client.post(
        "/connectors/ingest",
        json=bad,
        headers={"authorization": "Bearer test-token"},
    )
    assert bad_resp.status_code == 422

    good = _envelope("erp", "idem-erp-0001")
    good_resp = client.post(
        "/connectors/ingest",
        json=good,
        headers={"authorization": "Bearer test-token"},
    )
    assert good_resp.status_code == 200
    body = good_resp.json()
    assert body["status"] == "accepted"


def test_connector_ingest_idempotent_and_replay(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("EKB_CONNECTOR_ALLOWED_CIDRS", "10.0.0.0/8")
    client = TestClient(create_app(db_path=str(tmp_path / "connector_replay.db")))

    first = client.post(
        "/connectors/ingest",
        json=_envelope("mes", "idem-mes-1001"),
        headers={"authorization": "Bearer test-token"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "accepted"

    duplicate = client.post(
        "/connectors/ingest",
        json=_envelope("mes", "idem-mes-1001"),
        headers={"authorization": "Bearer test-token"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "replayed"

    replay_resp = client.post(
        "/connectors/replay",
        json={"connector_system": "mes", "limit": 100},
        headers={"authorization": "Bearer test-token"},
    )
    assert replay_resp.status_code == 200
    replay_body = replay_resp.json()
    assert replay_body["replayed"] >= 1
    assert replay_body["accepted"] >= 1
    assert replay_body["by_system"].get("mes", 0) >= 1


def test_connector_multi_system_replay_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("EKB_CONNECTOR_ALLOWED_CIDRS", "10.0.0.0/8")
    client = TestClient(create_app(db_path=str(tmp_path / "connector_multi_system.db")))

    systems = ["erp", "mes", "scada", "ticketing"]
    for i, system in enumerate(systems, start=1):
        resp = client.post(
            "/connectors/ingest",
            json=_envelope(system, f"idem-{system}-{i:04d}"),
            headers={"authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200

    replay_all = client.post(
        "/connectors/replay",
        json={"limit": 500},
        headers={"authorization": "Bearer test-token"},
    )
    assert replay_all.status_code == 200
    summary = replay_all.json()["by_system"]
    for system in systems:
        assert summary.get(system, 0) >= 1
