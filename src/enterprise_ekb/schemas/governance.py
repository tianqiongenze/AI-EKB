"""Governance bounded context: gateway invocation, harness evaluation, capacity estimation, audit and relay."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from enterprise_ekb.schemas.common import BusinessDomain


class AuditQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)


class GatewayInvokeRequest(BaseModel):
    tenant_id: str
    region_id: str
    plant_id: str
    domain: BusinessDomain
    user_or_agent_id: str
    skill_name: str
    skill_version: str
    tool_name: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HarnessEvaluationRequest(BaseModel):
    tenant_id: str
    skill_name: str
    skill_version: str
    quality_score: float = Field(ge=0, le=1)
    safety_score: float = Field(ge=0, le=1)
    regression_score: float = Field(ge=0, le=1)
    latency_ms: int = Field(ge=0)


class HarnessEvaluationResult(BaseModel):
    accepted: bool
    reasons: list[str]
    gate_scores: dict[str, float]


class CapacityEstimateRequest(BaseModel):
    online_users: int = Field(gt=0)
    active_ratio: float = Field(gt=0, le=1)
    cache_hit_ratio: float = Field(ge=0, le=1)
    complex_ratio: float = Field(ge=0, le=1)
    region_count: int = Field(default=1, ge=1, le=64)
    cross_region_ratio: float = Field(default=0.0, ge=0, le=1)
    failover_overhead_ratio: float = Field(default=0.15, ge=0, le=1)


class CapacityEstimateResult(BaseModel):
    estimated_qps: int
    estimated_llm_qps: int
    estimated_heavy_llm_qps: int
    recommended_a100_80g: int
    estimated_cross_region_qps: int
    estimated_failover_peak_qps: int
    recommended_gateway_vcpu: int
    recommended_control_plane_vcpu: int


class RelayRequest(BaseModel):
    batch_size: int = Field(default=100, ge=1, le=1000)
