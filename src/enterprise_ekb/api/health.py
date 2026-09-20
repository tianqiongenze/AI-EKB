from __future__ import annotations

import hashlib
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
    def readyz(request: Request) -> Response | dict[str, object]:
        publisher_backend = ctx.publisher.__class__.__name__
        event_backend_mismatch = (
            ctx.config.event_publisher_backend.lower() == "pulsar"
            and publisher_backend == "InMemoryPublisher"
        )
        if os.getenv("EKB_ENV", "").lower() == "production" and event_backend_mismatch:
            raise HTTPException(status_code=503, detail="event_backend_mismatch")
        body = {
            "status": "ready",
            "db_driver": ctx.config.db_driver,
            "db_path": ctx.resolved_db_path,
            "event_publisher_backend": publisher_backend,
            "event_backend_mismatch": event_backend_mismatch,
            "outbox_claim_instance": ctx.store.outbox_claim_instance_id(),
            "outbox": ctx.store.outbox_stats(),
        }
        # ETag must be replica-stable: outbox_claim_instance differs per pod and
        # would make If-None-Match flip by load-balancing chance (found by
        # executing the LAN manual test guide against the 2-replica deploy).
        etag_body = {k: v for k, v in body.items() if k != "outbox_claim_instance"}
        etag = hashlib.sha256(repr(etag_body).encode("utf-8")).hexdigest()[:16]
        if request.headers.get("if-none-match") == f'"{etag}"':
            return Response(content=b"", status_code=304)
        return Response(content=body, headers={"ETag": f'"{etag}"'})
    return [healthz, readyz]
