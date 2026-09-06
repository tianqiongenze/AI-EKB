import os
from pathlib import Path

import pytest
from litestar.testing import TestClient

from enterprise_ekb.app import create_app


@pytest.fixture()
def auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token-123")
    monkeypatch.delenv("EKB_ENV", raising=False)


def test_metrics_endpoint_exposes_prometheus_format(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "metrics.db")))
    client.get("/healthz")
    client.get("/healthz")

    resp = client.get("/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "# TYPE ekb_http_request_duration_seconds summary" in body
    assert 'path="/healthz"' in body
    assert "ekb_outbox_events" in body


def test_metrics_endpoint_rejects_garbage_path_label_cardinality(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "metrics2.db")))
    client.get("/no-such-route-xyz")
    body = client.get("/metrics").text
    # Unmatched request paths must never become metric labels (cardinality safety).
    # Note: Litestar does not run app middleware for unmatched (404) requests, so they
    # produce no observation; on frameworks that do, they normalize to "unmatched".
    assert "no-such-route-xyz" not in body


def test_protected_endpoint_rejects_missing_and_wrong_token(auth_env, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EKB_DATALAKE_ALLOWED_TOPIC_PREFIXES", "persistent://group/control/,persistent://group/connectors/")
    monkeypatch.setenv("EKB_DATALAKE_ALLOWED_TABLE_PREFIXES", "ekb_")
    client = TestClient(create_app(db_path=str(tmp_path / "auth1.db")))
    payload = {
        "table_name": "ekb_test_table",
        "table_format": "iceberg",
        "domain": "manufacturing",
        "source_topic": "persistent://group/connectors/erp-ingested",
        "tenant_id": "group",
        "region_id": "cn-north-1",
    }
    missing = client.post("/datalake/tables/register", json=payload)
    wrong = client.post(
        "/datalake/tables/register",
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_protected_endpoint_accepts_correct_token(auth_env, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EKB_DATALAKE_ALLOWED_TOPIC_PREFIXES", "persistent://group/control/,persistent://group/connectors/")
    monkeypatch.setenv("EKB_DATALAKE_ALLOWED_TABLE_PREFIXES", "ekb_")
    client = TestClient(create_app(db_path=str(tmp_path / "auth2.db")))
    resp = client.post(
        "/datalake/tables/register",
        json={
            "table_name": "ekb_test_table",
            "table_format": "iceberg",
            "domain": "manufacturing",
            "source_topic": "persistent://group/connectors/erp-ingested",
            "tenant_id": "group",
            "region_id": "cn-north-1",
        },
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert resp.status_code == 200


def test_admin_endpoints_still_fail_closed_without_token_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EKB_ENV", "production")
    monkeypatch.delenv("EKB_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(db_path=str(tmp_path / "prod_fail_closed.db")))
    resp = client.post(
        "/datalake/tables/register",
        json={
            "table_name": "ekb_test_table",
            "table_format": "iceberg",
            "domain": "manufacturing",
            "source_topic": "persistent://group/connectors/erp-ingested",
            "tenant_id": "group",
            "region_id": "cn-north-1",
        },
    )
    assert resp.status_code == 503
