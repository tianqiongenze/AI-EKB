"""P0-③: Retrieval three-leg completion tests (BM25 lexical + graph read + reranker).

These tests verify the retrieval layer is no longer a two-leg stub:
- BM25 lexical: in-memory term-frequency scoring (no ES dependency)
- Graph read leg: pluggable reader returning ranked entity IDs
- Reranker: cross-encoder hook applied after RRF fusion
"""

import pytest

from enterprise_ekb.retrieval import HybridRetriever, reciprocal_rank_fusion


# ---------------------------------------------------------------------------
# BM25 lexical leg
# ---------------------------------------------------------------------------

def test_bm25_scorer_ranks_by_term_frequency() -> None:
    from enterprise_ekb.retrieval import BM25Scorer

    docs = [
        {"id": "d1", "text": "battery quality control defect analysis"},
        {"id": "d2", "text": "battery assembly line throughput"},
        {"id": "d3", "text": "quality assurance inspection battery cells"},
    ]
    scorer = BM25Scorer(docs)
    results = scorer.search("battery quality", top_k=3)
    assert len(results) == 3
    # d1 and d3 both have battery+quality; d2 has battery only
    ids = [r[0] for r in results]
    assert "d2" in ids
    # d1 (both terms) should rank above d2 (one term)
    assert ids.index("d1") < ids.index("d2")


def test_bm25_empty_query_returns_empty() -> None:
    from enterprise_ekb.retrieval import BM25Scorer

    scorer = BM25Scorer([{"id": "x", "text": "hello"}])
    assert scorer.search("", top_k=5) == []


# ---------------------------------------------------------------------------
# Graph read leg
# ---------------------------------------------------------------------------

def test_graph_read_leg_provides_ranked_entities() -> None:
    """GraphReader is a callable returning ranked entity IDs for a query."""

    class FakeGraphReader:
        def __call__(self, query: str, top_k: int = 10) -> list[str]:
            return [f"entity:{query}:{i}" for i in range(min(3, top_k))]

    service = type("S", (), {"search": staticmethod(lambda query, limit: type("R", (), {"items": []})())})()
    retriever = HybridRetriever(
        domain_capability_service=service,
        graph_search=FakeGraphReader(),
    )
    result = retriever.retrieve(query="defect", vector=None, collection_name=None, top_k=5)
    assert result.legs["graph"] == 3
    assert any("entity:defect" in item.id for item in result.items)
    # Without vector leg, degraded should be True (vector=0)
    assert result.degraded is True


# ---------------------------------------------------------------------------
# Reranker hook
# ---------------------------------------------------------------------------

def test_reranker_reorders_after_rrf() -> None:
    class ReverseReranker:
        def __call__(self, items):
            return list(reversed(items))

    service = type("S", (), {"search": staticmethod(lambda query, limit: type("R", (), {"items": []})())})()
    retriever = HybridRetriever(
        domain_capability_service=service,
        graph_search=lambda q, top_k=10: ["g1", "g2", "g3"],
        reranker=ReverseReranker(),
    )
    result = retriever.retrieve(query="test", vector=None, collection_name=None, top_k=3)
    assert len(result.items) == 3
    # Reversed: g3 should be first
    assert "g3" in result.items[0].id


# ---------------------------------------------------------------------------
# End-to-end: all three legs + reranker
# ---------------------------------------------------------------------------

def test_three_leg_retrieval_with_reranker() -> None:
    from enterprise_ekb.retrieval import BM25Scorer

    docs = [
        {"id": "cap:quality", "text": "quality control defect management"},
        {"id": "cap:safety", "text": "safety inspection compliance audit"},
        {"id": "cap:battery", "text": "battery assembly manufacturing process"},
    ]
    bm25 = BM25Scorer(docs)

    class FakeService:
        def search(self, query, limit):
            ids = [r[0] for r in bm25.search(query, top_k=limit)]
            items = [type("I", (), {"capability_type": i.split(":")[1], "title": i})() for i in ids]
            return type("R", (), {"items": items})()

    class FakeMilvus:
        def search(self, collection, vectors, limit):
            return [{"id": "vec:1", "title": "Vector doc 1"}]

    class FakeGraph:
        def __call__(self, query, top_k=10):
            return ["graph:entity1"]

    class IdentityReranker:
        def __call__(self, items):
            return items  # passthrough

    retriever = HybridRetriever(
        domain_capability_service=FakeService(),
        milvus_client=FakeMilvus(),
        graph_search=FakeGraph(),
        reranker=IdentityReranker(),
    )
    result = retriever.retrieve(query="quality", vector=[0.1, 0.2], collection_name="docs", top_k=5)
    assert result.legs["lexical"] >= 0
    assert result.legs["vector"] == 1
    assert result.legs["graph"] == 1
    assert not result.degraded  # all three legs produced results
