from __future__ import annotations

from dataclasses import dataclass

import base64
from datetime import datetime, timezone
from typing import Any

from enterprise_ekb.middleware_clients import HttpAdapter, HttpRetryConfig
from enterprise_ekb.schemas import (
    ConnectorDirection,
    ConnectorEnvelope,
    ConnectorHealthRequest,
    ConnectorHealthResult,
    ConnectorProfile,
    ConnectorProfileListRequest,
    ConnectorProfileUpsertRequest,
    ConnectorPullMode,
    ConnectorPullRequest,
    ConnectorPullResult,
    ConnectorCheckpointRequest,
    ConnectorCheckpointResponse,
    ConnectorCheckpointUpdateRequest,
    ConnectorReplayRequest,
    ConnectorReplayResult,
    ConnectorRunStatus,
    ConnectorSystem,
)


@dataclass(frozen=True)
class ConnectorDispatchResult:
    status: ConnectorRunStatus
    reason: str


class BaseConnector:
    system: ConnectorSystem

    def validate(self, envelope: ConnectorEnvelope) -> None:
        if envelope.connector_system != self.system:
            raise ValueError("connector_system_mismatch")

    def dispatch(self, envelope: ConnectorEnvelope) -> ConnectorDispatchResult:
        self.validate(envelope)
        if not envelope.event_type.strip():
            return ConnectorDispatchResult(status=ConnectorRunStatus.ignored, reason="empty_event_type")
        return ConnectorDispatchResult(status=ConnectorRunStatus.accepted, reason="accepted")

    def health_check(self, profile: ConnectorProfile) -> ConnectorHealthResult:
        if profile.status.value != "active":
            return ConnectorHealthResult(
                connector_system=profile.connector_system,
                profile_name=profile.profile_name,
                status="degraded",
                detail="profile_inactive",
            )
        if not profile.base_url.startswith(("http://", "https://")):
            return ConnectorHealthResult(
                connector_system=profile.connector_system,
                profile_name=profile.profile_name,
                status="degraded",
                detail="invalid_base_url",
            )
        if profile.auth_type == "bearer" and not profile.auth_config.get("token"):
            return ConnectorHealthResult(
                connector_system=profile.connector_system,
                profile_name=profile.profile_name,
                status="degraded",
                detail="missing_bearer_token",
            )
        if profile.auth_type == "basic":
            username = profile.auth_config.get("username")
            password = profile.auth_config.get("password")
            if not username or not password:
                return ConnectorHealthResult(
                    connector_system=profile.connector_system,
                    profile_name=profile.profile_name,
                    status="degraded",
                    detail="missing_basic_credentials",
                )
        return ConnectorHealthResult(
            connector_system=profile.connector_system,
            profile_name=profile.profile_name,
            status="ok",
            detail="connector_profile_ready",
        )

    def pull(
        self,
        profile: ConnectorProfile,
        from_cursor: str,
        limit: int,
    ) -> tuple[list[ConnectorEnvelope], str]:
        start = int(from_cursor) if from_cursor.isdigit() else 0
        pull_count = min(limit, profile.pull_batch_size)
        envelopes: list[ConnectorEnvelope] = []
        for i in range(1, pull_count + 1):
            offset = start + i
            envelopes.append(
                ConnectorEnvelope(
                    connector_system=self.system,
                    direction=ConnectorDirection.inbound,
                    tenant_id="group",
                    region_id="cn-north-1",
                    source_id=f"{self.system.value}-{profile.profile_name}",
                    event_type=f"{self.system.value}.entity.changed",
                    occurred_at="2026-03-30T00:00:00Z",
                    idempotency_key=f"{self.system.value}:{profile.profile_name}:{offset}",
                    payload={
                        "profile": profile.profile_name,
                        "cursor": str(offset),
                        "system": self.system.value,
                    },
                    metadata={"mode": "pull", "base_url": profile.base_url},
                )
            )
        next_cursor = str(start + pull_count)
        return envelopes, next_cursor


