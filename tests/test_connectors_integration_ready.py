from pathlib import Path
import json

from litestar.testing import TestClient

from enterprise_ekb.app import create_app
from enterprise_ekb import connectors as connectors_module


def _profile(system: str, name: str) -> dict[str, object]:
    return {
        "profile": {
            "connector_system": system,
            "profile_name": name,
            "base_url": "https://10.0.0.1/api",
            "auth_type": "bearer",
            "auth_config": {"token": "secret-token"},
            "timeout_ms": 5000,
            "pull_batch_size": 20,
            "status": "active",
            "metadata": {"env": "sit"},
            "adapter_type": "generic",
        }
    }


def test_profile_checkpoint_health_and_pull_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("EKB_CONNECTOR_ALLOWED_CIDRS", "10.0.0.0/8")
    client = TestClient(create_app(db_path=str(tmp_path / "connector_link.db")))

    sap_fixture_path = Path(__file__).with_name("fixtures") / "sap_odata_page.json"
    sap_fixture = json.loads(sap_fixture_path.read_text(encoding="utf-8"))

    captured_calls: list[dict[str, object]] = []

    def fake_get(self, url: str, headers: dict[str, str] | None = None, params: dict[str, object] | None = None, raise_for_status: bool = True):
        captured_calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        return sap_fixture

    monkeypatch.setattr(connectors_module.HttpAdapter, "get", fake_get)

    upsert = client.post(
        "/connectors/profiles/upsert",
        json=_profile("erp", "erp-sit"),
        headers={"authorization": "Bearer test-token"},
    )
    assert upsert.status_code == 200
    assert upsert.json()["status"] == "ok"

    set_checkpoint = client.post(
        "/connectors/checkpoint/update",
        json={
            "connector_system": "erp",
            "profile_name": "erp-sit",
            "cursor": "0",
            "watermark": "2026-03-01T00:00:00Z",
        },
        headers={"authorization": "Bearer test-token"},
    )
    assert set_checkpoint.status_code == 200

    profile_with_sap = _profile("erp", "erp-sit")
    profile_with_sap["profile"]["adapter_type"] = "sap_odata"
    profile_with_sap["profile"]["metadata"] = {
        "env": "sit",
        "endpoint": "odata",
        "delta_field": "LastChangeDateTime",
        "delta_token": "delta-001",
    }
    upsert2 = client.post(
        "/connectors/profiles/upsert",
        json=profile_with_sap,
        headers={"authorization": "Bearer test-token"},
    )
    assert upsert2.status_code == 200

    list_resp = client.post(
        "/connectors/profiles/list",
        json={"connector_system": "erp", "limit": 10},
        headers={"authorization": "Bearer test-token"},
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] == 1

    health = client.post(
        "/connectors/health",
        json={"connector_system": "erp", "profile_name": "erp-sit"},
        headers={"authorization": "Bearer test-token"},
    )
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    cp_get = client.post(
        "/connectors/checkpoint/get",
        json={"connector_system": "erp", "profile_name": "erp-sit"},
        headers={"authorization": "Bearer test-token"},
    )
    assert cp_get.status_code == 200
    assert cp_get.json()["cursor"] == "0"

    dry_pull = client.post(
        "/connectors/pull",
        json={
            "connector_system": "erp",
            "profile_name": "erp-sit",
            "mode": "dry_run",
            "limit": 5,
        },
        headers={"authorization": "Bearer test-token"},
    )
    assert dry_pull.status_code == 200
    assert dry_pull.json()["pulled"] == 2
    assert dry_pull.json()["accepted"] == 2
    assert captured_calls
    assert captured_calls[0]["params"]["$top"] == 5
    assert captured_calls[0]["params"]["$deltatoken"] == "delta-001"

    cp_after_dry = client.post(
        "/connectors/checkpoint/get",
        json={"connector_system": "erp", "profile_name": "erp-sit"},
        headers={"authorization": "Bearer test-token"},
    )
    assert cp_after_dry.status_code == 200
    assert cp_after_dry.json()["cursor"] == "0"


