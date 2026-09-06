from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app
from enterprise_ekb.retrieval import HybridRetriever, reciprocal_rank_fusion


def test_rrf_fusion_known_scores() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d"]], k=60)
    scores = dict(fused)
    # b is rank1 in list2 and rank2 in list1 -> higher than a (rank1 list1 only)
    assert scores["b"] > scores["a"]
    assert fused[0][0] == "b"
    assert abs(scores["a"] - (1 / 61)) < 1e-9
    assert abs(scores["b"] - (1 / 62 + 1 / 61)) < 1e-9


def test_rrf_stable_order_for_ties() -> None:
    fused = reciprocal_rank_fusion([["x"], ["y"]], k=60)
    assert [doc_id for doc_id, _ in fused] == ["x", "y"]


def test_hybrid_retriever_merges_vector_and_lexical() -> None:
    class FakeMilvus:
        def search(self, collection, vectors, limit):
            return [{"id": "vec-1", "title": "Vector doc"}, {"id": "vec-2"}]

    service = type(
        "FakeService",
        (),
        {"search": staticmethod(lambda query, limit: type("R", (), {"items": [type("I", (), {"capability_type": "cap_a", "title": "Cap A"})()]})())},
    )()
    retriever = HybridRetriever(domain_capability_service=service, milvus_client=FakeMilvus())
    result = retriever.retrieve(query="battery", vector=[0.1, 0.2], collection_name="ekb_docs", top_k=5)
    assert result.legs == {"lexical": 1, "vector": 2, "graph": 0}
    assert result.degraded is True  # graph leg unavailable
    ids = [item.id for item in result.items]
    assert "capability:cap_a" in ids and "vector:vec-1" in ids
    top = result.items[0]
    assert top.score >= result.items[-1].score


def test_hybrid_endpoint_lexical_only_degrades_gracefully(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "hybrid.db")))
    client.post(
        "/domain/capabilities/bootstrap",
        json={"owner": "domain-pmo"},
    )
    resp = client.post(
        "/retrieval/hybrid",
        json={
            "tenant_id": "group",
            "region_id": "cn-north-1",
            "query": "quality",
            "top_k": 5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["legs"]["lexical"] >= 0
    assert body["degraded"] is True
    assert isinstance(body["items"], list)


def test_hybrid_endpoint_requires_query_or_vector(tmp_path: Path) -> None:
    client = TestClient(create_app(db_path=str(tmp_path / "hybrid2.db")))
    resp = client.post(
        "/retrieval/hybrid",
        json={"tenant_id": "group", "region_id": "cn-north-1"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "query_or_vector_required"