class ERPConnector(BaseConnector):
    system = ConnectorSystem.erp

    def pull(
        self,
        profile: ConnectorProfile,
        from_cursor: str,
        limit: int,
    ) -> tuple[list[ConnectorEnvelope], str]:
        adapter = HttpAdapter(timeout_ms=profile.timeout_ms, retry=HttpRetryConfig())
        headers = _build_auth_headers(profile)
        endpoint = profile.metadata.get("endpoint", "odata")
        page_size = min(limit, profile.pull_batch_size)
        url = f"{profile.base_url.rstrip('/')}/{endpoint}"
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        records: list[dict[str, Any]] = []
        next_cursor = from_cursor or "0"
        delta_cursor = from_cursor if from_cursor and not from_cursor.isdigit() else profile.metadata.get("delta_token")
        delta_field = profile.metadata.get("delta_field", "LastChangeDateTime")

        try:
            if delta_cursor:
                params = {"$deltatoken": delta_cursor, "$top": page_size}
                secret = profile.auth_config.get("signature_secret", "")
                if secret:
                    data = adapter.signed_get(url=url, headers=headers, params=params, secret=secret)
                else:
                    data = adapter.get(url=url, headers=headers, params=params)
                pulled = data.get("value", []) if isinstance(data, dict) else []
                if isinstance(pulled, list):
                    records.extend([item for item in pulled if isinstance(item, dict)])
                next_delta = data.get("@odata.deltaLink") if isinstance(data, dict) else None
                if isinstance(next_delta, str) and next_delta:
                    next_cursor = next_delta
            else:
                skip = int(from_cursor) if from_cursor.isdigit() else 0
                while len(records) < limit:
                    step = min(page_size, limit - len(records))
                    params = {
                        "$top": step,
                        "$skip": skip,
                        "$orderby": f"{delta_field} asc",
                    }
                    secret = profile.auth_config.get("signature_secret", "")
                    if secret:
                        data = adapter.signed_get(url=url, headers=headers, params=params, secret=secret)
                    else:
                        data = adapter.get(url=url, headers=headers, params=params)
                    pulled = data.get("value", []) if isinstance(data, dict) else []
                    page_records = [item for item in pulled if isinstance(item, dict)] if isinstance(pulled, list) else []
                    if not page_records:
                        break
                    records.extend(page_records)
                    skip += len(page_records)
                    next_cursor = str(skip)
                    if len(page_records) < step:
                        break
        finally:
            adapter.close()

        envelopes = _records_to_envelopes(
            system=self.system,
            profile=profile,
            records=records,
            base_cursor=int(from_cursor) if from_cursor.isdigit() else 0,
            now_iso=now_iso,
            cursor_field=delta_field,
        )
        return envelopes, next_cursor


class MESConnector(BaseConnector):
    system = ConnectorSystem.mes


class SCADAConnector(BaseConnector):
    system = ConnectorSystem.scada


class TicketingConnector(BaseConnector):
    system = ConnectorSystem.ticketing

    def pull(
        self,
        profile: ConnectorProfile,
        from_cursor: str,
        limit: int,
    ) -> tuple[list[ConnectorEnvelope], str]:
        adapter = HttpAdapter(timeout_ms=profile.timeout_ms, retry=HttpRetryConfig())
        headers = _build_auth_headers(profile)
        page_size = min(limit, profile.pull_batch_size)
        offset = int(from_cursor) if from_cursor.isdigit() else 0
        table = profile.metadata.get("table", "incident")
        url = f"{profile.base_url.rstrip('/')}/now/table/{table}"
        cursor_field = profile.metadata.get("delta_field", "sys_updated_on")
        watermark = profile.metadata.get("watermark")
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        records: list[dict[str, Any]] = []
        next_cursor = str(offset)
        try:
            while len(records) < limit:
                step = min(page_size, limit - len(records))
                query = f"{cursor_field}>={watermark}" if isinstance(watermark, str) and watermark else ""
                params = {
                    "sysparm_limit": step,
                    "sysparm_offset": offset,
                    "sysparm_query": query,
                    "sysparm_orderby": cursor_field,
                }
                secret = profile.auth_config.get("signature_secret", "")
                if secret:
                    data = adapter.signed_get(url=url, headers=headers, params=params, secret=secret)
                else:
                    data = adapter.get(url=url, headers=headers, params=params)

                pulled = data.get("result", []) if isinstance(data, dict) else []
                page_records = [item for item in pulled if isinstance(item, dict)] if isinstance(pulled, list) else []
                if not page_records:
                    break
                records.extend(page_records)
                offset += len(page_records)
                next_cursor = str(offset)
                if len(page_records) < step:
                    break
        finally:
            adapter.close()

        envelopes = _records_to_envelopes(
            system=self.system,
            profile=profile,
            records=records,
            base_cursor=int(from_cursor) if from_cursor.isdigit() else 0,
            now_iso=now_iso,
            cursor_field=cursor_field,
        )
        return envelopes, next_cursor


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors = {
            ConnectorSystem.erp: ERPConnector(),
            ConnectorSystem.mes: MESConnector(),
            ConnectorSystem.scada: SCADAConnector(),
            ConnectorSystem.ticketing: TicketingConnector(),
        }

    def dispatch(self, envelope: ConnectorEnvelope) -> ConnectorDispatchResult:
        connector = self._connectors[envelope.connector_system]
        return connector.dispatch(envelope)

    def get(self, connector_system: ConnectorSystem) -> BaseConnector:
        return self._connectors[connector_system]


