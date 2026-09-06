from __future__ import annotations

import os
import time
import uuid
from typing import Any, cast

from litestar import Request, Response, get, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.domain_capability import default_domain_bootstrap
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
    @post("/domain/capabilities/upsert", status_code=200, sync_to_thread=True)
    def upsert_domain_capability(data: BusinessCapabilityManifest) -> dict[str, object]:
        capability_id = ctx.domain_capability_service.upsert(data)
        ctx.store.enqueue_outbox(
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
        return ctx.domain_capability_service.search(
            domain=data.domain,
            query=data.query,
            limit=data.limit,
        )
    @get("/domain/capabilities/coverage", sync_to_thread=True)
    def domain_capabilities_coverage() -> DomainCoverageResponse:
        return ctx.domain_capability_service.coverage()
    @post("/domain/capabilities/bootstrap", status_code=200, sync_to_thread=True)
    def bootstrap_domain_capabilities(data: DomainBootstrapRequest) -> dict[str, object]:
        items = default_domain_bootstrap(owner=data.owner)
        inserted = 0
        for item in items:
            ctx.domain_capability_service.upsert(item)
            inserted += 1
        ctx.store.enqueue_outbox(
            event_type="domain.capabilities.bootstrapped",
            payload={
                "owner": data.owner,
                "inserted": inserted,
            },
        )
        return {"status": "ok", "inserted": inserted}
    return [upsert_domain_capability, search_domain_capabilities, domain_capabilities_coverage, bootstrap_domain_capabilities]
