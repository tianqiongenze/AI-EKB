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
    @post("/mcp/invoke", status_code=200, sync_to_thread=True)
    def mcp_invoke(data: GatewayInvokeRequest, request: Request) -> dict[str, object]:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = ctx.mcp_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = ctx.config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = ctx.tenant_region_mcp_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        if ctx.distributed_mcp_limiter is not None:
            if not ctx.distributed_mcp_limiter.allow(
                f"mcp:{data.tenant_id}:{data.region_id}",
                limit=tenant_region_override or ctx.config.mcp_rate_limit_per_minute,
            ):
                raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        response = ctx._run_with_retry(
            lambda: ctx.mcp_gateway.invoke(data),
            attempts=ctx.config.mcp_invoke_retry_attempts,
            base_delay_ms=ctx.config.mcp_invoke_retry_base_delay_ms,
        )
        ctx.store.append_audit(
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
        ctx.store.enqueue_outbox(
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


    @post("/mcp/stream", status_code=200)
    async def mcp_stream(data: GatewayInvokeRequest, request: Request) -> Response:
        """SSE streaming LLM invocation (first-token + incremental tokens)."""
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        async def stream():
            async for chunk in ctx.mcp_gateway.invoke_stream(data):
                yield chunk
        return Response(content=stream(), media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return [mcp_invoke, mcp_stream]
