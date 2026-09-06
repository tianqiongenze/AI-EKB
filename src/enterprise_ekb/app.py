from __future__ import annotations

import logging
import random
import os
import secrets
import time
import uuid

from typing import Any
from typing import cast

from litestar import Litestar, Request, Response, get, post
from litestar.exceptions import HTTPException, ValidationException
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY
import ipaddress
import socket
from urllib.parse import urlparse
import re

from enterprise_ekb.metrics import HTTPMetricsMiddleware, registry as metrics_registry

_logger = logging.getLogger("enterprise_ekb.app")

from enterprise_ekb.capacity import estimate_capacity
from enterprise_ekb.a2a_runtime import A2AConsumerConfig, build_a2a_consumer
from enterprise_ekb.connectors import ConnectorRuntime
from enterprise_ekb.config import load_config
from enterprise_ekb.event_bus import InMemoryPublisher, OutboxRelay, PulsarPublisher
from enterprise_ekb.harness import HarnessGate
from enterprise_ekb.domain_capability import DomainCapabilityService, default_domain_bootstrap
from enterprise_ekb.mcp_gateway import MCPGateway
from enterprise_ekb.policy import PolicyEngine
from enterprise_ekb.rate_limiter import TenantRegionRateLimiter, TokenBucketRateLimiter
from enterprise_ekb.schemas import (
    A2APriority,
    A2ASupervisionScanRequest,
    A2ASupervisionScanResult,
    A2ASupervisionAlert,
    A2AEnvelope,
    AuditQuery,
    BusinessCapabilityManifest,
    CapacityEstimateRequest,
    CapacityEstimateResult,
    ConnectorEnvelope,
    ConnectorHealthRequest,
    ConnectorHealthResult,
    ConnectorProfile,
    ConnectorProfileListRequest,
    ConnectorProfileUpsertRequest,
    ConnectorPullRequest,
    ConnectorPullResult,
    ConnectorCheckpointRequest,
    ConnectorCheckpointResponse,
    ConnectorCheckpointUpdateRequest,
    ConnectorReplayRequest,
    ConnectorReplayResult,
    DomainBootstrapRequest,
    DomainCapabilitySearchRequest,
    DomainCapabilitySearchResult,
    DomainCoverageResponse,
    DataFlywheelEvent,
    DataPipelineSupervisionScanRequest,
    DataPipelineSupervisionScanResult,
    DataLakeTableSpec,
    FlinkPipelineSpec,
    GatewayInvokeRequest,
    GraphUpsertRequest,
    HarnessEvaluationRequest,
    HarnessEvaluationResult,
    RelayRequest,
    SkillManifest,
    SkillPromotionRequest,
    VectorSearchRequest,
    VectorSearchResult,
    SubAgentTaskRecord,
    SubAgentTaskRequest,
    SubAgentTaskResult,
    SubAgentTaskStatus,
    VectorUpsertRequest,
)
from enterprise_ekb.skill_registry import SkillRegistry
from enterprise_ekb.storage import SQLiteControlPlaneStore
from enterprise_ekb.tidb_store import TiDBControlPlaneStore
from enterprise_ekb.middleware_clients import (
    HighPerformanceMilvusClient,
    HighPerformanceNeo4jClient,
    MilvusConfig,
    Neo4jConfig,
)


def _dump_alert(alert: A2ASupervisionAlert) -> dict[str, Any]:
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