class ConnectorRuntime:
    def __init__(self, store, registry: ConnectorRegistry | None = None) -> None:
        self._store = store
        self._registry = registry or ConnectorRegistry()

    def ingest(self, envelope: ConnectorEnvelope) -> ConnectorDispatchResult:
        existing_id, inserted = self._store.persist_connector_envelope(
            envelope=envelope,
            status=ConnectorRunStatus.accepted,
        )
        if not inserted:
            self._store.mark_connector_replayed(
                row_id=existing_id,
                status=ConnectorRunStatus.replayed,
            )
            self._store.enqueue_outbox(
                event_type=f"connector.{envelope.connector_system.value}.ingested",
                payload={
                    "connector_system": envelope.connector_system.value,
                    "direction": envelope.direction.value,
                    "tenant_id": envelope.tenant_id,
                    "region_id": envelope.region_id,
                    "source_id": envelope.source_id,
                    "event_type": envelope.event_type,
                    "idempotency_key": envelope.idempotency_key,
                    "status": ConnectorRunStatus.replayed.value,
                    "row_id": existing_id,
                },
            )
            return ConnectorDispatchResult(status=ConnectorRunStatus.replayed, reason="idempotent_replay")

        result = self._registry.dispatch(envelope)
        row_id = existing_id
        self._store.update_connector_status(row_id=row_id, status=result.status)
        self._store.enqueue_outbox(
            event_type=f"connector.{envelope.connector_system.value}.ingested",
            payload={
                "connector_system": envelope.connector_system.value,
                "direction": envelope.direction.value,
                "tenant_id": envelope.tenant_id,
                "region_id": envelope.region_id,
                "source_id": envelope.source_id,
                "event_type": envelope.event_type,
                "idempotency_key": envelope.idempotency_key,
                "status": result.status.value,
                "row_id": row_id,
            },
        )
        return result

    def replay(self, request: ConnectorReplayRequest) -> ConnectorReplayResult:
        rows = self._store.list_connector_envelopes(
            connector_system=request.connector_system,
            limit=request.limit,
        )
        replayed = 0
        accepted = 0
        ignored = 0
        by_system: dict[str, int] = {}

        for row in rows:
            envelope = row["envelope"]
            result = self._registry.dispatch(envelope)
            self._store.mark_connector_replayed(row_id=int(row["id"]), status=result.status)
            replayed += 1
            if result.status == ConnectorRunStatus.accepted:
                accepted += 1
            elif result.status == ConnectorRunStatus.ignored:
                ignored += 1
            by_system[envelope.connector_system.value] = by_system.get(envelope.connector_system.value, 0) + 1

        return ConnectorReplayResult(
            replayed=replayed,
            accepted=accepted,
            ignored=ignored,
            by_system=by_system,
        )

    def upsert_profile(self, request: ConnectorProfileUpsertRequest) -> int:
        profile_id = self._store.upsert_connector_profile(request.profile)
        self._store.enqueue_outbox(
            event_type="connector.profile.upserted",
            payload={
                "connector_system": request.profile.connector_system.value,
                "profile_name": request.profile.profile_name,
                "status": request.profile.status.value,
                "profile_id": profile_id,
            },
        )
        return profile_id

    def list_profiles(self, request: ConnectorProfileListRequest) -> list[ConnectorProfile]:
        return self._store.list_connector_profiles(
            connector_system=request.connector_system,
            limit=request.limit,
        )

    def get_checkpoint(self, request: ConnectorCheckpointRequest) -> ConnectorCheckpointResponse:
        checkpoint = self._store.get_connector_checkpoint(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
        )
        if checkpoint is None:
            return ConnectorCheckpointResponse(
                connector_system=request.connector_system,
                profile_name=request.profile_name,
                cursor="0",
                watermark=None,
                updated_at=None,
            )
        return ConnectorCheckpointResponse(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
            cursor=str(checkpoint["cursor"]),
            watermark=checkpoint.get("watermark"),
            updated_at=checkpoint.get("updated_at"),
        )

    def update_checkpoint(self, request: ConnectorCheckpointUpdateRequest) -> ConnectorCheckpointResponse:
        self._store.upsert_connector_checkpoint(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
            cursor=request.cursor,
            watermark=request.watermark,
        )
        self._store.enqueue_outbox(
            event_type="connector.checkpoint.updated",
            payload={
                "connector_system": request.connector_system.value,
                "profile_name": request.profile_name,
                "cursor": request.cursor,
                "watermark": request.watermark,
            },
        )
        return self.get_checkpoint(
            ConnectorCheckpointRequest(
                connector_system=request.connector_system,
                profile_name=request.profile_name,
            )
        )

    def check_health(self, request: ConnectorHealthRequest) -> ConnectorHealthResult:
        profile = self._store.get_connector_profile(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
        )
        if profile is None:
            return ConnectorHealthResult(
                connector_system=request.connector_system,
                profile_name=request.profile_name,
                status="missing",
                detail="profile_not_found",
            )
        connector = self._registry.get(request.connector_system)
        return connector.health_check(profile)

    def pull(self, request: ConnectorPullRequest) -> ConnectorPullResult:
        profile = self._store.get_connector_profile(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
        )
        if profile is None:
            raise ValueError("connector_profile_not_found")

        connector = self._registry.get(request.connector_system)
        checkpoint = self._store.get_connector_checkpoint(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
        )
        checkpoint_cursor = str(checkpoint["cursor"]) if checkpoint is not None else "0"
        checkpoint_watermark = checkpoint.get("watermark") if checkpoint is not None else None

        if request.from_cursor is not None:
            from_cursor = request.from_cursor
            from_watermark = checkpoint_watermark
        else:
            from_cursor = checkpoint_cursor
            from_watermark = checkpoint_watermark

        pull_profile = profile.model_copy(deep=True)
        if from_watermark and not pull_profile.metadata.get("watermark"):
            pull_profile.metadata["watermark"] = from_watermark

        envelopes, next_cursor = connector.pull(profile=pull_profile, from_cursor=from_cursor, limit=request.limit)
        sample_ids = [env.idempotency_key for env in envelopes[:10]]

        accepted = 0
        replayed = 0
        if request.mode == ConnectorPullMode.commit:
            for envelope in envelopes:
                result = self.ingest(envelope)
                if result.status == ConnectorRunStatus.accepted:
                    accepted += 1
                elif result.status == ConnectorRunStatus.replayed:
                    replayed += 1
            observed_watermark = None
            if envelopes:
                timestamps = [str(env.occurred_at) for env in envelopes if env.occurred_at]
                if timestamps:
                    observed_watermark = max(timestamps)
            self._store.upsert_connector_checkpoint(
                connector_system=request.connector_system,
                profile_name=request.profile_name,
                cursor=next_cursor,
                watermark=observed_watermark or from_watermark,
            )
        else:
            accepted = len(envelopes)

        self._store.append_connector_pull_run(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
            mode=request.mode.value,
            from_cursor=from_cursor,
            next_cursor=next_cursor,
            pulled_count=len(envelopes),
            accepted_count=accepted,
            replayed_count=replayed,
            sample_event_ids=sample_ids,
        )
        self._store.enqueue_outbox(
            event_type="connector.pull.executed",
            payload={
                "connector_system": request.connector_system.value,
                "profile_name": request.profile_name,
                "mode": request.mode.value,
                "pulled": len(envelopes),
                "accepted": accepted,
                "replayed": replayed,
                "from_cursor": from_cursor,
                "next_cursor": next_cursor,
            },
        )

        return ConnectorPullResult(
            connector_system=request.connector_system,
            profile_name=request.profile_name,
            mode=request.mode,
            pulled=len(envelopes),
            accepted=accepted,
            replayed=replayed,
            next_cursor=next_cursor,
            sample_event_ids=sample_ids,
            adapter_type=profile.adapter_type,
        )


