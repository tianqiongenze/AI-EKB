from __future__ import annotations

from litestar import Request, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.schemas import (
    ConnectorCheckpointRequest,
    ConnectorCheckpointResponse,
    ConnectorCheckpointUpdateRequest,
    ConnectorEnvelope,
    ConnectorHealthRequest,
    ConnectorHealthResult,
    ConnectorProfileListRequest,
    ConnectorProfileUpsertRequest,
    ConnectorPullRequest,
    ConnectorPullResult,
    ConnectorReplayRequest,
    ConnectorReplayResult,
)


def routes(ctx: ControlPlaneContext) -> list:
    @post("/connectors/ingest", status_code=200, sync_to_thread=True)
    def ingest_connector_event(
        data: ConnectorEnvelope,
        request: Request,
    ) -> dict[str, object]:
        ctx._require_auth(request)
        result = ctx.connector_runtime.ingest(data)
        return {
            "status": result.status.value,
            "reason": result.reason,
        }
    @post("/connectors/replay", status_code=200, sync_to_thread=True)
    def replay_connector_events(data: ConnectorReplayRequest, request: Request) -> ConnectorReplayResult:
        ctx._require_auth(request)
        return ctx.connector_runtime.replay(data)
    @post("/connectors/profiles/upsert", status_code=200, sync_to_thread=True)
    def upsert_connector_profile(
        data: ConnectorProfileUpsertRequest,
        request: Request,
    ) -> dict[str, object]:
        ctx._require_auth(request)
        ctx._validate_connector_base_url(data.profile.base_url)
        profile_id = ctx.connector_runtime.upsert_profile(data)
        return {"status": "ok", "profile_id": profile_id}
    @post("/connectors/profiles/list", status_code=200, sync_to_thread=True)
    def list_connector_profiles(
        data: ConnectorProfileListRequest,
        request: Request,
    ) -> dict[str, object]:
        ctx._require_auth(request)
        items = ctx.connector_runtime.list_profiles(data)
        return {
            "count": len(items),
            "items": [ctx._model_to_dict(item) for item in items],
        }
    @post("/connectors/checkpoint/get", status_code=200, sync_to_thread=True)
    def get_connector_checkpoint(
        data: ConnectorCheckpointRequest,
        request: Request,
    ) -> ConnectorCheckpointResponse:
        ctx._require_auth(request)
        return ctx.connector_runtime.get_checkpoint(data)
    @post("/connectors/checkpoint/update", status_code=200, sync_to_thread=True)
    def update_connector_checkpoint(
        data: ConnectorCheckpointUpdateRequest,
        request: Request,
    ) -> ConnectorCheckpointResponse:
        ctx._require_auth(request)
        return ctx.connector_runtime.update_checkpoint(data)
    @post("/connectors/health", status_code=200, sync_to_thread=True)
    def check_connector_health(
        data: ConnectorHealthRequest,
        request: Request,
    ) -> ConnectorHealthResult:
        ctx._require_auth(request)
        return ctx.connector_runtime.check_health(data)
    @post("/connectors/pull", status_code=200, sync_to_thread=True)
    def pull_connector(
        data: ConnectorPullRequest,
        request: Request,
    ) -> ConnectorPullResult:
        ctx._require_auth(request)
        try:
            return ctx.connector_runtime.pull(data)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [ingest_connector_event, replay_connector_events, upsert_connector_profile, list_connector_profiles, get_connector_checkpoint, update_connector_checkpoint, check_connector_health, pull_connector]
