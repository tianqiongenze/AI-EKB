from __future__ import annotations

from litestar import Request, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.schemas import (
    A2ASupervisionAlert,
    DataFlywheelEvent,
    DataLakeTableSpec,
    DataPipelineSupervisionScanRequest,
    DataPipelineSupervisionScanResult,
    FlinkPipelineSpec,
    GraphUpsertRequest,
    RelayRequest,
    VectorSearchRequest,
    VectorSearchResult,
    VectorUpsertRequest,
)


def routes(ctx: ControlPlaneContext) -> list:
    @post("/datalake/tables/register", status_code=200, sync_to_thread=True)
    def register_datalake_table(data: DataLakeTableSpec, request: Request) -> dict[str, object]:
        ctx._require_admin_auth(request)
        ctx._validate_table_name(data.table_name)
        ctx._validate_datalake_topic(data.source_topic)
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = ctx.config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = ctx.tenant_region_a2a_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        if ctx.distributed_a2a_limiter is not None:
            if not ctx.distributed_a2a_limiter.allow(
                f"a2a:{data.tenant_id}:{data.region_id}",
                limit=tenant_region_override or ctx.config.a2a_rate_limit_per_minute,
            ):
                raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        event_payload = {
            "tenant_id": data.tenant_id,
            "region_id": data.region_id,
            "table_name": data.table_name,
            "table_format": data.table_format.value,
            "domain": data.domain,
            "source_topic": data.source_topic,
            "partition_fields": data.partition_fields,
            "primary_keys": data.primary_keys,
            "retention_days": data.retention_days,
            "compaction_strategy": data.compaction_strategy.value,
            "table_schema": data.table_schema,
        }
        ctx.store.enqueue_outbox(event_type="datalake.table.registered", payload=event_payload)
        ctx.store.append_audit(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            plant_id="datalake",
            user_or_agent_id="datalake-admin",
            skill_name="datalake",
            skill_version="v1",
            tool_name="register_table",
            decision_reason="accepted",
            accepted=True,
            payload=event_payload,
        )
        return {"status": "registered", "table": data.table_name}
    @post("/flink/pipelines/register", status_code=200, sync_to_thread=True)
    def register_flink_pipeline(data: FlinkPipelineSpec, request: Request) -> dict[str, object]:
        ctx._require_admin_auth(request)
        ctx._validate_job_name(data.job_name)
        ctx._validate_table_name(data.sink_table)
        ctx._validate_datalake_topic(data.source_topic)
        ctx.store.enqueue_outbox(
            event_type="flink.pipeline.registered",
            payload={
                "job_name": data.job_name,
                "mode": data.mode.value,
                "source_topic": data.source_topic,
                "sink_table": data.sink_table,
                "checkpoint_interval_ms": data.checkpoint_interval_ms,
                "watermark_delay_seconds": data.watermark_delay_seconds,
                "parallelism": data.parallelism,
                "exactly_once": data.exactly_once,
                "restart_strategy": data.restart_strategy,
                "restart_max_failures_per_interval": data.restart_max_failures_per_interval,
                "restart_failure_rate_interval": data.restart_failure_rate_interval,
                "restart_delay": data.restart_delay,
                "checkpoint_timeout_ms": data.checkpoint_timeout_ms,
                "max_concurrent_checkpoints": data.max_concurrent_checkpoints,
            },
        )
        ctx.store.append_audit(
            tenant_id="group",
            region_id="global",
            plant_id="flink",
            user_or_agent_id="flink-admin",
            skill_name="flink",
            skill_version="v1",
            tool_name="register_pipeline",
            decision_reason="accepted",
            accepted=True,
            payload={
                "job_name": data.job_name,
                "mode": data.mode.value,
                "source_topic": data.source_topic,
                "sink_table": data.sink_table,
            },
        )
        return {"status": "registered", "job_name": data.job_name}
    @post("/flywheel/events", status_code=200, sync_to_thread=True)
    def publish_flywheel_event(data: DataFlywheelEvent, request: Request) -> dict[str, object]:
        ctx._require_admin_auth(request)
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = ctx.config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = ctx.tenant_region_a2a_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        if ctx.distributed_a2a_limiter is not None:
            if not ctx.distributed_a2a_limiter.allow(
                f"a2a:{data.tenant_id}:{data.region_id}",
                limit=tenant_region_override or ctx.config.a2a_rate_limit_per_minute,
            ):
                raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        ctx.store.enqueue_outbox(
            event_type="flywheel.event.recorded",
            payload={
                "tenant_id": data.tenant_id,
                "region_id": data.region_id,
                "plant_id": data.plant_id,
                "stage": data.stage.value,
                "objective": data.objective,
                "trace_id": data.trace_id,
                "payload": data.payload,
            },
        )
        ctx.store.append_audit(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            plant_id=data.plant_id or "unknown",
            user_or_agent_id="flywheel-system",
            skill_name="flywheel",
            skill_version="v1",
            tool_name="record_event",
            decision_reason="accepted",
            accepted=True,
            payload={
                "stage": data.stage.value,
                "objective": data.objective,
                "trace_id": data.trace_id,
            },
        )
        return {"status": "recorded", "trace_id": data.trace_id}
    @post("/events/relay", status_code=200, sync_to_thread=True)
    def relay_events(data: RelayRequest, request: Request) -> dict[str, object]:
        ctx._require_admin_auth(request)
        bounded_batch_size = min(max(1, data.batch_size), max(1, ctx.config.events_relay_batch_size_max))
        result = ctx._run_with_retry(
            lambda: ctx.outbox_relay.run_once(batch_size=bounded_batch_size),
            attempts=ctx.config.events_relay_retry_attempts,
            base_delay_ms=ctx.config.events_relay_retry_base_delay_ms,
        )
        return {
            "relay": result,
            "outbox": ctx.store.outbox_stats(),
        }
    @post("/datapipeline/supervision/scan", status_code=200, sync_to_thread=True)
    def datapipeline_supervision_scan(
        data: DataPipelineSupervisionScanRequest,
        request: Request,
    ) -> DataPipelineSupervisionScanResult:
        ctx._require_admin_auth(request)
        recent_outbox = ctx.store.recent_outbox_events(limit=data.lookback_limit)

        pipeline_events = {
            "datalake.table.registered",
            "flink.pipeline.registered",
            "flywheel.event.recorded",
        }
        supervision_alerts: list[A2ASupervisionAlert] = []

        relevant = [e for e in recent_outbox if e["event_type"] in pipeline_events]
        dead_count = sum(1 for e in relevant if e["status"] == "dead")

        if dead_count >= data.dead_event_threshold:
            supervision_alerts.append(
                A2ASupervisionAlert(
                    alert_type="pipeline_dead_events",
                    severity="critical",
                    message="pipeline supervision detected dead outbox events",
                    details={"dead_count": dead_count, "threshold": data.dead_event_threshold},
                )
            )

        missing_signals = max(0, data.missing_signal_threshold - len(relevant))
        if missing_signals > 0:
            supervision_alerts.append(
                A2ASupervisionAlert(
                    alert_type="pipeline_signal_gap",
                    severity="high",
                    message="pipeline supervision detected missing signal volume",
                    details={
                        "missing_signals": missing_signals,
                        "recent_relevant_events": len(relevant),
                        "required": data.missing_signal_threshold,
                    },
                )
            )

        result_status = "alert" if supervision_alerts else "ok"
        summary = {
            "recent_relevant_events": len(relevant),
            "dead_count": dead_count,
            "alert_count": len(supervision_alerts),
        }

        ctx.store.enqueue_outbox(
            event_type="datapipeline.supervision.scan.executed",
            payload={
                "status": result_status,
                "summary": summary,
                "alerts": [ctx._dump_alert(alert) for alert in supervision_alerts],
            },
        )

        if supervision_alerts:
            ctx.store.enqueue_outbox(
                event_type="datapipeline.supervision.alerted",
                payload={
                    "status": result_status,
                    "summary": summary,
                    "alerts": [ctx._dump_alert(alert) for alert in supervision_alerts],
                },
            )

        return DataPipelineSupervisionScanResult(
            status=result_status,
            alerts=supervision_alerts,
            summary=summary,
        )
    @post("/graph/upsert", status_code=200, sync_to_thread=True)
    def graph_upsert(data: GraphUpsertRequest, request: Request) -> dict[str, str]:
        ctx._require_admin_auth(request)
        if ctx.neo4j_client is None:
            raise HTTPException(status_code=503, detail="neo4j_unavailable")
        ctx.neo4j_client.batch_upsert_relations(
            [
                {
                    "source": row.source,
                    "target": row.target,
                    "relation_type": row.relation_type,
                }
                for row in data.rows
            ]
        )
        return {"status": "ok"}
    @post("/vector/upsert", status_code=200, sync_to_thread=True)
    def vector_upsert(data: VectorUpsertRequest, request: Request) -> dict[str, str]:
        ctx._require_admin_auth(request)
        if ctx.milvus_client is None:
            raise HTTPException(status_code=503, detail="milvus_unavailable")
        ctx.milvus_client.batch_upsert(data.collection_name, data.rows)
        ctx.cache.delete_prefix("vector:")
        return {"status": "ok"}
    @post("/vector/search", status_code=200, sync_to_thread=True)
    def vector_search(data: VectorSearchRequest) -> VectorSearchResult:
        if ctx.milvus_client is None:
            raise HTTPException(status_code=503, detail="milvus_unavailable")
        cache_key = ctx.cache.key("vector:search", data.collection_name, data.vectors, data.limit)
        _hit, cached = ctx.cache.get_or_load(cache_key, lambda: ctx.milvus_client.search(data.collection_name, data.vectors, data.limit))
        return VectorSearchResult(results=cached)
    return [register_datalake_table, register_flink_pipeline, publish_flywheel_event, relay_events, datapipeline_supervision_scan, graph_upsert, vector_upsert, vector_search]