def _build_auth_headers(profile: ConnectorProfile) -> dict[str, str]:
    if profile.auth_type == "bearer":
        token = profile.auth_config.get("token", "")
        if token:
            return {"Authorization": f"Bearer {token}"}
    if profile.auth_type == "basic":
        username = profile.auth_config.get("username", "")
        password = profile.auth_config.get("password", "")
        if username and password:
            import base64

            encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
            return {"Authorization": f"Basic {encoded}"}
    api_key = profile.auth_config.get("api_key")
    api_key_header = profile.auth_config.get("api_key_header", "X-API-Key")
    if api_key:
        return {api_key_header: str(api_key)}
    return {}


def _records_to_envelopes(
    system: ConnectorSystem,
    profile: ConnectorProfile,
    records: list[dict[str, Any]],
    base_cursor: int,
    now_iso: str,
    cursor_field: str,
) -> list[ConnectorEnvelope]:
    envelopes: list[ConnectorEnvelope] = []
    for idx, record in enumerate(records, start=1):
        cursor = base_cursor + idx
        record_id = record.get("id") or record.get("sys_id") or f"{cursor}"
        envelopes.append(
            ConnectorEnvelope(
                connector_system=system,
                direction=ConnectorDirection.inbound,
                tenant_id="group",
                region_id="cn-north-1",
                source_id=f"{system.value}-{profile.profile_name}",
                event_type=f"{system.value}.record.changed",
                occurred_at=str(record.get(cursor_field) or now_iso),
                idempotency_key=f"{system.value}:{profile.profile_name}:{record_id}",
                payload={"record": record, "cursor": str(cursor), "delta_field": cursor_field},
                metadata={"profile": profile.profile_name, "adapter_type": profile.adapter_type},
            )
        )
    return envelopes
