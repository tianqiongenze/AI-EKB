import os
from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_admin_endpoints_fail_closed_without_token_in_production(tmp_path: Path) -> None:
    os.environ["EKB_ENV"] = "production"
    os.environ.pop("EKB_AUTH_TOKEN", None)

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
