from __future__ import annotations

import os
import time
import uuid
from typing import Any, cast

from litestar import Request, Response, get, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.schemas import (
    A2APriority,
    A2ASupervisionAlert,
    A2ASupervisionScanRequest,
    A2ASupervisionScanResult,
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
    SubAgentTaskRecord,
    SubAgentTaskRequest,
    SubAgentTaskResult,
    SubAgentTaskStatus,
    VectorSearchRequest,
    VectorSearchResult,
    VectorUpsertRequest,
)



def routes(ctx: ControlPlaneContext) -> list:
    @post("/a2a/supervision/scan", status_code=200, sync_to_thread=True)
    def a2a_supervision_scan(
        data: A2ASupervisionScanRequest,
        request: Request,
    ) -> A2ASupervisionScanResult:
        ctx._require_admin_auth(request)
        outbox_stats = ctx.store.outbox_stats()
        dead_events = int(outbox_stats.get("dead", 0))
        recent_outbox = ctx.store.recent_outbox_events(limit=data.lookback_limit)
        recent_audits = ctx.store.recent_audits(limit=data.lookback_limit)

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


        ctx.store.enqueue_outbox(
            event_type="a2a.supervision.scan.executed",
            payload={
                "status": result_status,
                "summary": summary,
                "alerts": [ctx._dump_alert(alert) for alert in supervision_alerts],
            },
        )

        if supervision_alerts:
            ctx.store.enqueue_outbox(
                event_type="a2a.supervision.alerted",
                payload={
                    "status": result_status,
                    "summary": summary,
                    "alerts": [ctx._dump_alert(alert) for alert in supervision_alerts],
                },
            )

        return A2ASupervisionScanResult(status=result_status, alerts=supervision_alerts, summary=summary)
    @post("/a2a/publish", status_code=200, sync_to_thread=True)
    def publish_a2a(data: A2AEnvelope, request: Request) -> dict[str, object]:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = ctx.a2a_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = ctx.config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = ctx.tenant_region_a2a_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        if ctx.distributed_a2a_limiter is not None:
            if not ctx.distributed_a2a_limiter.allow(
                f"a2a:{data.tenant_id}:{data.region_id}",
                limit=tenant_region_override or ctx.config.a2a_rate_limit_per_minute,
            ):
                raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        ctx.store.enqueue_outbox(
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
    @post("/a2a/consume", status_code=200, sync_to_thread=True)
    def consume_a2a(request: Request) -> dict[str, object]:
        ctx._require_admin_auth(request)
        if ctx.a2a_consumer is None:
            raise HTTPException(status_code=400, detail="a2a_consumer_disabled")
        processed = ctx.a2a_consumer.run_once()
        return {"processed": processed}
    return [a2a_supervision_scan, publish_a2a, consume_a2a]
