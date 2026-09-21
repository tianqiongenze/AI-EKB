from __future__ import annotations

import json

from litestar import Request, Response, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.schemas import (
    GatewayInvokeRequest,
)


def routes(ctx: ControlPlaneContext) -> list:
    @post("/mcp/invoke", status_code=200, sync_to_thread=True)
    def mcp_invoke(data: GatewayInvokeRequest, request: Request) -> dict[str, object]:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = ctx.mcp_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
        tenant_region_key = f"{data.tenant_id}:{data.region_id}"
        tenant_region_override = ctx.config.tenant_region_rate_limits.get(tenant_region_key)
        tenant_region_limit = ctx.tenant_region_mcp_limiter.allow(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            override_tokens_per_minute=tenant_region_override,
        )
        if not tenant_region_limit.allowed:
            raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        if ctx.distributed_mcp_limiter is not None:
            if not ctx.distributed_mcp_limiter.allow(
                f"mcp:{data.tenant_id}:{data.region_id}",
                limit=tenant_region_override or ctx.config.mcp_rate_limit_per_minute,
            ):
                raise HTTPException(status_code=429, detail="tenant_region_rate_limited")
        # LCO 三层语义缓存：命中直接返回（cache_hit/cache_layer 元数据透传，OSW 铁律）
        from enterprise_ekb.api.llm_cache import _SEMANTIC_CACHE

        cache_system_key = f"mcp:{data.skill_name}:{data.skill_version}:{data.tool_name}"
        cache_user_key = json.dumps(data.payload, ensure_ascii=False, sort_keys=True, default=str)
        cached = _SEMANTIC_CACHE.get(cache_system_key, cache_user_key)
        if cached is not None:
            answer, layer = cached
            try:
                answer_data = json.loads(answer) if isinstance(answer, str) else answer
            except (TypeError, ValueError):
                answer_data = answer
            return {
                "accepted": True,
                "reason": "semantic_cache_hit",
                "data": answer_data,
                "cache_hit": True,
                "cache_layer": layer,
            }
        response = ctx._run_with_retry(
            lambda: ctx.mcp_gateway.invoke(data),
            attempts=ctx.config.mcp_invoke_retry_attempts,
            base_delay_ms=ctx.config.mcp_invoke_retry_base_delay_ms,
        )
        ctx.store.append_audit(
            tenant_id=data.tenant_id,
            region_id=data.region_id,
            plant_id=data.plant_id,
            user_or_agent_id=data.user_or_agent_id,
            skill_name=data.skill_name,
            skill_version=data.skill_version,
            tool_name=data.tool_name,
            decision_reason=response.decision_reason,
            accepted=response.accepted,
            payload=data.payload,
        )
        ctx.store.enqueue_outbox(
            event_type="mcp.invoked",
            payload={
                "tenant_id": data.tenant_id,
                "region_id": data.region_id,
                "plant_id": data.plant_id,
                "skill": f"{data.skill_name}:{data.skill_version}",
                "tool": data.tool_name,
                "accepted": response.accepted,
                "reason": response.decision_reason,
            },
        )
        if not response.accepted:
            raise HTTPException(status_code=403, detail=response.decision_reason)
        # 未命中→回填缓存（仅接受的成功响应）
        _SEMANTIC_CACHE.put(
            cache_system_key,
            cache_user_key,
            response.data if isinstance(response.data, str) else json.dumps(response.data, ensure_ascii=False, sort_keys=True, default=str),
        )
        return {
            "accepted": response.accepted,
            "reason": response.decision_reason,
            "data": response.data,
            "cache_hit": False,
            "cache_layer": 0,
        }


    @post("/mcp/stream", status_code=200)
    async def mcp_stream(data: GatewayInvokeRequest, request: Request) -> Response:
        """SSE streaming LLM invocation (first-token + incremental tokens)."""
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        async def stream():
            async for chunk in ctx.mcp_gateway.invoke_stream(data):
                yield chunk
        return Response(content=stream(), media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return [mcp_invoke, mcp_stream]