def test_pull_commit_advances_checkpoint_and_allows_replay(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("EKB_CONNECTOR_ALLOWED_CIDRS", "10.0.0.0/8")
    client = TestClient(create_app(db_path=str(tmp_path / "connector_commit.db")))

    client.post(
        "/connectors/profiles/upsert",
        json=_profile("mes", "mes-sit"),
        headers={"authorization": "Bearer test-token"},
    )

    commit_pull = client.post(
        "/connectors/pull",
        json={
            "connector_system": "mes",
            "profile_name": "mes-sit",
            "mode": "commit",
            "limit": 3,
        },
        headers={"authorization": "Bearer test-token"},
    )
    assert commit_pull.status_code == 200
    assert commit_pull.json()["pulled"] == 3

    cp = client.post(
        "/connectors/checkpoint/get",
        json={"connector_system": "mes", "profile_name": "mes-sit"},
        headers={"authorization": "Bearer test-token"},
    )
    assert cp.status_code == 200
    assert cp.json()["cursor"] == "3"

    replay = client.post(
        "/connectors/replay",
        json={"connector_system": "mes", "limit": 50},
        headers={"authorization": "Bearer test-token"},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] >= 1


def test_ticketing_pull_with_signature_and_fixture_replay(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("EKB_CONNECTOR_ALLOWED_CIDRS", "10.0.0.0/8")
    client = TestClient(create_app(db_path=str(tmp_path / "connector_ticketing.db")))

    fixture_path = Path(__file__).with_name("fixtures") / "servicenow_incident_page.json"
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    signed_calls: list[dict[str, object]] = []

    def fake_signed_get(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, object],
        secret: str,
        signature_header: str = "X-Signature",
    ):
        signed_calls.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "secret": secret,
                "signature_header": signature_header,
            }
        )
        return fixture_payload

    monkeypatch.setattr(connectors_module.HttpAdapter, "signed_get", fake_signed_get)

    profile_payload = _profile("ticketing", "sn-sit")
    profile_payload["profile"]["auth_type"] = "basic"
    profile_payload["profile"]["auth_config"] = {
        "username": "api-user",
        "password": "api-pass",
        "signature_secret": "hmac-secret",
    }
    profile_payload["profile"]["metadata"] = {
        "env": "sit",
        "table": "incident",
        "delta_field": "sys_updated_on",
        "watermark": "2026-03-01 00:00:00",
    }
    profile_payload["profile"]["adapter_type"] = "servicenow_table"
    upsert = client.post(
        "/connectors/profiles/upsert",
        json=profile_payload,
        headers={"authorization": "Bearer test-token"},
    )
    assert upsert.status_code == 200

    pull = client.post(
        "/connectors/pull",
        json={
            "connector_system": "ticketing",
            "profile_name": "sn-sit",
            "mode": "commit",
            "limit": 10,
        },
        headers={"authorization": "Bearer test-token"},
    )
    assert pull.status_code == 200
    body = pull.json()
    assert body["pulled"] == 2
    assert body["accepted"] == 2
    assert body["next_cursor"] == "2"
    assert signed_calls
    assert signed_calls[0]["params"]["sysparm_limit"] == 10
    assert signed_calls[0]["params"]["sysparm_offset"] == 0
    assert signed_calls[0]["params"]["sysparm_query"] == "sys_updated_on>=2026-03-01 00:00:00"
    assert signed_calls[0]["secret"] == "hmac-secret"

    checkpoint = client.post(
        "/connectors/checkpoint/get",
        json={"connector_system": "ticketing", "profile_name": "sn-sit"},
        headers={"authorization": "Bearer test-token"},
    )
    assert checkpoint.status_code == 200
    assert checkpoint.json()["cursor"] == "2"

    replay = client.post(
        "/connectors/replay",
        json={"connector_system": "ticketing", "limit": 20},
        headers={"authorization": "Bearer test-token"},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] >= 1
