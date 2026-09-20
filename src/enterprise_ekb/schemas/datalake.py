"""Data lake bounded context: Iceberg tables, data flywheel, Flink pipelines and pipeline supervision."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from enterprise_ekb.schemas.common import A2ASupervisionAlert, BusinessDomain


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


class DataPipelineSupervisionScanRequest(BaseModel):
    lookback_limit: int = Field(default=200, ge=10, le=5000)
    dead_event_threshold: int = Field(default=10, ge=1, le=100000)
    missing_signal_threshold: int = Field(default=0, ge=0, le=100000)


class DataPipelineSupervisionScanResult(BaseModel):
    status: str
    alerts: list[A2ASupervisionAlert] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
