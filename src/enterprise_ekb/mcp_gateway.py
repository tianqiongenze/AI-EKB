"""LLM gateway with streaming SSE support (P0-①: replace stub with real inference path).

The gateway routes to either a real LLM backend (OpenAI-compatible API, e.g.
vLLM serving 7B/72B) or a deterministic fallback that produces structured
output for environments without GPU. Streaming is exposed via SSE
(Server-Sent Events) for first-token latency measurement.

Key metrics (per source architecture §二 设计原则): first_token_ms, total_ms,
tokens_generated — all emitted in the SSE stream and exported to /metrics.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from enterprise_ekb.metrics import registry as metrics_registry
from enterprise_ekb.policy import PolicyEngine
from enterprise_ekb.schemas import GatewayInvokeRequest


@dataclass(frozen=True)
class GatewayResponse:
    accepted: bool
    decision_reason: str
    data: dict[str, Any]
    trace_id: str = ""
    first_token_ms: float = 0.0
    total_ms: float = 0.0
    tokens_generated: int = 0


# ---------------------------------------------------------------------------
# LLM backend protocol
# ---------------------------------------------------------------------------


class LLMBackend:
    """Pluggable LLM backend. Default: deterministic local generator (no GPU).

    Production: subclass and override `generate_stream` to call vLLM/OpenAI.
    """

    def __init__(self, system_prompt: str = "") -> None:
        self.system_prompt = system_prompt or (
            "你是雅迪集团企业知识库助手。基于知识库内容回答问题，"
            "引用来源，若不确定则说明。保持专业、简洁。"
        )

    async def generate_stream(self, query: str, context: str = "") -> AsyncIterator[str]:
        """Default: non-streaming local fallback that yields structured chunks."""
        parts = _compose_response(query, context)
        for token in parts:
            await asyncio.sleep(0)
            yield token

    async def generate(self, query: str, context: str = "") -> tuple[str, int]:
        """Non-streaming convenience: collect full response."""
        tokens = 0
        chunks: list[str] = []
        async for chunk in self.generate_stream(query, context):
            chunks.append(chunk)
            tokens += 1
        return "".join(chunks), tokens


def _compose_response(query: str, context: str) -> list[str]:
    """Deterministic response composed from query + context (test-friendly)."""
    base = f"关于「{query}」的检索结果：\n\n"
    if context:
        base += f"根据知识库记录：{context[:200]}\n\n"
    base += "建议进一步检索相关工艺文档与设备维护手册。"
    return [base[i:i+3] for i in range(0, len(base), 3)]


class OpenAIBackend(LLMBackend):
    """Connects to an OpenAI-compatible endpoint (vLLM, TGI, OpenAI)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "default",
        system_prompt: str = "",
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(system_prompt)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout_seconds

    async def generate_stream(self, query: str, context: str = "") -> AsyncIterator[str]:
        import httpx

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"上下文：{context}\n\n问题：{query}" if context else query},
        ]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "max_tokens": 1024,
                    "temperature": 0.3,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        chunk = json.loads(line[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content


# ---------------------------------------------------------------------------
# MCP Gateway (upgraded)
# ---------------------------------------------------------------------------


class MCPGateway:
    """Policy-gated LLM invocation gateway with streaming support."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        llm_backend: LLMBackend | None = None,
    ) -> None:
        self.policy_engine = policy_engine
        self.llm = llm_backend or LLMBackend()

    def invoke(self, request: GatewayInvokeRequest) -> GatewayResponse:
        """Synchronous invocation (backward-compatible; non-streaming)."""
        decision = self.policy_engine.evaluate_invoke(request)
        if not decision.allowed:
            return GatewayResponse(
                accepted=False,
                decision_reason=decision.reason,
                data={},
            )

        trace_id = uuid.uuid4().hex[:16]
        query = str(request.payload.get("query", request.tool_name))
        context = str(request.payload.get("context", ""))

        t0 = time.perf_counter()
        result, tokens = asyncio.run(self.llm.generate(query, context))
        total_ms = (time.perf_counter() - t0) * 1000

        metrics_registry.observe(
            "ekb_llm_total_duration_ms",
            {"skill": request.skill_name, "tool": request.tool_name},
            total_ms,
        )
        metrics_registry.inc(
            "ekb_llm_tokens_total",
            {"skill": request.skill_name},
            value=max(tokens, 1),
        )

        return GatewayResponse(
            accepted=True,
            decision_reason=decision.reason,
            data={
                "tenant_id": request.tenant_id,
                "skill": f"{request.skill_name}:{request.skill_version}",
                "tool": request.tool_name,
                "answer": result,
                "trace_id": trace_id,
                "tokens": tokens,
                "first_token_ms": round(total_ms / max(tokens, 1), 2),
                "total_ms": round(total_ms, 2),
            },
            trace_id=trace_id,
            first_token_ms=round(total_ms / max(tokens, 1), 2),
            total_ms=round(total_ms, 2),
            tokens_generated=tokens,
        )

    async def invoke_stream(self, request: GatewayInvokeRequest) -> AsyncIterator[str]:
        """SSE streaming invocation (first-token + incremental tokens)."""
        decision = self.policy_engine.evaluate_invoke(request)
        if not decision.allowed:
            yield _sse_event("error", {"reason": decision.reason})
            return

        trace_id = uuid.uuid4().hex[:16]
        query = str(request.payload.get("query", request.tool_name))
        context = str(request.payload.get("context", ""))

        yield _sse_event("start", {
            "trace_id": trace_id,
            "skill": f"{request.skill_name}:{request.skill_version}",
            "tool": request.tool_name,
        })

        t0 = time.perf_counter()
        first_token_emitted = False
        tokens = 0

        async for chunk in self.llm.generate_stream(query, context):
            if not first_token_emitted:
                ft_ms = (time.perf_counter() - t0) * 1000
                metrics_registry.observe(
                    "ekb_llm_first_token_ms",
                    {"skill": request.skill_name},
                    ft_ms,
                )
                yield _sse_event("first_token", {"ms": round(ft_ms, 2)})
                first_token_emitted = True
            tokens += 1
            yield _sse_event("token", {"content": chunk})

        total_ms = (time.perf_counter() - t0) * 1000
        metrics_registry.observe(
            "ekb_llm_total_duration_ms",
            {"skill": request.skill_name, "tool": request.tool_name},
            total_ms,
        )
        metrics_registry.inc(
            "ekb_llm_tokens_total",
            {"skill": request.skill_name},
            value=max(tokens, 1),
        )
        yield _sse_event("done", {
            "trace_id": trace_id,
            "tokens": tokens,
            "total_ms": round(total_ms, 2),
        })


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
