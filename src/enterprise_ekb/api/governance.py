from __future__ import annotations

import os
import time
import uuid
from typing import Any, cast

from litestar import Request, Response, get, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.capacity import estimate_capacity
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
    @post("/harness/evaluate", status_code=200, sync_to_thread=True)
    def evaluate_harness(data: HarnessEvaluationRequest) -> HarnessEvaluationResult:
        result = ctx.harness_gate.evaluate(data)
        ctx.store.append_harness_run(
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
        ctx.store.enqueue_outbox(
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
        ctx.store.enqueue_outbox(
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
        ctx._require_admin_auth(request)
        items = ctx.store.recent_audits(limit=data.limit)
        return {
            "count": len(items),
            "items": items,
        }
    return [evaluate_harness, capacity_estimate, query_audit]
