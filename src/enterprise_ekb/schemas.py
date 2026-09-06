from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillRiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SkillStage(str, Enum):
    draft = "draft"
    review = "review"
    staging = "staging"
    production = "production"
    deprecated = "deprecated"


class BusinessDomain(str, Enum):
    strategy = "strategy"
    rnd = "rnd"
    manufacturing = "manufacturing"
    quality = "quality"
    procurement = "procurement"
    aftersales = "aftersales"
    hr = "hr"
    finance = "finance"
    materials = "materials"
    marketing = "marketing"
    iot = "iot"
    knowledge_graph = "knowledge_graph"


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


class CapabilityMaturity(str, Enum):
    planned = "planned"
    implemented = "implemented"
    validated = "validated"


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


class SkillManifest(BaseModel):
    skill_name: str = Field(min_length=2)
    version: str = Field(min_length=1)
    owner: str = Field(min_length=2)
    risk_level: SkillRiskLevel
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    residency_scope: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    changelog: str = Field(default="")


class BusinessCapabilityManifest(BaseModel):
    domain: BusinessDomain
    capability_type: str = Field(min_length=2)
    title: str = Field(min_length=2)
    description: str = Field(default="")
    owner: str = Field(min_length=2)
    maturity: CapabilityMaturity = CapabilityMaturity.planned
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DomainCapabilitySearchRequest(BaseModel):
    domain: BusinessDomain | None = None
    query: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


class DomainCapabilitySearchResult(BaseModel):
    count: int
    items: list[BusinessCapabilityManifest]


class DomainCoverageItem(BaseModel):
    domain: BusinessDomain
    required_count: int
    implemented_count: int
    planned_count: int
    status: str
    missing_capabilities: list[str]
    implemented_capabilities: list[str]


class DomainCoverageResponse(BaseModel):
    summary: dict[str, int]
    items: list[DomainCoverageItem]


class DomainBootstrapRequest(BaseModel):
    owner: str = Field(default="domain-pmo")


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


class SkillPromotionRequest(BaseModel):
    skill_name: str
    version: str
    target_stage: SkillStage


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


class GraphRelation(BaseModel):
    source: str
    target: str
    relation_type: str


class GraphUpsertRequest(BaseModel):
    rows: list[GraphRelation]


class VectorUpsertRequest(BaseModel):
    collection_name: str
    rows: list[dict[str, Any]]


class VectorSearchRequest(BaseModel):
    collection_name: str
    vectors: list[list[float]]
    limit: int = Field(default=10, ge=1, le=200)


class VectorSearchResult(BaseModel):
    results: Any


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


class DataLakeTableFormat(str, Enum):
    iceberg = "iceberg"


class DataLakeCompactionStrategy(str, Enum):
    size_tiered = "size_tiered"
    bin_pack = "bin_pack"


class DataLakeTableSpec(BaseModel):
    table_name: str = Field(min_length=3, max_length=191)
    table_format: DataLakeTableFormat = DataLakeTableFormat.iceberg
    domain: BusinessDomain
    source_topic: str = Field(min_length=8, max_length=512)
    tenant_id: str = Field(min_length=1, max_length=128)
    region_id: str = Field(min_length=1, max_length=128)
    partition_fields: list[str] = Field(default_factory=list)
    primary_keys: list[str] = Field(default_factory=list)
    retention_days: int = Field(default=30, ge=1, le=3650)
    compaction_strategy: DataLakeCompactionStrategy = DataLakeCompactionStrategy.bin_pack
    table_schema: dict[str, Any] = Field(default_factory=dict)


class DataFlywheelStage(str, Enum):
    ingest = "ingest"
    transform = "transform"
    train = "train"
    serve = "serve"
    feedback = "feedback"


class DataFlywheelEvent(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    region_id: str = Field(min_length=1, max_length=128)
    plant_id: str | None = Field(default=None, max_length=128)
    stage: DataFlywheelStage
    objective: str = Field(min_length=2, max_length=512)
    trace_id: str = Field(min_length=8, max_length=191)
    payload: dict[str, Any] = Field(default_factory=dict)


class FlinkPipelineMode(str, Enum):
    streaming = "streaming"
    batch = "batch"


class FlinkPipelineSpec(BaseModel):
    job_name: str = Field(min_length=3, max_length=191)
    mode: FlinkPipelineMode = FlinkPipelineMode.streaming
    source_topic: str = Field(min_length=8, max_length=512)
    sink_table: str = Field(min_length=3, max_length=191)
    checkpoint_interval_ms: int = Field(default=30000, ge=1000, le=3600000)
    watermark_delay_seconds: int = Field(default=30, ge=0, le=3600)
    parallelism: int = Field(default=4, ge=1, le=256)
    exactly_once: bool = True
    restart_strategy: str = Field(default="failure-rate", min_length=3, max_length=64)
    restart_max_failures_per_interval: int = Field(default=5, ge=1, le=1000)
    restart_failure_rate_interval: str = Field(default="10m", min_length=2, max_length=32)
    restart_delay: str = Field(default="30s", min_length=2, max_length=32)
    checkpoint_timeout_ms: int = Field(default=600000, ge=1000, le=3600000)
    max_concurrent_checkpoints: int = Field(default=1, ge=1, le=32)


class A2ASupervisionScanRequest(BaseModel):
    lookback_limit: int = Field(default=200, ge=10, le=5000)
    dead_event_threshold: int = Field(default=10, ge=1, le=100000)
    failed_task_ratio_threshold: float = Field(default=0.2, ge=0, le=1)


class A2ASupervisionAlert(BaseModel):
    alert_type: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class A2ASupervisionScanResult(BaseModel):
    status: str
    alerts: list[A2ASupervisionAlert] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class DataPipelineSupervisionScanRequest(BaseModel):
    lookback_limit: int = Field(default=200, ge=10, le=5000)
    dead_event_threshold: int = Field(default=10, ge=1, le=100000)
    missing_signal_threshold: int = Field(default=0, ge=0, le=100000)


class DataPipelineSupervisionScanResult(BaseModel):
    status: str
    alerts: list[A2ASupervisionAlert] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class HybridRetrievalItem(BaseModel):
    id: str
    score: float
    title: str | None = None


class HybridRetrievalResult(BaseModel):
    items: list[HybridRetrievalItem]
    legs: dict[str, int]
    degraded: bool


class HybridRetrievalRequest(BaseModel):
    tenant_id: str
    region_id: str
    query: str | None = None
    vector: list[float] | None = None
    collection_name: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)
