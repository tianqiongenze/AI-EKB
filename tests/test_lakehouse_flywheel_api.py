from pathlib import Path

import pytest
from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_register_datalake_table_pipeline_and_flywheel_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EKB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv(
        "EKB_DATALAKE_ALLOWED_TOPIC_PREFIXES", "persistent://group/control/,persistent://group/connectors/"
    )
    monkeypatch.setenv("EKB_DATALAKE_ALLOWED_TABLE_PREFIXES", "ekb_")
    db_path = tmp_path / "lakehouse_flywheel.db"
    client = TestClient(create_app(db_path=str(db_path)))
    headers = {"Authorization": "Bearer test-token"}

    table_resp = client.post(
        "/datalake/tables/register",
        json={
            "table_name": "ekb_bronze_connector_events",
            "table_format": "iceberg",
            "domain": "manufacturing",
            "source_topic": "persistent://group/connectors/erp-ingested",
            "tenant_id": "group",
            "region_id": "cn-north-1",
            "partition_fields": ["tenant_id", "region_id", "event_date"],
            "primary_keys": ["connector_system", "idempotency_key"],
            "retention_days": 90,
            "compaction_strategy": "bin_pack",
            "table_schema": {"fields": [{"name": "tenant_id", "type": "string"}]},
        },
        headers=headers,
    )
    assert table_resp.status_code == 200
    assert table_resp.json()["status"] == "registered"

    pipeline_resp = client.post(
        "/flink/pipelines/register",
        json={
            "job_name": "flink_connector_bronze_ingest",
            "mode": "streaming",
            "source_topic": "persistent://group/connectors/erp-ingested",
            "sink_table": "ekb_bronze_connector_events",
            "checkpoint_interval_ms": 30000,
            "watermark_delay_seconds": 30,
            "parallelism": 8,
            "exactly_once": True,
        },
        headers=headers,
    )
    assert pipeline_resp.status_code == 200
    assert pipeline_resp.json()["status"] == "registered"

    flywheel_resp = client.post(
        "/flywheel/events",
        json={
            "tenant_id": "group",
            "region_id": "cn-north-1",
            "plant_id": "plant-bj",
            "stage": "feedback",
            "objective": "improve anomaly precision",
            "trace_id": "trace-12345",
            "payload": {"precision": 0.91, "recall": 0.87},
        },
        headers=headers,
    )
    assert flywheel_resp.status_code == 200
    assert flywheel_resp.json()["status"] == "recorded"
