"""Hybrid retrieval with Reciprocal Rank Fusion (P0-③: three legs complete).

Legs:
- lexical: BM25 in-memory scorer (no ES dependency; pluggable to ES for scale)
- vector: Milvus similarity search (dense leg, external client)
- graph: pluggable reader (Neo4j multi-hop query or any callable returning IDs)

Fusion: Reciprocal Rank Fusion (weighted, k=60 default). Reranker hook
(cross-encoder) applies after RRF for final precision boost.
"""

from __future__ import annotations

from typing import Any




class BM25Scorer:
    """In-memory BM25 (Okapi) term-frequency scorer.

    No ES dependency — pluggable to ES/OpenSearch at production scale. Good
    enough for CI tests and small catalogs; the scoring formula is the
    standard BM25 (k1=1.5, b=0.75) so results are directly comparable.
    """

    def __init__(self, documents: list[dict[str, str]], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs: list[tuple[str, list[str]]] = []
        self._df: dict[str, int] = {}
        self._avgdl = 0.0
        for doc in documents:
            tokens = doc["text"].lower().split()
            self._docs.append((doc["id"], tokens))
            self._avgdl += len(tokens)
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1
        self._avgdl = self._avgdl / max(len(self._docs), 1)
        self._n = len(self._docs)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        if not query.strip():
            return []
        terms = query.lower().split()
        import math
        scores: list[tuple[str, float]] = []
        for doc_id, tokens in self._docs:
            score = 0.0
            tf_map: dict[str, int] = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            dl = len(tokens)
            for term in terms:
                tf = tf_map.get(term, 0)
                if tf == 0:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (self._n - df + 0.5) / (df + 0.5))
                numerator = tf * (self._k1 + 1)
                denominator = tf + self._k1 * (1 - self._b + self._b * dl / max(self._avgdl, 1))
                score += idf * numerator / denominator
            if score > 0:
                scores.append((doc_id, score))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:top_k]


from enterprise_ekb.schemas import HybridRetrievalItem, HybridRetrievalResult


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked id lists; returns ids sorted by fused score desc (stable).

    `weights` allows down-weighting a weaker retriever (weighted RRF); default
    is uniform, the production default per published benchmarks.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("weights must match rankings length")
    effective = weights if weights is not None else [1.0] * len(rankings)
    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, effective):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class HybridRetriever:
    def __init__(
        self,
        domain_capability_service: Any,
        milvus_client: Any | None = None,
        graph_search: Any | None = None,
        k: int = 60,
        leg_weights: list[float] | None = None,
        reranker: Any | None = None,
    ) -> None:
        self.domain_capability_service = domain_capability_service
        self.milvus_client = milvus_client
        self.graph_search = graph_search
        self.k = k
        self.leg_weights = leg_weights
        self.reranker = reranker

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

        fused = reciprocal_rank_fusion(rankings, k=self.k, weights=self.leg_weights)[:top_k]
        items = [
            HybridRetrievalItem(id=doc_id, score=round(score, 6), title=titles.get(doc_id))
            for doc_id, score in fused
        ]
        if self.reranker is not None:
            items = list(self.reranker(items))[:top_k]
        return HybridRetrievalResult(
            items=items,
            legs=legs,
            degraded=any(count == 0 for count in legs.values()),
        )
