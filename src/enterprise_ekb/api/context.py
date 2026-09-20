"""Shared control-plane context (bounded-context route modules read from here).

Extracted from create_app as the DDD carrier: build_context wires infrastructure
and services exactly as create_app did; route modules receive the context and
close over it.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import secrets
import socket
import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

from litestar import Request
from litestar.exceptions import HTTPException

from enterprise_ekb.cache import MultiLevelCache
from enterprise_ekb.config import AppConfig
from enterprise_ekb.connectors import ConnectorRuntime
from enterprise_ekb.domain_capability import DomainCapabilityService
from enterprise_ekb.event_bus import InMemoryPublisher, OutboxRelay, PulsarPublisher
from enterprise_ekb.harness import HarnessGate
from enterprise_ekb.mcp_gateway import MCPGateway
from enterprise_ekb.policy import PolicyEngine
from enterprise_ekb.rate_limiter import TenantRegionRateLimiter, TokenBucketRateLimiter
from enterprise_ekb.risk_control import DistributedRateLimiter
from enterprise_ekb.skill_registry import SkillRegistry
from enterprise_ekb.storage import ReplicaRoutingStore, SQLiteControlPlaneStore
from enterprise_ekb.tidb_store import TiDBControlPlaneStore
from enterprise_ekb.middleware_clients import (
    HighPerformanceMilvusClient,
    HighPerformanceNeo4jClient,
    MilvusConfig,
    Neo4jConfig,
)
from enterprise_ekb.a2a_runtime import A2AConsumerConfig, build_a2a_consumer
from enterprise_ekb.risk_control import NonceStore, verify_bearer_credential

_logger = logging.getLogger("enterprise_ekb.app")


def _dump_alert(alert: Any) -> dict[str, Any]:
    dump = getattr(alert, "model_dump", None)
    if callable(dump):
        result = dump(mode="json")
        if isinstance(result, dict):
            return cast(dict[str, Any], result)
    legacy = alert.dict()
    if isinstance(legacy, dict):
        return cast(dict[str, Any], legacy)
    raise TypeError("supervision alert serialization failed")


def _run_with_retry(
    operation: Any,
    *,
    attempts: int,
    base_delay_ms: int,
) -> Any:
    safe_attempts = max(1, attempts)
    safe_base_delay_ms = max(1, base_delay_ms)
    last_error: Exception | None = None
    for attempt in range(safe_attempts):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt == safe_attempts - 1:
                break
            time.sleep((safe_base_delay_ms * (2**attempt)) / 1000.0)
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable retry operation")


@dataclass
class ControlPlaneContext:
    config: Any = None
    store: Any = None
    skill_registry: Any = None
    policy_engine: Any = None
    mcp_gateway: Any = None
    harness_gate: Any = None
    publisher: Any = None
    outbox_relay: Any = None
    domain_capability_service: Any = None
    connector_runtime: Any = None
    mcp_rate_limiter: Any = None
    a2a_rate_limiter: Any = None
    tenant_region_mcp_limiter: Any = None
    tenant_region_a2a_limiter: Any = None
    redis_backend: Any = None
    distributed_mcp_limiter: Any = None
    distributed_a2a_limiter: Any = None
    nonce_store: Any = None
    cache: Any = None
    milvus_client: Any = None
    neo4j_client: Any = None
    a2a_consumer: Any = None
    resolved_db_path: Any = None
    auth_disabled_warning_emitted: bool = False

    @staticmethod
    def _dump_alert(alert: Any) -> dict[str, Any]:
        return _dump_alert(alert)

    @staticmethod
    def _run_with_retry(operation: Any, *, attempts: int, base_delay_ms: int) -> Any:
        return _run_with_retry(operation, attempts=attempts, base_delay_ms=base_delay_ms)

    def _require_admin_auth(self, request: Request) -> str:
        if not self.config.auth_token:
            if os.getenv("EKB_ENV", "").lower() == "production":
                raise HTTPException(status_code=503, detail="auth_not_configured")
            if not self.auth_disabled_warning_emitted:
                _logger.warning(
                    "EKB_AUTH_TOKEN is empty; admin endpoints are running without authentication"
                    " (set EKB_ENV=production to fail closed)"
                )
                self.auth_disabled_warning_emitted = True
            return ""
        auth_header = request.headers.get("authorization", "")
        if not self._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        return auth_header

    def _require_auth(self, request: Request) -> None:
        if self.config.connector_auth_enabled and not self.config.auth_token:
            if os.getenv("EKB_ENV", "").lower() == "production":
                self._audit_connector_auth_failure(request, "auth_not_configured")
                raise HTTPException(status_code=503, detail="auth_not_configured")
            return
        if self.config.connector_auth_enabled and self.config.auth_token:
            if not self._bearer_matches(request):
                self._audit_connector_auth_failure(request, "unauthorized")
                raise HTTPException(status_code=401, detail="unauthorized")

    def _bearer_matches(self, request: Request) -> bool:
        auth_header = request.headers.get("authorization", "")
        if secrets.compare_digest(auth_header, f"Bearer {self.config.auth_token}"):
            return True
        return verify_bearer_credential(
            auth_header,
            self.config.auth_token,
            self.config.jwt_hs256_secret,
            self.config.jwt_expected_audience,
        )

    auth_disabled_warning_emitted = False


    def _audit_connector_auth_failure(self, request: Request, detail: str) -> None:
        client_host = request.client.host if request.client else "unknown"
        self.store.append_audit(
            tenant_id="unknown",
            region_id="unknown",
            plant_id="unknown",
            user_or_agent_id=client_host,
            skill_name="connector",
            skill_version="n/a",
            tool_name=request.url.path,
            decision_reason=detail,
            accepted=False,
            payload={
                "path": request.url.path,
                "method": request.method,
                "client": client_host,
            },
        )


    def _validate_datalake_topic(self, topic: str) -> None:
        allowed = any(topic.startswith(prefix) for prefix in self.config.datalake_allowed_topic_prefixes)
        if not allowed:
            raise HTTPException(status_code=400, detail="source_topic_not_allowed")

    def _validate_table_name(self, table_name: str) -> None:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{2,190}", table_name):
            raise HTTPException(status_code=400, detail="invalid_table_name")
        allowed = any(table_name.startswith(prefix) for prefix in self.config.datalake_allowed_table_prefixes)
        if not allowed:
            raise HTTPException(status_code=400, detail="table_name_not_allowed")

    def _validate_job_name(self, job_name: str) -> None:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_\-]{2,190}", job_name):
            raise HTTPException(status_code=400, detail="invalid_job_name")

    def _is_ip_allowed(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return False
        if not self.config.connector_allowed_cidrs:
            return False
        for cidr in self.config.connector_allowed_cidrs:
            try:
                if addr in ipaddress.ip_network(cidr, strict=False):
                    return True
            except ValueError:
                continue
        return False

    def _validate_connector_base_url(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(status_code=400, detail="invalid_base_url_scheme")
        if not parsed.hostname:
            raise HTTPException(status_code=400, detail="invalid_base_url_host")
        try:
            addrinfo = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror as exc:
            raise HTTPException(status_code=400, detail="invalid_base_url_dns") from exc
        resolved = {str(info[4][0]) for info in addrinfo if info[4]}
        if not resolved:
            raise HTTPException(status_code=400, detail="invalid_base_url_resolution")
        if not all(self._is_ip_allowed(ip) for ip in resolved):
            raise HTTPException(status_code=400, detail="base_url_not_allowed")

    def _model_to_dict(self, model: Any) -> dict[str, Any]:
        dump = getattr(model, "model_dump", None)
        if callable(dump):
            result = dump(mode="json")
            if isinstance(result, dict):
                return cast(dict[str, Any], result)
            raise TypeError("model_dump must return dict for API serialization")
        legacy = model.dict()
        if isinstance(legacy, dict):
            return cast(dict[str, Any], legacy)
        raise TypeError("model.dict() must return dict for API serialization")



def build_context(config: AppConfig, db_path: str | None = None) -> ControlPlaneContext:
    resolved_db_path = db_path or config.db_path
    external_clients_enabled = os.getenv("EKB_ENABLE_EXTERNAL_CLIENTS", "false").lower() == "true"

    if config.db_driver.lower() == "crdb":
        from enterprise_ekb.crdb_store import CockroachDBControlPlaneStore

        store = CockroachDBControlPlaneStore(
            host=config.crdb_host,
            port=config.crdb_port,
            user=config.crdb_user,
            password=config.crdb_password,
            database=config.crdb_database,
            follower_reads=config.crdb_follower_reads,
        )
    elif config.db_driver.lower() == "tidb":
        store = TiDBControlPlaneStore(
            host=config.tidb_host,
            port=config.tidb_port,
            user=config.tidb_user,
            password=config.tidb_password,
            database=config.tidb_database,
        )
    else:
        store = SQLiteControlPlaneStore(db_path=resolved_db_path)
    redis_backend = None
    if config.rate_limit_backend.lower() == "redis" or config.cache_backend.lower() == "redis":
        try:
            redis_backend = HighPerformanceRedisClient(
                RedisConfig(
                    url=config.redis_url,
                    max_connections=config.redis_max_connections,
                    socket_timeout_seconds=config.redis_socket_timeout_seconds,
                    socket_connect_timeout_seconds=config.redis_socket_connect_timeout_seconds,
                )
            ).client
        except Exception:
            _logger.warning("Redis backend init failed; distributed limits and L2 cache disabled", exc_info=True)
            redis_backend = None
    cache = MultiLevelCache(
        l1_ttl_seconds=config.cache_l1_ttl_seconds,
        l2_ttl_seconds=config.cache_l2_ttl_seconds,
        redis_client=redis_backend if config.cache_backend.lower() == "redis" else None,
    )
    skill_registry = SkillRegistry(store=store)
    policy_engine = PolicyEngine(skill_registry=skill_registry, cache=cache)
    mcp_gateway = MCPGateway(policy_engine=policy_engine)
    harness_gate = HarnessGate()
    if config.event_publisher_backend.lower() == "pulsar" and config.pulsar_service_url:
        try:
            publisher = PulsarPublisher(
                service_url=config.pulsar_service_url,
                token=config.pulsar_token,
                tls_enabled=config.pulsar_tls_enabled,
                ca_cert_path=config.pulsar_ca_cert_path,
            )
        except Exception:
            _logger.warning(
                "Pulsar publisher init failed for %s; falling back to InMemoryPublisher",
                config.pulsar_service_url,
                exc_info=True,
            )
            publisher = InMemoryPublisher()
    else:
        publisher = InMemoryPublisher()
    outbox_relay = OutboxRelay(store=store, publisher=publisher)
    # Read-write separation (review §10): handlers/queries route reads to the
    # replica; the relay above deliberately keeps the primary store.
    if config.db_driver.lower() == "sqlite" and config.read_replica_db_path:
        store = ReplicaRoutingStore(
            primary=store,
            replica=SQLiteControlPlaneStore(db_path=config.read_replica_db_path),
        )
    elif config.db_driver.lower() == "tidb" and config.tidb_read_host:
        store = ReplicaRoutingStore(
            primary=store,
            replica=TiDBControlPlaneStore(
                host=config.tidb_read_host,
                port=config.tidb_port,
                user=config.tidb_user,
                password=config.tidb_password,
                database=config.tidb_database,
            ),
        )
    domain_capability_service = DomainCapabilityService(store=store, cache=cache)
    connector_runtime = ConnectorRuntime(store=store)
    mcp_rate_limiter = TokenBucketRateLimiter(config.mcp_rate_limit_per_minute)
    a2a_rate_limiter = TokenBucketRateLimiter(config.a2a_rate_limit_per_minute)
    tenant_region_mcp_limiter = TenantRegionRateLimiter(config.mcp_rate_limit_per_minute)
    tenant_region_a2a_limiter = TenantRegionRateLimiter(config.a2a_rate_limit_per_minute)

    distributed_mcp_limiter = (
        DistributedRateLimiter(config.mcp_rate_limit_per_minute, redis_client=redis_backend)
        if redis_backend is not None
        else None
    )
    distributed_a2a_limiter = (
        DistributedRateLimiter(config.a2a_rate_limit_per_minute, redis_client=redis_backend)
        if redis_backend is not None
        else None
    )
    nonce_store = NonceStore(ttl_seconds=config.replay_window_seconds, redis_client=redis_backend)
    milvus_client = None
    neo4j_client = None
    if external_clients_enabled:
        try:
            milvus_client = HighPerformanceMilvusClient(
                MilvusConfig(
                    uri=config.milvus_uri,
                    token=config.milvus_token,
                    db_name=config.milvus_db_name,
                )
            )
        except Exception:
            _logger.warning("Milvus client init failed for %s; vector features degrade", config.milvus_uri, exc_info=True)
            milvus_client = None
        try:
            neo4j_client = HighPerformanceNeo4jClient(
                Neo4jConfig(
                    uri=config.neo4j_uri,
                    username=config.neo4j_username,
                    password=config.neo4j_password,
                    max_connection_pool_size=config.neo4j_max_connection_pool_size,
                )
            )
        except Exception:
            _logger.warning("Neo4j client init failed for %s; graph features degrade", config.neo4j_uri, exc_info=True)
            neo4j_client = None

    a2a_consumer = None
    if config.a2a_enabled and config.event_publisher_backend.lower() == "pulsar":
        a2a_consumer = build_a2a_consumer(
            A2AConsumerConfig(
                service_url=config.pulsar_service_url,
                token=config.pulsar_token,
                tls_enabled=config.pulsar_tls_enabled,
                ca_cert_path=config.pulsar_ca_cert_path,
                topic=config.a2a_topic,
                subscription=config.a2a_subscription,
            )
        )

    return ControlPlaneContext(
        config=config,
        store=store,
        skill_registry=skill_registry,
        policy_engine=policy_engine,
        mcp_gateway=mcp_gateway,
        harness_gate=harness_gate,
        publisher=publisher,
        outbox_relay=outbox_relay,
        domain_capability_service=domain_capability_service,
        connector_runtime=connector_runtime,
        mcp_rate_limiter=mcp_rate_limiter,
        a2a_rate_limiter=a2a_rate_limiter,
        tenant_region_mcp_limiter=tenant_region_mcp_limiter,
        tenant_region_a2a_limiter=tenant_region_a2a_limiter,
        redis_backend=redis_backend,
        distributed_mcp_limiter=distributed_mcp_limiter,
        distributed_a2a_limiter=distributed_a2a_limiter,
        nonce_store=nonce_store,
        cache=cache,
        milvus_client=milvus_client,
        neo4j_client=neo4j_client,
        a2a_consumer=a2a_consumer,
        resolved_db_path=resolved_db_path,
        auth_disabled_warning_emitted=False,
    )
