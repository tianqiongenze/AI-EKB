from __future__ import annotations

from litestar import Request, get, post
from litestar.exceptions import HTTPException

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.retrieval import HybridRetriever
from enterprise_ekb.schemas import HybridRetrievalRequest, HybridRetrievalResult


def routes(ctx: ControlPlaneContext) -> list:
    retriever = HybridRetriever(
        domain_capability_service=ctx.domain_capability_service,
        milvus_client=ctx.milvus_client,
    )

    @post("/retrieval/hybrid", status_code=200, sync_to_thread=True)
    def hybrid_retrieval(data: HybridRetrievalRequest, request: Request) -> HybridRetrievalResult:
        if ctx.config.auth_token and not ctx._bearer_matches(request):
            raise HTTPException(status_code=401, detail="unauthorized")
        if not data.query and not data.vector:
            raise HTTPException(status_code=400, detail="query_or_vector_required")
        return retriever.retrieve(
            query=data.query,
            vector=data.vector,
            collection_name=data.collection_name,
            top_k=data.top_k,
        )

    return [hybrid_retrieval]