def create_app(db_path: str | None = None) -> Litestar:
    config = load_config()
    resolved_db_path = db_path or config.db_path
    external_clients_enabled = os.getenv("EKB_ENABLE_EXTERNAL_CLIENTS", "false").lower() == "true"

    if config.db_driver.lower() == "tidb":
        store = TiDBControlPlaneStore(
            host=config.tidb_host,
            port=config.tidb_port,
            user=config.tidb_user,
            password=config.tidb_password,
            database=config.tidb_database,
        )
    else:
        store = SQLiteControlPlaneStore(db_path=resolved_db_path)
    skill_registry = SkillRegistry(store=store)
    policy_engine = PolicyEngine(skill_registry=skill_registry)
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
    domain_capability_service = DomainCapabilityService(store=store)
    connector_runtime = ConnectorRuntime(store=store)
    mcp_rate_limiter = TokenBucketRateLimiter(config.mcp_rate_limit_per_minute)
    a2a_rate_limiter = TokenBucketRateLimiter(config.a2a_rate_limit_per_minute)
    tenant_region_mcp_limiter = TenantRegionRateLimiter(config.mcp_rate_limit_per_minute)
    tenant_region_a2a_limiter = TenantRegionRateLimiter(config.a2a_rate_limit_per_minute)

    def _bearer_matches(request: Request) -> bool:
        auth_header = request.headers.get("authorization", "")
        return secrets.compare_digest(auth_header, f"Bearer {config.auth_token}")

    auth_disabled_warning_emitted = False

    def _require_admin_auth(request: Request) -> str:
        nonlocal auth_disabled_warning_emitted
        if not config.auth_token:
            if os.getenv("EKB_ENV", "").lower() == "production":
                raise HTTPException(status_code=503, detail="auth_not_configured")
            if not auth_disabled_warning_emitted:
                _logger.warning(
                    "EKB_AUTH_TOKEN is empty; admin endpoints are running without authentication"
                    " (set EKB_ENV=production to fail closed)"
                )
                auth_disabled_warning_emitted = True
            return ""
        auth_header = request.headers.get("authorization", "")
        if not secrets.compare_digest(auth_header, f"Bearer {config.auth_token}"):
            raise HTTPException(status_code=401, detail="unauthorized")
        return auth_header

    def _validate_datalake_topic(topic: str) -> None:
        allowed = any(topic.startswith(prefix) for prefix in config.datalake_allowed_topic_prefixes)
        if not allowed:
            raise HTTPException(status_code=400, detail="source_topic_not_allowed")

    def _validate_table_name(table_name: str) -> None:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{2,190}", table_name):
            raise HTTPException(status_code=400, detail="invalid_table_name")
        allowed = any(table_name.startswith(prefix) for prefix in config.datalake_allowed_table_prefixes)
        if not allowed:
            raise HTTPException(status_code=400, detail="table_name_not_allowed")

    def _validate_job_name(job_name: str) -> None:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_\-]{2,190}", job_name):
            raise HTTPException(status_code=400, detail="invalid_job_name")

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

    @get("/metrics", include_in_schema=False, sync_to_thread=True)
    def prometheus_metrics() -> Response:
        outbox = store.outbox_stats()
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "pending"}, float(outbox.get("pending", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "processing"}, float(outbox.get("processing", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "dead"}, float(outbox.get("dead", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "published"}, float(outbox.get("published", 0)))
        return Response(
            content=metrics_registry.render(),
            media_type="text/plain; version=0.0.4",
        )

    def _audit_connector_auth_failure(request: Request, detail: str) -> None:
        client_host = request.client.host if request.client else "unknown"
        store.append_audit(
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

    def _require_auth(request: Request) -> None:
        if config.connector_auth_enabled and not config.auth_token:
            if os.getenv("EKB_ENV", "").lower() == "production":
                _audit_connector_auth_failure(request, "auth_not_configured")
                raise HTTPException(status_code=503, detail="auth_not_configured")
            return
        if config.connector_auth_enabled and config.auth_token:
            if not _bearer_matches(request):
                _audit_connector_auth_failure(request, "unauthorized")
                raise HTTPException(status_code=401, detail="unauthorized")

    def _is_ip_allowed(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return False
        if not config.connector_allowed_cidrs:
            return False
        for cidr in config.connector_allowed_cidrs:
            try:
                if addr in ipaddress.ip_network(cidr, strict=False):
                    return True
            except ValueError:
                continue
        return False

    def _validate_connector_base_url(base_url: str) -> None:
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
        if not all(_is_ip_allowed(ip) for ip in resolved):
            raise HTTPException(status_code=400, detail="base_url_not_allowed")

    def _model_to_dict(model: Any) -> dict[str, Any]:
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

    @get("/healthz", sync_to_thread=True)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @get("/readyz", sync_to_thread=True)
    def readyz() -> dict[str, object]:
        publisher_backend = publisher.__class__.__name__
        event_backend_mismatch = (
            config.event_publisher_backend.lower() == "pulsar"
            and publisher_backend == "InMemoryPublisher"
        )
        if os.getenv("EKB_ENV", "").lower() == "production" and event_backend_mismatch:
            raise HTTPException(status_code=503, detail="event_backend_mismatch")
        return {
            "status": "ready",
            "db_driver": config.db_driver,
            "db_path": resolved_db_path,
            "event_publisher_backend": publisher_backend,
            "event_backend_mismatch": event_backend_mismatch,
            "outbox_claim_instance": store.outbox_claim_instance_id(),
            "outbox": store.outbox_stats(),
        }

    @post("/skills/register", status_code=200, sync_to_thread=True)
    def register_skill(data: SkillManifest, request: Request) -> dict[str, str]:
        _require_admin_auth(request)
        try:
            stored = skill_registry.register(data)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        store.enqueue_outbox(
            event_type="skill.registered",
            payload={
                "skill_name": stored.manifest.skill_name,
                "version": stored.manifest.version,
                "stage": stored.stage.value,
                "owner": stored.manifest.owner,
            },
        )
        return {
            "skill": stored.manifest.skill_name,
            "version": stored.manifest.version,
            "stage": stored.stage.value,
        }

    @post("/skills/promote", status_code=200, sync_to_thread=True)
    def promote_skill(data: SkillPromotionRequest, request: Request) -> dict[str, str]:
        _require_admin_auth(request)
        try:
            stored = skill_registry.promote(
                skill_name=data.skill_name,
                version=data.version,
                target=data.target_stage,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.enqueue_outbox(
            event_type="skill.promoted",
            payload={
                "skill_name": stored.manifest.skill_name,
                "version": stored.manifest.version,
                "stage": stored.stage.value,
            },
        )
        return {
            "skill": stored.manifest.skill_name,
            "version": stored.manifest.version,
            "stage": stored.stage.value,
        }

    @post("/mcp/invoke", status_code=200, sync_to_thread=True)
    def mcp_invoke(data: GatewayInvokeRequest, request: Request) -> dict[str, object]:
        if config.auth_token and not _bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = mcp_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = tenant_region_mcp_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        response = _run_with_retry(
            lambda: mcp_gateway.invoke(data),
            attempts=config.mcp_invoke_retry_attempts,
            base_delay_ms=config.mcp_invoke_retry_base_delay_ms,
        )
        store.append_audit(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            plant_id=data.plant_id,
            user_or_agent_id=data.user_or_agent_id,
            skill_name=data.skill_name,
            skill_version=data.skill_version,
            tool_name=data.tool_name,
            decision_reason=response.decision_reason,
            accepted=response.accepted,
            payload=data.payload,
        )
        store.enqueue_outbox(
            event_type="mcp.invoked",
            payload={
                "tenant_id": data.tenant_id,
                "region_id": data.region_id,
                "plant_id": data.plant_id,
                "skill": f"{data.skill_name}:{data.skill_version}",
                "tool": data.tool_name,
                "accepted": response.accepted,
                "reason": response.decision_reason,
            },
        )
        if not response.accepted:
            raise HTTPException(status_code=403, detail=response.decision_reason)
        return {
            "accepted": response.accepted,
            "reason": response.decision_reason,
            "data": response.data,
        }

    @post("/harness/evaluate", status_code=200, sync_to_thread=True)
    def evaluate_harness(data: HarnessEvaluationRequest) -> HarnessEvaluationResult:
        result = harness_gate.evaluate(data)
        store.append_harness_run(
            tenant_id=data.tenant_id,
            skill_name=data.skill_name,
            skill_version=data.skill_version,
            quality_score=data.quality_score,
            safety_score=data.safety_score,
            regression_score=data.regression_score,
            latency_ms=data.latency_ms,
            accepted=result.accepted,
            reasons=result.reasons,
        )
        store.enqueue_outbox(
            event_type="harness.evaluated",
            payload={
                "tenant_id": data.tenant_id,
                "skill": f"{data.skill_name}:{data.skill_version}",
                "accepted": result.accepted,
                "reasons": result.reasons,
            },
        )
        return result

    @post("/capacity/estimate", status_code=200, sync_to_thread=True)
    def capacity_estimate(data: CapacityEstimateRequest) -> CapacityEstimateResult:
        result = estimate_capacity(data)
        store.enqueue_outbox(
            event_type="capacity.estimated",
            payload={
                "online_users": data.online_users,
                "active_ratio": data.active_ratio,
                "cache_hit_ratio": data.cache_hit_ratio,
                "complex_ratio": data.complex_ratio,
                "estimated_qps": result.estimated_qps,
                "estimated_heavy_llm_qps": result.estimated_heavy_llm_qps,
                "recommended_a100_80g": result.recommended_a100_80g,
            },
        )
        return result

    @post("/audit/query", status_code=200, sync_to_thread=True)
    def query_audit(data: AuditQuery, request: Request) -> dict[str, object]:
        _require_admin_auth(request)
        items = store.recent_audits(limit=data.limit)
        return {
            "count": len(items),
            "items": items,
        }

    @post("/a2a/supervision/scan", status_code=200, sync_to_thread=True)
    def a2a_supervision_scan(
        data: A2ASupervisionScanRequest,
        request: Request,
    ) -> A2ASupervisionScanResult:
        _require_admin_auth(request)
        outbox_stats = store.outbox_stats()
        dead_events = int(outbox_stats.get("dead", 0))
        recent_outbox = store.recent_outbox_events(limit=data.lookback_limit)
        recent_audits = store.recent_audits(limit=data.lookback_limit)

        supervision_alerts: list[A2ASupervisionAlert] = []

        if dead_events >= data.dead_event_threshold:
            supervision_alerts.append(
                A2ASupervisionAlert(
                    alert_type="outbox_dead_events",
                    severity="critical",
                    message="outbox dead events exceeded threshold",
                    details={
                        "dead_events": dead_events,
                        "threshold": data.dead_event_threshold,
                    },
                )
            )

        sub_task_total = 0
        sub_task_failed = 0
        for event in recent_outbox:
            if event["event_type"] not in {"a2a.message", "a2a.subagent.retry", "a2a.subagent.dlq"}:
                continue
            sub_task_total += 1
            if event["status"] == "dead" or event["event_type"] == "a2a.subagent.dlq":
                sub_task_failed += 1

        failed_ratio = (sub_task_failed / sub_task_total) if sub_task_total > 0 else 0.0
        if sub_task_total > 0 and failed_ratio >= data.failed_task_ratio_threshold:
            supervision_alerts.append(
                A2ASupervisionAlert(
                    alert_type="sub_agent_failure_ratio",
                    severity="high",
                    message="sub-agent failure ratio exceeded threshold",
                    details={
                        "failed": sub_task_failed,
                        "total": sub_task_total,
                        "ratio": round(failed_ratio, 4),
                        "threshold": data.failed_task_ratio_threshold,
                    },
                )
            )

        if not recent_audits:
            supervision_alerts.append(
                A2ASupervisionAlert(
                    alert_type="audit_signal_gap",
                    severity="medium",
                    message="no recent audit records found for supervision window",
                    details={"lookback_limit": data.lookback_limit},
                )
            )

        result_status = "alert" if supervision_alerts else "ok"
        summary = {
            "dead_events": dead_events,
            "recent_outbox_events": len(recent_outbox),
            "recent_audits": len(recent_audits),
            "sub_task_total": sub_task_total,
            "sub_task_failed": sub_task_failed,
            "sub_task_failed_ratio": round(failed_ratio, 4),
            "alert_count": len(supervision_alerts),
        }


        store.enqueue_outbox(
            event_type="a2a.supervision.scan.executed",
            payload={
                "status": result_status,
                "summary": summary,
                "alerts": [_dump_alert(alert) for alert in supervision_alerts],
            },
        )

        if supervision_alerts:
            store.enqueue_outbox(
                event_type="a2a.supervision.alerted",
                payload={
                    "status": result_status,
                    "summary": summary,
                    "alerts": [_dump_alert(alert) for alert in supervision_alerts],
                },
            )

        return A2ASupervisionScanResult(status=result_status, alerts=supervision_alerts, summary=summary)

    @post("/datapipeline/supervision/scan", status_code=200, sync_to_thread=True)
    def datapipeline_supervision_scan(
        data: DataPipelineSupervisionScanRequest,
        request: Request,
    ) -> DataPipelineSupervisionScanResult:
        _require_admin_auth(request)
        recent_outbox = store.recent_outbox_events(limit=data.lookback_limit)

        pipeline_events = {
            "datalake.table.registered",
            "flink.pipeline.registered",
            "flywheel.event.recorded",
        }
        supervision_alerts: list[A2ASupervisionAlert] = []

        relevant = [e for e in recent_outbox if e["event_type"] in pipeline_events]
        dead_count = sum(1 for e in relevant if e["status"] == "dead")

        if dead_count >= data.dead_event_threshold:
            supervision_alerts.append(
                A2ASupervisionAlert(
                    alert_type="pipeline_dead_events",
                    severity="critical",
                    message="pipeline supervision detected dead outbox events",
                    details={"dead_count": dead_count, "threshold": data.dead_event_threshold},
                )
            )

        missing_signals = max(0, data.missing_signal_threshold - len(relevant))
        if missing_signals > 0:
            supervision_alerts.append(
                A2ASupervisionAlert(
                    alert_type="pipeline_signal_gap",
                    severity="high",
                    message="pipeline supervision detected missing signal volume",
                    details={
                        "missing_signals": missing_signals,
                        "recent_relevant_events": len(relevant),
                        "required": data.missing_signal_threshold,
                    },
                )
            )

        result_status = "alert" if supervision_alerts else "ok"
        summary = {
            "recent_relevant_events": len(relevant),
            "dead_count": dead_count,
            "alert_count": len(supervision_alerts),
        }

        def _dump_alert(alert: A2ASupervisionAlert) -> dict[str, Any]:
            dump = getattr(alert, "model_dump", None)
            if callable(dump):
                result = dump(mode="json")
                if isinstance(result, dict):
                    return cast(dict[str, Any], result)
            legacy = alert.dict()
            if isinstance(legacy, dict):
                return cast(dict[str, Any], legacy)
            raise TypeError("pipeline supervision alert serialization failed")

        store.enqueue_outbox(
            event_type="datapipeline.supervision.scan.executed",
            payload={
                "status": result_status,
                "summary": summary,
                "alerts": [_dump_alert(alert) for alert in supervision_alerts],
            },
        )

        if supervision_alerts:
            store.enqueue_outbox(
                event_type="datapipeline.supervision.alerted",
                payload={
                    "status": result_status,
                    "summary": summary,
                    "alerts": [_dump_alert(alert) for alert in supervision_alerts],
                },
            )

        return DataPipelineSupervisionScanResult(
            status=result_status,
            alerts=supervision_alerts,
            summary=summary,
        )

    @post("/events/relay", status_code=200, sync_to_thread=True)
    def relay_events(data: RelayRequest, request: Request) -> dict[str, object]:
        _require_admin_auth(request)
        bounded_batch_size = min(max(1, data.batch_size), max(1, config.events_relay_batch_size_max))
        result = _run_with_retry(
            lambda: outbox_relay.run_once(batch_size=bounded_batch_size),
            attempts=config.events_relay_retry_attempts,
            base_delay_ms=config.events_relay_retry_base_delay_ms,
        )
        return {
            "relay": result,
            "outbox": store.outbox_stats(),
        }

    @post("/datalake/tables/register", status_code=200, sync_to_thread=True)
    def register_datalake_table(data: DataLakeTableSpec, request: Request) -> dict[str, object]:
        _require_admin_auth(request)
        _validate_table_name(data.table_name)
        _validate_datalake_topic(data.source_topic)
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = tenant_region_a2a_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        event_payload = {
            "tenant_id": data.tenant_id,
            "region_id": data.region_id,
            "table_name": data.table_name,
            "table_format": data.table_format.value,
            "domain": data.domain,
            "source_topic": data.source_topic,
            "partition_fields": data.partition_fields,
            "primary_keys": data.primary_keys,
            "retention_days": data.retention_days,
            "compaction_strategy": data.compaction_strategy.value,
            "table_schema": data.table_schema,
        }
        store.enqueue_outbox(event_type="datalake.table.registered", payload=event_payload)
        store.append_audit(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            plant_id="datalake",
            user_or_agent_id="datalake-admin",
            skill_name="datalake",
            skill_version="v1",
            tool_name="register_table",
            decision_reason="accepted",
            accepted=True,
            payload=event_payload,
        )
        return {"status": "registered", "table": data.table_name}

    @post("/flink/pipelines/register", status_code=200, sync_to_thread=True)
    def register_flink_pipeline(data: FlinkPipelineSpec, request: Request) -> dict[str, object]:
        _require_admin_auth(request)
        _validate_job_name(data.job_name)
        _validate_table_name(data.sink_table)
        _validate_datalake_topic(data.source_topic)
        store.enqueue_outbox(
            event_type="flink.pipeline.registered",
            payload={
                "job_name": data.job_name,
                "mode": data.mode.value,
                "source_topic": data.source_topic,
                "sink_table": data.sink_table,
                "checkpoint_interval_ms": data.checkpoint_interval_ms,
                "watermark_delay_seconds": data.watermark_delay_seconds,
                "parallelism": data.parallelism,
                "exactly_once": data.exactly_once,
                "restart_strategy": data.restart_strategy,
                "restart_max_failures_per_interval": data.restart_max_failures_per_interval,
                "restart_failure_rate_interval": data.restart_failure_rate_interval,
                "restart_delay": data.restart_delay,
                "checkpoint_timeout_ms": data.checkpoint_timeout_ms,
                "max_concurrent_checkpoints": data.max_concurrent_checkpoints,
            },
        )
        store.append_audit(
            tenant_id="group",
            region_id="global",
            plant_id="flink",
            user_or_agent_id="flink-admin",
            skill_name="flink",
            skill_version="v1",
            tool_name="register_pipeline",
            decision_reason="accepted",
            accepted=True,
            payload={
                "job_name": data.job_name,
                "mode": data.mode.value,
                "source_topic": data.source_topic,
                "sink_table": data.sink_table,
            },
        )
        return {"status": "registered", "job_name": data.job_name}

    @post("/flywheel/events", status_code=200, sync_to_thread=True)
    def publish_flywheel_event(data: DataFlywheelEvent, request: Request) -> dict[str, object]:
        _require_admin_auth(request)
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = tenant_region_a2a_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        store.enqueue_outbox(
            event_type="flywheel.event.recorded",
            payload={
                "tenant_id": data.tenant_id,
                "region_id": data.region_id,
                "plant_id": data.plant_id,
                "stage": data.stage.value,
                "objective": data.objective,
                "trace_id": data.trace_id,
                "payload": data.payload,
            },
        )
        store.append_audit(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            plant_id=data.plant_id or "unknown",
            user_or_agent_id="flywheel-system",
            skill_name="flywheel",
            skill_version="v1",
            tool_name="record_event",
            decision_reason="accepted",
            accepted=True,
            payload={
                "stage": data.stage.value,
                "objective": data.objective,
                "trace_id": data.trace_id,
            },
        )
        return {"status": "recorded", "trace_id": data.trace_id}

    @post("/a2a/publish", status_code=200, sync_to_thread=True)
    def publish_a2a(data: A2AEnvelope, request: Request) -> dict[str, object]:
        if config.auth_token and not _bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = a2a_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = tenant_region_a2a_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        store.enqueue_outbox(
            event_type="a2a.message",
            payload={
                "event_type": "a2a.message",
                "topic": f"persistent://{data.tenant_id}/a2a/{data.region_id}/{data.target_agent}",
                "message_id": data.message_id,
                "correlation_id": data.correlation_id,
                "tenant_id": data.tenant_id,
                "region_id": data.region_id,
                "plant_id": data.plant_id,
                "agent_id": data.agent_id,
                "target_agent": data.target_agent,
                "intent": data.intent,
                "priority": data.priority.value,
                "idempotency_key": data.idempotency_key,
                "created_at": data.created_at,
                "ttl_seconds": data.ttl_seconds,
                "payload": data.payload,
                "metadata": data.metadata,
            },
        )
        return {"status": "queued", "message_id": data.message_id}


    @post("/a2a/sub-agent/delegate", status_code=200, sync_to_thread=True)
    def delegate_sub_agent(data: SubAgentTaskRequest, request: Request) -> SubAgentTaskResult:
        if config.auth_token and not _bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = a2a_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = tenant_region_a2a_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")

        tenant_id = data.tenant_id
        idempotency_key = data.idempotency_key or data.task_id or uuid.uuid4().hex
        existing = store.get_sub_agent_task_by_idempotency(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return SubAgentTaskResult(
                task_id=existing.task_id,
                sub_agent_type=existing.sub_agent_type,
                status=existing.status,
                result_payload=existing.result_payload,
                error=existing.error,
                worker_id=existing.worker_id,
            )

        task_id = data.task_id or f"subtask_{uuid.uuid4().hex[:16]}"
        correlation_id = data.correlation_id or task_id

        store.create_sub_agent_task(
            task_id=task_id,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            region_id=data.region_id,
            plant_id=data.plant_id,
            supervisor_id=data.supervisor_id,
            sub_agent_type=data.sub_agent_type,
            task_objective=data.task_objective,
        )

        store.enqueue_outbox(
            event_type="a2a.message",
            payload={
                "event_type": "a2a.message",
                "topic": f"persistent://{tenant_id}/a2a/{data.region_id}/{data.sub_agent_type}",
                "message_id": task_id,
                "correlation_id": correlation_id,
                "tenant_id": tenant_id,
                "region_id": data.region_id,
                "plant_id": data.plant_id,
                "agent_id": data.supervisor_id,
                "target_agent": data.sub_agent_type,
                "intent": "delegate_sub_task",
                "priority": data.priority.value,
                "idempotency_key": idempotency_key,
                "created_at": str(time.time()),
                "ttl_seconds": data.timeout_seconds,
                "payload": {
                    "task_id": task_id,
                    "objective": data.task_objective,
                    "context": data.context_payload,
                },
                "metadata": {
                    "is_sub_agent_task": True,
                    "supervisor_id": data.supervisor_id,
                    "callback_agent": data.callback_agent,
                    **data.metadata,
                },
            },
        )
        return SubAgentTaskResult(
            task_id=task_id,
            sub_agent_type=data.sub_agent_type,
            status=SubAgentTaskStatus.queued,
        )

    @get("/a2a/sub-agent/tasks/{task_id:str}", sync_to_thread=True)
    def get_sub_agent_task(task_id: str, request: Request) -> SubAgentTaskRecord:
        if config.auth_token and not _bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        task = store.get_sub_agent_task(task_id=task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="sub_agent_task_not_found")
        return task

    @get("/a2a/sub-agent/tasks", sync_to_thread=True)
    def list_sub_agent_tasks(
        supervisor_id: str,
        request: Request,
        limit: int = 100,
    ) -> list[SubAgentTaskRecord]:
        if config.auth_token and not _bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        bounded_limit = max(1, min(limit, 500))
        return store.list_sub_agent_tasks_by_supervisor(
            supervisor_id=supervisor_id,
            limit=bounded_limit,
        )

    @post("/a2a/sub-agent/result", status_code=200, sync_to_thread=True)
    def report_sub_agent_result(
        data: SubAgentTaskResult,
        request: Request,
    ) -> SubAgentTaskRecord:
        if config.auth_token and not _bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")

        current = store.get_sub_agent_task(task_id=data.task_id)
        if current is None:
            raise HTTPException(status_code=404, detail="sub_agent_task_not_found")
        if current.status in {
            SubAgentTaskStatus.completed,
            SubAgentTaskStatus.failed,
            SubAgentTaskStatus.cancelled,
        }:
            return current

        if data.status in {SubAgentTaskStatus.running, SubAgentTaskStatus.retrying}:
            store.update_sub_agent_task_status(
                task_id=data.task_id,
                status=data.status,
                worker_id=data.worker_id,
                increment_attempt=(data.status == SubAgentTaskStatus.running),
            )
        else:
            store.update_sub_agent_task_status(
                task_id=data.task_id,
                status=data.status,
                result_payload=data.result_payload,
                error=data.error,
                worker_id=data.worker_id,
                increment_attempt=False,
            )

        updated = store.get_sub_agent_task(task_id=data.task_id)
        if updated is None:
            raise HTTPException(status_code=500, detail="sub_agent_task_update_failed")

        if (
            data.status == SubAgentTaskStatus.failed
            and updated.attempt_count < config.subagent_retry_max_attempts
        ):
            backoff_ms = (config.subagent_retry_base_delay_ms * (2 ** max(0, updated.attempt_count - 1))) + random.randint(
                0,
                max(0, config.subagent_retry_jitter_ms),
            )
            store.update_sub_agent_task_status(
                task_id=data.task_id,
                status=SubAgentTaskStatus.retrying,
                worker_id=data.worker_id,
                increment_attempt=False,
            )
            store.enqueue_outbox(
                event_type="a2a.subagent.retry",
                payload={
                    "event_type": "a2a.message",
                    "topic": f"persistent://{updated.tenant_id}/a2a/{updated.region_id}/{updated.sub_agent_type}",
                    "message_id": f"retry-{updated.task_id}-{updated.attempt_count}",
                    "correlation_id": updated.task_id,
                    "tenant_id": updated.tenant_id,
                    "region_id": updated.region_id,
                    "plant_id": updated.plant_id,
                    "agent_id": updated.supervisor_id,
                    "target_agent": updated.sub_agent_type,
                    "intent": "delegate_sub_task",
                    "priority": A2APriority.high.value,
                    "idempotency_key": f"retry-{updated.task_id}-{updated.attempt_count}",
                    "created_at": str(time.time()),
                    "ttl_seconds": max(1, int(backoff_ms / 1000) + 300),
                    "payload": {
                        "task_id": updated.task_id,
                        "objective": updated.task_objective,
                        "context": updated.result_payload,
                        "retry_after_ms": backoff_ms,
                    },
                    "metadata": {
                        "is_sub_agent_task": True,
                        "supervisor_id": updated.supervisor_id,
                        "retry_attempt": updated.attempt_count,
                    },
                },
            )

        if (
            data.status == SubAgentTaskStatus.failed
            and updated.attempt_count >= config.subagent_retry_max_attempts
        ):
            dlq_topic = config.subagent_dlq_topic_template.format(
                tenant=updated.tenant_id,
                region=updated.region_id,
                sub_agent_type=updated.sub_agent_type,
            )
            store.enqueue_outbox(
                event_type="a2a.subagent.dlq",
                payload={
                    "event_type": "a2a.message",
                    "topic": dlq_topic,
                    "message_id": f"dlq-{updated.task_id}",
                    "correlation_id": updated.task_id,
                    "tenant_id": updated.tenant_id,
                    "region_id": updated.region_id,
                    "plant_id": updated.plant_id,
                    "agent_id": updated.sub_agent_type,
                    "target_agent": "subagent-dlq",
                    "intent": "sub_task_dead_letter",
                    "priority": A2APriority.urgent.value,
                    "idempotency_key": f"dlq-{updated.task_id}",
                    "created_at": str(time.time()),
                    "ttl_seconds": 86400,
                    "payload": {
                        "task_id": updated.task_id,
                        "status": updated.status.value,
                        "attempt_count": updated.attempt_count,
                        "error": updated.error,
                        "data": updated.result_payload,
                    },
                    "metadata": {
                        "is_sub_agent_dlq": True,
                        "supervisor_id": updated.supervisor_id,
                    },
                },
            )

        store.enqueue_outbox(
            event_type="a2a.message",
            payload={
                "event_type": "a2a.message",
                "topic": f"persistent://{updated.tenant_id}/a2a/{updated.region_id}/{updated.supervisor_id}",
                "message_id": f"result-{updated.task_id}",
                "correlation_id": updated.task_id,
                "tenant_id": updated.tenant_id,
                "region_id": updated.region_id,
                "plant_id": updated.plant_id,
                "agent_id": updated.sub_agent_type,
                "target_agent": updated.supervisor_id,
                "intent": "sub_task_result",
                "priority": A2APriority.normal.value,
                "idempotency_key": f"result-{updated.task_id}-{updated.status.value}",
                "created_at": str(time.time()),
                "ttl_seconds": 300,
                "payload": {
                    "task_id": updated.task_id,
                    "status": updated.status.value,
                    "data": updated.result_payload,
                    "error": updated.error,
                    "worker_id": updated.worker_id,
                    "attempt_count": updated.attempt_count,
                },
                "metadata": {
                    "is_sub_agent_result": True,
                },
            },
        )

        return updated

    @post("/a2a/consume", status_code=200, sync_to_thread=True)
    def consume_a2a(request: Request) -> dict[str, object]:
        _require_admin_auth(request)
        if a2a_consumer is None:
            raise HTTPException(status_code=400, detail="a2a_consumer_disabled")
        processed = a2a_consumer.run_once()
        return {"processed": processed}

    @post("/graph/upsert", status_code=200, sync_to_thread=True)
    def graph_upsert(data: GraphUpsertRequest, request: Request) -> dict[str, str]:
        _require_admin_auth(request)
        if neo4j_client is None:
            raise HTTPException(status_code=503, detail="neo4j_unavailable")
        neo4j_client.batch_upsert_relations(
            [
                {
                    "source": row.source,
                    "target": row.target,
                    "relation_type": row.relation_type,
                }
                for row in data.rows
            ]
        )
        return {"status": "ok"}

    @post("/vector/upsert", status_code=200, sync_to_thread=True)
    def vector_upsert(data: VectorUpsertRequest, request: Request) -> dict[str, str]:
        _require_admin_auth(request)
        if milvus_client is None:
            raise HTTPException(status_code=503, detail="milvus_unavailable")
        milvus_client.batch_upsert(data.collection_name, data.rows)
        return {"status": "ok"}

    @post("/vector/search", status_code=200, sync_to_thread=True)
    def vector_search(data: VectorSearchRequest) -> VectorSearchResult:
        if milvus_client is None:
            raise HTTPException(status_code=503, detail="milvus_unavailable")
        results = milvus_client.search(data.collection_name, data.vectors, data.limit)
        return VectorSearchResult(results=results)

    @post("/domain/capabilities/upsert", status_code=200, sync_to_thread=True)
    def upsert_domain_capability(data: BusinessCapabilityManifest) -> dict[str, object]:
        capability_id = domain_capability_service.upsert(data)
        store.enqueue_outbox(
            event_type="domain.capability.upserted",
            payload={
                "id": capability_id,
                "domain": data.domain.value,
                "capability_type": data.capability_type,
                "title": data.title,
                "owner": data.owner,
                "maturity": data.maturity.value,
            },
        )
        return {"id": capability_id, "status": "ok"}

    @post("/domain/capabilities/search", status_code=200, sync_to_thread=True)
    def search_domain_capabilities(data: DomainCapabilitySearchRequest) -> DomainCapabilitySearchResult:
        return domain_capability_service.search(
            domain=data.domain,
            query=data.query,
            limit=data.limit,
        )

    @get("/domain/capabilities/coverage", sync_to_thread=True)
    def domain_capabilities_coverage() -> DomainCoverageResponse:
        return domain_capability_service.coverage()

    @post("/domain/capabilities/bootstrap", status_code=200, sync_to_thread=True)
    def bootstrap_domain_capabilities(data: DomainBootstrapRequest) -> dict[str, object]:
        items = default_domain_bootstrap(owner=data.owner)
        inserted = 0
        for item in items:
            domain_capability_service.upsert(item)
            inserted += 1
        store.enqueue_outbox(
            event_type="domain.capabilities.bootstrapped",
            payload={
                "owner": data.owner,
                "inserted": inserted,
            },
        )
        return {"status": "ok", "inserted": inserted}

    @post("/connectors/ingest", status_code=200, sync_to_thread=True)
    def ingest_connector_event(
        data: ConnectorEnvelope,
        request: Request,
    ) -> dict[str, object]:
        _require_auth(request)
        result = connector_runtime.ingest(data)
        return {
            "status": result.status.value,
            "reason": result.reason,
        }

    @post("/connectors/replay", status_code=200, sync_to_thread=True)
    def replay_connector_events(data: ConnectorReplayRequest, request: Request) -> ConnectorReplayResult:
        _require_auth(request)
        return connector_runtime.replay(data)

    @post("/connectors/profiles/upsert", status_code=200, sync_to_thread=True)
    def upsert_connector_profile(
        data: ConnectorProfileUpsertRequest,
        request: Request,
    ) -> dict[str, object]:
        _require_auth(request)
        _validate_connector_base_url(data.profile.base_url)
        profile_id = connector_runtime.upsert_profile(data)
        return {"status": "ok", "profile_id": profile_id}

    @post("/connectors/profiles/list", status_code=200, sync_to_thread=True)
    def list_connector_profiles(
        data: ConnectorProfileListRequest,
        request: Request,
    ) -> dict[str, object]:
        _require_auth(request)
        items = connector_runtime.list_profiles(data)
        return {
            "count": len(items),
            "items": [_model_to_dict(item) for item in items],
        }

    @post("/connectors/checkpoint/get", status_code=200, sync_to_thread=True)
    def get_connector_checkpoint(
        data: ConnectorCheckpointRequest,
        request: Request,
    ) -> ConnectorCheckpointResponse:
        _require_auth(request)
        return connector_runtime.get_checkpoint(data)

    @post("/connectors/checkpoint/update", status_code=200, sync_to_thread=True)
    def update_connector_checkpoint(
        data: ConnectorCheckpointUpdateRequest,
        request: Request,
    ) -> ConnectorCheckpointResponse:
        _require_auth(request)
        return connector_runtime.update_checkpoint(data)

    @post("/connectors/health", status_code=200, sync_to_thread=True)
    def check_connector_health(
        data: ConnectorHealthRequest,
        request: Request,
    ) -> ConnectorHealthResult:
        _require_auth(request)
        return connector_runtime.check_health(data)

    @post("/connectors/pull", status_code=200, sync_to_thread=True)
    def pull_connector(
        data: ConnectorPullRequest,
        request: Request,
    ) -> ConnectorPullResult:
        _require_auth(request)
        try:
            return connector_runtime.pull(data)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


    def _validation_exception_to_422(data: Request, exc: ValidationException) -> Response:
        return Response(content={"detail": exc.detail}, status_code=HTTP_422_UNPROCESSABLE_ENTITY)

    api = Litestar(
        route_handlers=[
            prometheus_metrics,
            healthz,
            readyz,
            register_skill,
            promote_skill,
            mcp_invoke,
            evaluate_harness,
            capacity_estimate,
            query_audit,
            a2a_supervision_scan,
            datapipeline_supervision_scan,
            relay_events,
            register_datalake_table,
            register_flink_pipeline,
            publish_flywheel_event,
            publish_a2a,
            delegate_sub_agent,
            get_sub_agent_task,
            list_sub_agent_tasks,
            report_sub_agent_result,
            consume_a2a,
            graph_upsert,
            vector_upsert,
            vector_search,
            upsert_domain_capability,
            search_domain_capabilities,
            domain_capabilities_coverage,
            bootstrap_domain_capabilities,
            ingest_connector_event,
            replay_connector_events,
            upsert_connector_profile,
            list_connector_profiles,
            get_connector_checkpoint,
            update_connector_checkpoint,
            check_connector_health,
            pull_connector,
        ],
        middleware=[HTTPMetricsMiddleware],
        openapi_config=None,
        exception_handlers={ValidationException: _validation_exception_to_422},
    )
    return api


app = create_app()
