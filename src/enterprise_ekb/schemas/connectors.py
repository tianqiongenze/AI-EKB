"""External system connector bounded context: envelopes, profiles, checkpoints, pull and health."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConnectorSystem(str, Enum):
    erp = "erp"
    mes = "mes"
    scada = "scada"
    ticketing = "ticketing"


class ConnectorDirection(str, Enum):
    inbound = "inbound"
    outbound = "outbound"


class ConnectorAuthType(str, Enum):
    bearer = "bearer"
    basic = "basic"
    apikey = "apikey"


class ConnectorAdapterType(str, Enum):
    generic = "generic"
    sap_odata = "sap_odata"
    servicenow_table = "servicenow_table"


class ConnectorProfileStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ConnectorPullMode(str, Enum):
    dry_run = "dry_run"
    commit = "commit"


class ConnectorRunStatus(str, Enum):
    accepted = "accepted"
    replayed = "replayed"
    ignored = "ignored"


class ConnectorEnvelope(BaseModel):
    connector_system: ConnectorSystem
    direction: ConnectorDirection
    tenant_id: str
    region_id: str
    source_id: str
    event_type: str = Field(min_length=2)
    occurred_at: str
    idempotency_key: str = Field(min_length=6)
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorReplayRequest(BaseModel):
    connector_system: ConnectorSystem | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ConnectorReplayResult(BaseModel):
    replayed: int
    accepted: int
    ignored: int
    by_system: dict[str, int]


class ConnectorProfile(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str = Field(min_length=2)
    base_url: str = Field(min_length=4)
    auth_type: ConnectorAuthType
    auth_config: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=5000, ge=100, le=120000)
    pull_batch_size: int = Field(default=100, ge=1, le=1000)
    status: ConnectorProfileStatus = ConnectorProfileStatus.active
    metadata: dict[str, Any] = Field(default_factory=dict)
    adapter_type: ConnectorAdapterType = ConnectorAdapterType.generic


class ConnectorProfileUpsertRequest(BaseModel):
    profile: ConnectorProfile


class ConnectorProfileListRequest(BaseModel):
    connector_system: ConnectorSystem | None = None
    limit: int = Field(default=100, ge=1, le=500)


class ConnectorCheckpointRequest(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str


class ConnectorCheckpointUpdateRequest(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str
    cursor: str = Field(min_length=1)
    watermark: str | None = None


class ConnectorCheckpointResponse(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str
    cursor: str
    watermark: str | None = None
    updated_at: str | None = None


class ConnectorPullRequest(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str
    mode: ConnectorPullMode = ConnectorPullMode.dry_run
    limit: int = Field(default=50, ge=1, le=1000)
    from_cursor: str | None = None


class ConnectorPullResult(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str
    mode: ConnectorPullMode
    pulled: int
    accepted: int
    replayed: int
    next_cursor: str
    sample_event_ids: list[str]
    adapter_type: ConnectorAdapterType | None = None


class ConnectorHealthRequest(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str


class ConnectorHealthResult(BaseModel):
    connector_system: ConnectorSystem
    profile_name: str
    status: str
    detail: str
