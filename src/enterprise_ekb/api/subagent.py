from __future__ import annotations

import random
import time
import uuid

from litestar import Request, get, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.schemas import (
    A2APriority,
    SubAgentTaskRecord,
    SubAgentTaskRequest,
    SubAgentTaskResult,
    SubAgentTaskStatus,
)


def routes(ctx: ControlPlaneContext) -> list:
    @post("/a2a/sub-agent/delegate", status_code=200, sync_to_thread=True)
    def delegate_sub_agent(data: SubAgentTaskRequest, request: Request) -> SubAgentTaskResult:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = ctx.a2a_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
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

        tenant_id = data.tenant_id
        idempotency_key = data.idempotency_key or data.task_id or uuid.uuid4().hex
        existing = ctx.store.get_sub_agent_task_by_idempotency(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return SubAgentTaskResult(
                task_id=existing.task_id,
                sub_agent_type=existing.sub_agent_type,
                status=existing.status,
                result_payload=existing.result_payload,
                error=existing.error,
                worker_id=existing.worker_id,
            )

        task_id = data.task_id or f"subtask_{uuid.uuid4().hex[:16]}"
        correlation_id = data.correlation_id or task_id

        ctx.store.create_sub_agent_task(
            task_id=task_id,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            region_id=data.region_id,
            plant_id=data.plant_id,
            supervisor_id=data.supervisor_id,
            sub_agent_type=data.sub_agent_type,
            task_objective=data.task_objective,
        )

        ctx.store.enqueue_outbox(
            event_type="a2a.message",
            payload={
                "event_type": "a2a.message",
                "topic": f"persistent://{tenant_id}/a2a/{data.region_id}/{data.sub_agent_type}",
                "message_id": task_id,
                "correlation_id": correlation_id,
                "tenant_id": tenant_id,
                "region_id": data.region_id,
                "plant_id": data.plant_id,
                "agent_id": data.supervisor_id,
                "target_agent": data.sub_agent_type,
                "intent": "delegate_sub_task",
                "priority": data.priority.value,
                "idempotency_key": idempotency_key,
                "created_at": str(time.time()),
                "ttl_seconds": data.timeout_seconds,
                "payload": {
                    "task_id": task_id,
                    "objective": data.task_objective,
                    "context": data.context_payload,
                },
                "metadata": {
                    "is_sub_agent_task": True,
                    "supervisor_id": data.supervisor_id,
                    "callback_agent": data.callback_agent,
                    **data.metadata,
                },
            },
        )
        return SubAgentTaskResult(
            task_id=task_id,
            sub_agent_type=data.sub_agent_type,
            status=SubAgentTaskStatus.queued,
        )
    @get("/a2a/sub-agent/tasks/{task_id:str}", sync_to_thread=True)
    def get_sub_agent_task(task_id: str, request: Request) -> SubAgentTaskRecord:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        task = ctx.store.get_sub_agent_task(task_id=task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="sub_agent_task_not_found")
        return task
    @get("/a2a/sub-agent/tasks", sync_to_thread=True)
    def list_sub_agent_tasks(
        supervisor_id: str,
        request: Request,
        limit: int = 100,
    ) -> list[SubAgentTaskRecord]:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        bounded_limit = max(1, min(limit, 500))
        return ctx.store.list_sub_agent_tasks_by_supervisor(
            supervisor_id=supervisor_id,
            limit=bounded_limit,
        )
    @post("/a2a/sub-agent/result", status_code=200, sync_to_thread=True)
    def report_sub_agent_result(
        data: SubAgentTaskResult,
        request: Request,
    ) -> SubAgentTaskRecord:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")

        current = ctx.store.get_sub_agent_task(task_id=data.task_id)
        if current is None:
            raise HTTPException(status_code=404, detail="sub_agent_task_not_found")
        if current.status in {
            SubAgentTaskStatus.completed,
            SubAgentTaskStatus.failed,
            SubAgentTaskStatus.cancelled,
        }:
            return current

        if data.status in {SubAgentTaskStatus.running, SubAgentTaskStatus.retrying}:
            ctx.store.update_sub_agent_task_status(
                task_id=data.task_id,
                status=data.status,
                worker_id=data.worker_id,
                increment_attempt=(data.status == SubAgentTaskStatus.running),
            )
        else:
            ctx.store.update_sub_agent_task_status(
                task_id=data.task_id,
                status=data.status,
                result_payload=data.result_payload,
                error=data.error,
                worker_id=data.worker_id,
                increment_attempt=False,
            )

        updated = ctx.store.get_sub_agent_task(task_id=data.task_id)
        if updated is None:
            raise HTTPException(status_code=500, detail="sub_agent_task_update_failed")

        if (
            data.status == SubAgentTaskStatus.failed
            and updated.attempt_count < ctx.config.subagent_retry_max_attempts
        ):
            backoff_ms = (ctx.config.subagent_retry_base_delay_ms * (2 ** max(0, updated.attempt_count - 1))) + random.randint(
                0,
                max(0, ctx.config.subagent_retry_jitter_ms),
            )
            ctx.store.update_sub_agent_task_status(
                task_id=data.task_id,
                status=SubAgentTaskStatus.retrying,
                worker_id=data.worker_id,
                increment_attempt=False,
            )
            ctx.store.enqueue_outbox(
                event_type="a2a.subagent.retry",
                payload={
                    "event_type": "a2a.message",
                    "topic": f"persistent://{updated.tenant_id}/a2a/{updated.region_id}/{updated.sub_agent_type}",
                    "message_id": f"retry-{updated.task_id}-{updated.attempt_count}",
                    "correlation_id": updated.task_id,
                    "tenant_id": updated.tenant_id,
                    "region_id": updated.region_id,
                    "plant_id": updated.plant_id,
                    "agent_id": updated.supervisor_id,
                    "target_agent": updated.sub_agent_type,
                    "intent": "delegate_sub_task",
                    "priority": A2APriority.high.value,
                    "idempotency_key": f"retry-{updated.task_id}-{updated.attempt_count}",
                    "created_at": str(time.time()),
                    "ttl_seconds": max(1, int(backoff_ms / 1000) + 300),
                    "payload": {
                        "task_id": updated.task_id,
                        "objective": updated.task_objective,
                        "context": updated.result_payload,
                        "retry_after_ms": backoff_ms,
                    },
                    "metadata": {
                        "is_sub_agent_task": True,
                        "supervisor_id": updated.supervisor_id,
                        "retry_attempt": updated.attempt_count,
                    },
                },
            )

        if (
            data.status == SubAgentTaskStatus.failed
            and updated.attempt_count >= ctx.config.subagent_retry_max_attempts
        ):
            dlq_topic = ctx.config.subagent_dlq_topic_template.format(
                tenant=updated.tenant_id,
                region=updated.region_id,
                sub_agent_type=updated.sub_agent_type,
            )
            ctx.store.enqueue_outbox(
                event_type="a2a.subagent.dlq",
                payload={
                    "event_type": "a2a.message",
                    "topic": dlq_topic,
                    "message_id": f"dlq-{updated.task_id}",
                    "correlation_id": updated.task_id,
                    "tenant_id": updated.tenant_id,
                    "region_id": updated.region_id,
                    "plant_id": updated.plant_id,
                    "agent_id": updated.sub_agent_type,
                    "target_agent": "subagent-dlq",
                    "intent": "sub_task_dead_letter",
                    "priority": A2APriority.urgent.value,
                    "idempotency_key": f"dlq-{updated.task_id}",
                    "created_at": str(time.time()),
                    "ttl_seconds": 86400,
                    "payload": {
                        "task_id": updated.task_id,
                        "status": updated.status.value,
                        "attempt_count": updated.attempt_count,
                        "error": updated.error,
                        "data": updated.result_payload,
                    },
                    "metadata": {
                        "is_sub_agent_dlq": True,
                        "supervisor_id": updated.supervisor_id,
                    },
                },
            )

        ctx.store.enqueue_outbox(
            event_type="a2a.message",
            payload={
                "event_type": "a2a.message",
                "topic": f"persistent://{updated.tenant_id}/a2a/{updated.region_id}/{updated.supervisor_id}",
                "message_id": f"result-{updated.task_id}",
                "correlation_id": updated.task_id,
                "tenant_id": updated.tenant_id,
                "region_id": updated.region_id,
                "plant_id": updated.plant_id,
                "agent_id": updated.sub_agent_type,
                "target_agent": updated.supervisor_id,
                "intent": "sub_task_result",
                "priority": A2APriority.normal.value,
                "idempotency_key": f"result-{updated.task_id}-{updated.status.value}",
                "created_at": str(time.time()),
                "ttl_seconds": 300,
                "payload": {
                    "task_id": updated.task_id,
                    "status": updated.status.value,
                    "data": updated.result_payload,
                    "error": updated.error,
                    "worker_id": updated.worker_id,
                    "attempt_count": updated.attempt_count,
                },
                "metadata": {
                    "is_sub_agent_result": True,
                },
            },
        )

        return updated
    return [delegate_sub_agent, get_sub_agent_task, list_sub_agent_tasks, report_sub_agent_result]
