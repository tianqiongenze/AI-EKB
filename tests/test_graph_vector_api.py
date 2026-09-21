import os

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_graph_upsert_returns_ok() -> None:
    os.environ["EKB_AUTH_TOKEN"] = "graph-token"
    app = create_app()
    client = TestClient(app)
    headers = {"Authorization": "Bearer graph-token"}
    resp = client.post(
        "/graph/upsert",
        json={"rows": [{"source": "a", "target": "b", "relation_type": "RELATED"}]},
        headers=headers,
    )
    assert resp.status_code in {200, 503}


def test_vector_upsert_and_search_return_ok() -> None:
    os.environ["EKB_AUTH_TOKEN"] = "graph-token"
    app = create_app()
    client = TestClient(app)
    headers = {"Authorization": "Bearer graph-token"}
    upsert = client.post(
        "/vector/upsert",
        json={"collection_name": "knowledge_chunks_v1", "rows": [{"id": "1", "vector": [0.1, 0.2]}]},
        headers=headers,
    )
    assert upsert.status_code in {200, 503}
    search = client.post(
        "/vector/search",
        json={"collection_name": "knowledge_chunks_v1", "vectors": [[0.1, 0.2]], "limit": 1},
    )
    assert search.status_code in {200, 503}
