"""A2A agent-to-agent bounded context: envelopes, sub-agent tasks and supervision scans."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from enterprise_ekb.schemas.common import A2ASupervisionAlert


class A2APriority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class SubAgentTaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class A2AEnvelope(BaseModel):
    message_id: str = Field(min_length=8)
    correlation_id: str = Field(min_length=8)
    tenant_id: str
    region_id: str
    plant_id: str | None = None
    agent_id: str
    target_agent: str
    intent: str
    priority: A2APriority = A2APriority.normal
    idempotency_key: str | None = None
    created_at: str
    ttl_seconds: int | None = None
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubAgentTaskRequest(BaseModel):
    tenant_id: str = "system"
    region_id: str = "global"
    plant_id: str | None = None
    supervisor_id: str
    sub_agent_type: str
    task_objective: str
    context_payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    idempotency_key: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    callback_agent: str | None = None
    priority: A2APriority = A2APriority.high
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubAgentTaskResult(BaseModel):
    task_id: str
    sub_agent_type: str
    status: SubAgentTaskStatus
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    worker_id: str | None = None


class SubAgentTaskRecord(BaseModel):
    task_id: str
    idempotency_key: str
    tenant_id: str
    region_id: str
    plant_id: str | None = None
    supervisor_id: str
    sub_agent_type: str
    task_objective: str
    status: SubAgentTaskStatus
    attempt_count: int
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    worker_id: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class A2ASupervisionScanRequest(BaseModel):
    lookback_limit: int = Field(default=200, ge=10, le=5000)
    dead_event_threshold: int = Field(default=10, ge=1, le=100000)
    failed_task_ratio_threshold: float = Field(default=0.2, ge=0, le=1)


class A2ASupervisionScanResult(BaseModel):
    status: str
    alerts: list[A2ASupervisionAlert] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
