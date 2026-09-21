from __future__ import annotations

from litestar import Request, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.capacity import estimate_capacity
from enterprise_ekb.schemas import (
    AuditQuery,
    CapacityEstimateRequest,
    CapacityEstimateResult,
    HarnessEvaluationRequest,
    HarnessEvaluationResult,
)


def routes(ctx: ControlPlaneContext) -> list:
    @post("/harness/evaluate", status_code=200, sync_to_thread=True)
    def evaluate_harness(data: HarnessEvaluationRequest) -> HarnessEvaluationResult:
        result = ctx.harness_gate.evaluate(data)
        ctx.store.append_harness_run(
            tenant_id=data.tenant_id,
            skill_name=data.skill_name,
            skill_version=data.skill_version,
            quality_score=data.quality_score,
            safety_score=data.safety_score,
            regression_score=data.regression_score,
            latency_ms=data.latency_ms,
            accepted=result.accepted,
            reasons=result.reasons,
        )
        ctx.store.enqueue_outbox(
            event_type="harness.evaluated",
            payload={
                "tenant_id": data.tenant_id,
                "skill": f"{data.skill_name}:{data.skill_version}",
                "accepted": result.accepted,
                "reasons": result.reasons,
            },
        )
        return result
    @post("/capacity/estimate", status_code=200, sync_to_thread=True)
    def capacity_estimate(data: CapacityEstimateRequest, request: Request) -> CapacityEstimateResult:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        # Pure compute: cache by payload hash (audit event below still emitted every call).
        cache_key = ctx.cache.key("capacity", data.model_dump(mode="json"))
        _hit, cached = ctx.cache.get_or_load(
            cache_key,
            lambda: estimate_capacity(data).model_dump(mode="json"),
            ttl_seconds=3600,
        )
        result = CapacityEstimateResult.model_validate(cached) if isinstance(cached, dict) else cached
        ctx.store.enqueue_outbox(
            event_type="capacity.estimated",
            payload={
                "online_users": data.online_users,
                "active_ratio": data.active_ratio,
                "cache_hit_ratio": data.cache_hit_ratio,
                "complex_ratio": data.complex_ratio,
                "estimated_qps": result.estimated_qps,
                "estimated_heavy_llm_qps": result.estimated_heavy_llm_qps,
                "recommended_a100_80g": result.recommended_a100_80g,
            },
        )
        return result
    @post("/audit/query", status_code=200, sync_to_thread=True)
    def query_audit(data: AuditQuery, request: Request) -> dict[str, object]:
        ctx._require_admin_auth(request)
        # Read-mostly: short TTL without invalidation (append-only audit log).
        cache_key = ctx.cache.key("audit:recent", data.limit)
        _hit, cached = ctx.cache.get_or_load(
            cache_key,
            lambda: ctx.store.recent_audits(limit=data.limit),
            ttl_seconds=30,
        )
        items = cached
        return {
            "count": len(items),
            "items": items,
        }
    return [evaluate_harness, capacity_estimate, query_audit]
