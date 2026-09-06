import os
from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_readyz_reports_driver(tmp_path: Path) -> None:
    os.environ["EKB_DB_DRIVER"] = "sqlite"
    db_path = tmp_path / "driver.db"
    app = create_app(db_path=str(db_path))
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db_driver"] == "sqlite"


def test_load_config_contains_middleware_defaults() -> None:
    os.environ["EKB_DB_DRIVER"] = "sqlite"
    from enterprise_ekb.config import load_config

    cfg = load_config()
    assert cfg.redis_max_connections >= 1
    assert cfg.neo4j_max_connection_pool_size >= 1
    assert cfg.milvus_db_name == "default"


def test_load_config_parses_tenant_region_rate_limits() -> None:
    os.environ["EKB_DB_DRIVER"] = "sqlite"
    os.environ["EKB_TENANT_REGION_RATE_LIMITS"] = "group:cn-north-1=12000,group:eu-central-1=9000"
    from enterprise_ekb.config import load_config

    cfg = load_config()
    assert cfg.tenant_region_rate_limits["group:cn-north-1"] == 12000
    assert cfg.tenant_region_rate_limits["group:eu-central-1"] == 9000


def test_load_config_datalake_allowlists() -> None:
    os.environ["EKB_DB_DRIVER"] = "sqlite"
    os.environ["EKB_DATALAKE_ALLOWED_TOPIC_PREFIXES"] = "persistent://group/connectors/,persistent://group/a2a/"
    os.environ["EKB_DATALAKE_ALLOWED_TABLE_PREFIXES"] = "ekb_,analytics_"
    from enterprise_ekb.config import load_config

    cfg = load_config()
    assert "persistent://group/connectors/" in cfg.datalake_allowed_topic_prefixes
    assert "analytics_" in cfg.datalake_allowed_table_prefixes
