from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    db_driver: str
    db_path: str
    tidb_host: str
    tidb_port: int
    tidb_user: str
    tidb_password: str
    tidb_database: str
    event_publisher_backend: str
    pulsar_service_url: str
    pulsar_token: str
    pulsar_tls_enabled: bool
    pulsar_ca_cert_path: str
    redis_url: str
    redis_max_connections: int
    redis_socket_timeout_seconds: float
    redis_socket_connect_timeout_seconds: float
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_max_connection_pool_size: int
    milvus_uri: str
    milvus_token: str
    milvus_db_name: str
    auth_token: str
    mcp_rate_limit_per_minute: int
    a2a_rate_limit_per_minute: int
    a2a_enabled: bool
    a2a_topic: str
    a2a_subscription: str
    connector_allowed_cidrs: list[str]
    connector_auth_enabled: bool
    tenant_region_rate_limits: dict[str, int]
    subagent_retry_max_attempts: int
    subagent_retry_base_delay_ms: int
    subagent_retry_jitter_ms: int
    subagent_dlq_topic_template: str
    mcp_invoke_retry_attempts: int
    mcp_invoke_retry_base_delay_ms: int
    events_relay_retry_attempts: int
    events_relay_retry_base_delay_ms: int
    events_relay_batch_size_max: int
    datalake_allowed_topic_prefixes: list[str]
    datalake_allowed_table_prefixes: list[str]
    rate_limit_backend: str
    cache_backend: str
    cache_l1_ttl_seconds: int
    cache_l2_ttl_seconds: int
    request_signing_secret: str
    replay_window_seconds: int
    jwt_hs256_secret: str
    jwt_expected_audience: str
    log_format: str
    relay_background_enabled: bool
    relay_interval_seconds: float


