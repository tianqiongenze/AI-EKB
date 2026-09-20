"""Enterprise EKB schemas, split by bounded context.

The historical single-module ``enterprise_ekb.schemas`` is replaced by this
package; every public name is re-exported here so that
``from enterprise_ekb.schemas import X`` keeps working unchanged.

Context modules depend only on ``common`` (star-shaped dependency graph,
no cycles):
- common:     cross-context shared enums / base types
- skills:     skill manifest, risk levels, promotion
- governance: gateway invoke, harness evaluation, capacity, audit, relay
- a2a:        A2A envelopes, sub-agent tasks, supervision scans
- connectors: external system connector envelopes / profiles / checkpoints / pull / health
- datalake:   data lake tables, data flywheel, Flink pipelines, pipeline supervision
- domain:     business capability manifests and domain coverage
- retrieval:  hybrid retrieval and graph / vector knowledge-store primitives
"""
from enterprise_ekb.schemas.a2a import (
    A2AEnvelope,
    A2APriority,
    A2ASupervisionScanRequest,
    A2ASupervisionScanResult,
    SubAgentTaskRecord,
    SubAgentTaskRequest,
    SubAgentTaskResult,
    SubAgentTaskStatus,
)
from enterprise_ekb.schemas.common import (
    A2ASupervisionAlert,
    BusinessDomain,
)
from enterprise_ekb.schemas.connectors import (
    ConnectorAdapterType,
    ConnectorAuthType,
    ConnectorCheckpointRequest,
    ConnectorCheckpointResponse,
    ConnectorCheckpointUpdateRequest,
    ConnectorDirection,
    ConnectorEnvelope,
    ConnectorHealthRequest,
    ConnectorHealthResult,
    ConnectorProfile,
    ConnectorProfileListRequest,
    ConnectorProfileStatus,
    ConnectorProfileUpsertRequest,
    ConnectorPullMode,
    ConnectorPullRequest,
    ConnectorPullResult,
    ConnectorReplayRequest,
    ConnectorReplayResult,
    ConnectorRunStatus,
    ConnectorSystem,
)
from enterprise_ekb.schemas.datalake import (
    DataFlywheelEvent,
    DataFlywheelStage,
    DataLakeCompactionStrategy,
    DataLakeTableFormat,
    DataLakeTableSpec,
    DataPipelineSupervisionScanRequest,
    DataPipelineSupervisionScanResult,
    FlinkPipelineMode,
    FlinkPipelineSpec,
)
from enterprise_ekb.schemas.domain import (
    BusinessCapabilityManifest,
    CapabilityMaturity,
    DomainBootstrapRequest,
    DomainCapabilitySearchRequest,
    DomainCapabilitySearchResult,
    DomainCoverageItem,
    DomainCoverageResponse,
)
from enterprise_ekb.schemas.governance import (
    AuditQuery,
    CapacityEstimateRequest,
    CapacityEstimateResult,
    GatewayInvokeRequest,
    HarnessEvaluationRequest,
    HarnessEvaluationResult,
    RelayRequest,
)
from enterprise_ekb.schemas.retrieval import (
    GraphRelation,
    GraphUpsertRequest,
    HybridRetrievalItem,
    HybridRetrievalRequest,
    HybridRetrievalResult,
    VectorSearchRequest,
    VectorSearchResult,
    VectorUpsertRequest,
)
from enterprise_ekb.schemas.skills import (
    SkillManifest,
    SkillPromotionRequest,
    SkillRiskLevel,
    SkillStage,
)

__all__ = [
    "A2AEnvelope",
    "A2APriority",
    "A2ASupervisionAlert",
    "A2ASupervisionScanRequest",
    "A2ASupervisionScanResult",
    "AuditQuery",
    "BusinessCapabilityManifest",
    "BusinessDomain",
    "CapabilityMaturity",
    "CapacityEstimateRequest",
    "CapacityEstimateResult",
    "ConnectorAdapterType",
    "ConnectorAuthType",
    "ConnectorCheckpointRequest",
    "ConnectorCheckpointResponse",
    "ConnectorCheckpointUpdateRequest",
    "ConnectorDirection",
    "ConnectorEnvelope",
    "ConnectorHealthRequest",
    "ConnectorHealthResult",
    "ConnectorProfile",
    "ConnectorProfileListRequest",
    "ConnectorProfileStatus",
    "ConnectorProfileUpsertRequest",
    "ConnectorPullMode",
    "ConnectorPullRequest",
    "ConnectorPullResult",
    "ConnectorReplayRequest",
    "ConnectorReplayResult",
    "ConnectorRunStatus",
    "ConnectorSystem",
    "DataFlywheelEvent",
    "DataFlywheelStage",
    "DataLakeCompactionStrategy",
    "DataLakeTableFormat",
    "DataLakeTableSpec",
    "DataPipelineSupervisionScanRequest",
    "DataPipelineSupervisionScanResult",
    "DomainBootstrapRequest",
    "DomainCapabilitySearchRequest",
    "DomainCapabilitySearchResult",
    "DomainCoverageItem",
    "DomainCoverageResponse",
    "FlinkPipelineMode",
    "FlinkPipelineSpec",
    "GatewayInvokeRequest",
    "GraphRelation",
    "GraphUpsertRequest",
    "HarnessEvaluationRequest",
    "HarnessEvaluationResult",
    "HybridRetrievalItem",
    "HybridRetrievalRequest",
    "HybridRetrievalResult",
    "RelayRequest",
    "SkillManifest",
    "SkillPromotionRequest",
    "SkillRiskLevel",
    "SkillStage",
    "SubAgentTaskRecord",
    "SubAgentTaskRequest",
    "SubAgentTaskResult",
    "SubAgentTaskStatus",
    "VectorSearchRequest",
    "VectorSearchResult",
    "VectorUpsertRequest",
]
