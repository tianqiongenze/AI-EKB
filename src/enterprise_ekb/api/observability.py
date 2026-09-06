from __future__ import annotations

import os
import time
import uuid
from typing import Any, cast

from litestar import Request, Response, get, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.metrics import registry as metrics_registry
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
    @get("/metrics", include_in_schema=False, sync_to_thread=True)
    def prometheus_metrics() -> Response:
        outbox = ctx.store.outbox_stats()
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "pending"}, float(outbox.get("pending", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "processing"}, float(outbox.get("processing", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "dead"}, float(outbox.get("dead", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "published"}, float(outbox.get("published", 0)))
        return Response(
            content=metrics_registry.render(),
            media_type="text/plain; version=0.0.4",
        )
    return [prometheus_metrics]