def _parse_tenant_region_rate_limits(raw: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for part in raw.split(","):
        item = part.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            limit = int(value)
        except ValueError:
            continue
        if limit > 0:
            parsed[key] = limit
    return parsed


def _parse_csv_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_config() -> AppConfig:
    return AppConfig(
        db_driver=os.getenv("EKB_DB_DRIVER", "sqlite"),
        db_path=os.getenv("EKB_DB_PATH", "./data/control_plane.db"),
        tidb_host=os.getenv("EKB_TIDB_HOST", "127.0.0.1"),
        tidb_port=int(os.getenv("EKB_TIDB_PORT", "4000")),
        tidb_user=os.getenv("EKB_TIDB_USER", "root"),
        tidb_password=os.getenv("EKB_TIDB_PASSWORD", ""),
        tidb_database=os.getenv("EKB_TIDB_DATABASE", "ekb_control_plane"),
        event_publisher_backend=os.getenv("EKB_EVENT_PUBLISHER_BACKEND", "memory"),
        pulsar_service_url=os.getenv("EKB_PULSAR_SERVICE_URL", "pulsar://127.0.0.1:6650"),
        pulsar_token=os.getenv("EKB_PULSAR_TOKEN", ""),
        pulsar_tls_enabled=os.getenv("EKB_PULSAR_TLS_ENABLED", "false").lower() == "true",
        pulsar_ca_cert_path=os.getenv("EKB_PULSAR_CA_CERT_PATH", ""),
        redis_url=os.getenv("EKB_REDIS_URL", "redis://127.0.0.1:6379/0"),
        redis_max_connections=int(os.getenv("EKB_REDIS_MAX_CONNECTIONS", "200")),
        redis_socket_timeout_seconds=float(os.getenv("EKB_REDIS_SOCKET_TIMEOUT_SECONDS", "0.2")),
        redis_socket_connect_timeout_seconds=float(
            os.getenv("EKB_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", "0.2")
        ),
        neo4j_uri=os.getenv("EKB_NEO4J_URI", "bolt://127.0.0.1:7687"),
        neo4j_username=os.getenv("EKB_NEO4J_USERNAME", "neo4j"),
        neo4j_password=os.getenv("EKB_NEO4J_PASSWORD", ""),
        neo4j_max_connection_pool_size=int(os.getenv("EKB_NEO4J_MAX_CONNECTION_POOL_SIZE", "100")),
        milvus_uri=os.getenv("EKB_MILVUS_URI", "http://127.0.0.1:19530"),
        milvus_token=os.getenv("EKB_MILVUS_TOKEN", ""),
        milvus_db_name=os.getenv("EKB_MILVUS_DB_NAME", "default"),
        auth_token=os.getenv("EKB_AUTH_TOKEN", ""),
        mcp_rate_limit_per_minute=int(os.getenv("EKB_MCP_RATE_LIMIT_PER_MINUTE", "6000")),
        a2a_rate_limit_per_minute=int(os.getenv("EKB_A2A_RATE_LIMIT_PER_MINUTE", "12000")),
        a2a_enabled=os.getenv("EKB_A2A_ENABLED", "false").lower() == "true",
        a2a_topic=os.getenv("EKB_A2A_TOPIC", "persistent://group/a2a/default"),
        a2a_subscription=os.getenv("EKB_A2A_SUBSCRIPTION", "yadea-ekb-a2a"),
        connector_allowed_cidrs=[
            cidr.strip()
            for cidr in os.getenv("EKB_CONNECTOR_ALLOWED_CIDRS", "").split(",")
            if cidr.strip()
        ],
        connector_auth_enabled=os.getenv("EKB_CONNECTOR_AUTH_ENABLED", "true").lower() == "true",
        tenant_region_rate_limits=_parse_tenant_region_rate_limits(
            os.getenv("EKB_TENANT_REGION_RATE_LIMITS", "")
        ),
        subagent_retry_max_attempts=int(os.getenv("EKB_SUBAGENT_RETRY_MAX_ATTEMPTS", "5")),
        subagent_retry_base_delay_ms=int(os.getenv("EKB_SUBAGENT_RETRY_BASE_DELAY_MS", "200")),
        subagent_retry_jitter_ms=int(os.getenv("EKB_SUBAGENT_RETRY_JITTER_MS", "150")),
        subagent_dlq_topic_template=os.getenv(
            "EKB_SUBAGENT_DLQ_TOPIC_TEMPLATE",
            "persistent://{tenant}/a2a-dlq/{region}/{sub_agent_type}",
        ),
        mcp_invoke_retry_attempts=int(os.getenv("EKB_MCP_INVOKE_RETRY_ATTEMPTS", "3")),
        mcp_invoke_retry_base_delay_ms=int(os.getenv("EKB_MCP_INVOKE_RETRY_BASE_DELAY_MS", "20")),
        events_relay_retry_attempts=int(os.getenv("EKB_EVENTS_RELAY_RETRY_ATTEMPTS", "3")),
        events_relay_retry_base_delay_ms=int(os.getenv("EKB_EVENTS_RELAY_RETRY_BASE_DELAY_MS", "30")),
        events_relay_batch_size_max=int(os.getenv("EKB_EVENTS_RELAY_BATCH_SIZE_MAX", "200")),
        datalake_allowed_topic_prefixes=_parse_csv_list(
            os.getenv(
                "EKB_DATALAKE_ALLOWED_TOPIC_PREFIXES",
                "persistent://group/control/,persistent://group/audit/,persistent://group/observability/",
            )
        ),
        datalake_allowed_table_prefixes=_parse_csv_list(
            os.getenv("EKB_DATALAKE_ALLOWED_TABLE_PREFIXES", "ekb_")
        ),
        rate_limit_backend=os.getenv("EKB_RATE_LIMIT_BACKEND", "memory"),
        cache_backend=os.getenv("EKB_CACHE_BACKEND", "memory"),
        cache_l1_ttl_seconds=int(os.getenv("EKB_CACHE_L1_TTL_SECONDS", "60")),
        cache_l2_ttl_seconds=int(os.getenv("EKB_CACHE_L2_TTL_SECONDS", "300")),
        request_signing_secret=os.getenv("EKB_REQUEST_SIGNING_SECRET", ""),
        replay_window_seconds=int(os.getenv("EKB_REPLAY_WINDOW_SECONDS", "300")),
        jwt_hs256_secret=os.getenv("EKB_JWT_HS256_SECRET", ""),
        jwt_expected_audience=os.getenv("EKB_JWT_EXPECTED_AUDIENCE", ""),
        log_format=os.getenv("EKB_LOG_FORMAT", "text"),
        relay_background_enabled=os.getenv("EKB_RELAY_BACKGROUND_ENABLED", "false").lower() == "true",
        relay_interval_seconds=float(os.getenv("EKB_RELAY_INTERVAL_SECONDS", "5")),
    )
