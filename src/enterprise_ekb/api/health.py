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
    @get("/healthz", sync_to_thread=True)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}
    @get("/readyz", sync_to_thread=True)
    def readyz() -> dict[str, object]:
        publisher_backend = ctx.publisher.__class__.__name__
        event_backend_mismatch = (
            ctx.config.event_publisher_backend.lower() == "pulsar"
            and publisher_backend == "InMemoryPublisher"
        )
        if os.getenv("EKB_ENV", "").lower() == "production" and event_backend_mismatch:
            raise HTTPException(status_code=503, detail="event_backend_mismatch")
        return {
            "status": "ready",
            "db_driver": ctx.config.db_driver,
            "db_path": ctx.resolved_db_path,
            "event_publisher_backend": publisher_backend,
            "event_backend_mismatch": event_backend_mismatch,
            "outbox_claim_instance": ctx.store.outbox_claim_instance_id(),
            "outbox": ctx.store.outbox_stats(),
        }
    return [healthz, readyz]
