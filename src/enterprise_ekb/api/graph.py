"""P1-6 routes: knowledge-graph build / search / neighbors / stats.

The graph build enqueues a ``graph.rebuilt`` transactional-outbox event so
downstream consumers (cache invalidation, L3 context enrichment) observe the
rebuild (EER ironrule: no fire-and-forget for state-change events).
"""

from __future__ import annotations

from typing import Any

from litestar import Request, get, post
from pydantic import BaseModel, Field

from enterprise_ekb.knowledge_graph import KnowledgeGraphService


class GraphChunkInput(BaseModel):
    content: str
    chunk_id: str = ""
    source: str = ""


class GraphBuildRequest(BaseModel):
    # 审查 P1-9：chunk 数与单 chunk 长度上限（CPU DoS 面）
    chunks: list[GraphChunkInput] = Field(default_factory=list, max_length=2000)


def routes(ctx: Any) -> list:
    service = KnowledgeGraphService()

    @post("/graph/build", status_code=200, sync_to_thread=True)
    def graph_build(data: GraphBuildRequest, request: Request) -> dict:
        ctx._require_admin_auth(request)
        report = service.build_from_chunks(
            [chunk.model_dump() for chunk in data.chunks]
        )
        ctx.store.enqueue_outbox(
            event_type="graph.rebuilt",
            payload={"nodes": report["nodes"], "edges": report["edges"]},
        )
        return report

    @get("/graph/search", sync_to_thread=True)
    def graph_search(request: Request, keyword: str, top_k: int = 20) -> dict:
        ctx._require_auth(request)
        return {"keyword": keyword, "results": service.search(keyword, top_k=top_k)}

    @get("/graph/neighbors", sync_to_thread=True)
    def graph_neighbors(request: Request, entity: str, hops: int = 1) -> dict:
        ctx._require_auth(request)
        return service.neighbors(entity, hops=hops)

    @get("/graph/stats", sync_to_thread=True)
    def graph_stats(request: Request) -> dict:
        ctx._require_auth(request)
        return service.stats()

    return [graph_build, graph_search, graph_neighbors, graph_stats]
