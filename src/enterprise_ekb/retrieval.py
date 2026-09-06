"""Hybrid retrieval with Reciprocal Rank Fusion (review P1 混合检索层).

Legs available today:
- lexical: domain-capability catalog search (SQL LIKE, the sparse leg)
- vector: Milvus similarity search (dense leg, external client)
- graph: pluggable hook (Neo4j client currently write-only; degrades to skip)

Fusion is Reciprocal Rank Fusion (score = sum 1/(k + rank)), the standard
robust default for merging heterogeneous ranked lists without score
calibration. Legs that are unavailable degrade the response instead of
failing it (`degraded=True`, per-leg counts reported).
"""

from __future__ import annotations

from typing import Any

from enterprise_ekb.schemas import HybridRetrievalItem, HybridRetrievalResult


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Fuse ranked id lists; returns ids sorted by fused score desc (stable)."""
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class HybridRetriever:
    def __init__(
        self,
        domain_capability_service: Any,
        milvus_client: Any | None = None,
        graph_search: Any | None = None,
        k: int = 60,
    ) -> None:
        self.domain_capability_service = domain_capability_service
        self.milvus_client = milvus_client
        self.graph_search = graph_search
        self.k = k

    def retrieve(
        self,
        query: str | None,
        vector: list[float] | None,
        collection_name: str | None,
        top_k: int,
    ) -> HybridRetrievalResult:
        legs: dict[str, int] = {"lexical": 0, "vector": 0, "graph": 0}
        rankings: list[list[str]] = []
        titles: dict[str, str] = {}

        if query:
            lexical = self.domain_capability_service.search(query=query, limit=top_k)
            ids: list[str] = []
            for item in lexical.items:
                doc_id = f"capability:{item.capability_type}"
                ids.append(doc_id)
                titles.setdefault(doc_id, item.title)
            rankings.append(ids)
            legs["lexical"] = len(ids)

        if vector and self.milvus_client is not None and collection_name:
            try:
                raw = self.milvus_client.search(collection_name, [vector], top_k)
                ids = []
                for row in raw or []:
                    doc_id = f"vector:{row.get('id') if isinstance(row, dict) else row}"
                    ids.append(doc_id)
                    if isinstance(row, dict) and row.get("title"):
                        titles.setdefault(doc_id, str(row["title"]))
                rankings.append(ids)
                legs["vector"] = len(ids)
            except Exception:
                legs["vector"] = 0

        if self.graph_search is not None:
            try:
                graph_ids = list(self.graph_search(query or "", top_k))[:top_k]
                rankings.append([str(doc_id) for doc_id in graph_ids])
                legs["graph"] = len(graph_ids)
            except Exception:
                legs["graph"] = 0

        fused = reciprocal_rank_fusion(rankings, k=self.k)[:top_k]
        items = [
            HybridRetrievalItem(id=doc_id, score=round(score, 6), title=titles.get(doc_id))
            for doc_id, score in fused
        ]
        return HybridRetrievalResult(
            items=items,
            legs=legs,
            degraded=any(count == 0 for count in legs.values()),
        )
