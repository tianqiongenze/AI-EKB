"""GraphQL 层测试：schema 编译、5 类查询、limit 钳制、鉴权。

实测模式：REAL（真实 strawberry 0.327.7 federation schema + 真实 SQLite 存储）。
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    from enterprise_ekb.app import create_app

    return TestClient(create_app(db_path=str(tmp_path / "gql.db")))


def _seed_document(client: TestClient) -> str:
    b64 = base64.b64encode("# 工艺\nTTFAR 电池采用石墨烯技术。".encode()).decode("ascii")
    resp = client.post(
        "/documents/ingest",
        json={"source_name": "gql.md", "source_type": "md", "content_b64": b64},
    )
    assert resp.status_code == 200
    return resp.json()["doc_id"]


def test_federation_sdl_exposes_query_and_mutation():
    from enterprise_ekb.api.graphql_schema import federation_schema

    sdl = federation_schema.as_str()
    assert "type Query" in sdl
    assert "type Mutation" in sdl
    for field in ("documents", "document", "chunks", "audits", "rbacRoles", "kpiPanel"):
        assert field in sdl


def test_graphql_documents_query(client):
    doc_id = _seed_document(client)
    resp = client.post(
        "/graphql",
        json={"query": "{ documents(limit: 10) { docId sourceName chunkCount status } }"},
    )
    assert resp.status_code == 200
    docs = resp.json()["data"]["documents"]
    assert len(docs) == 1
    assert docs[0]["docId"] == doc_id
    assert docs[0]["chunkCount"] == 2


def test_graphql_document_and_chunks_query(client):
    doc_id = _seed_document(client)
    resp = client.post(
        "/graphql",
        json={
            "query": f'{{ document(docId: "{doc_id}") {{ sourceType }} chunks(docId: "{doc_id}") {{ seq chunkType }} }}',  # noqa: UP031-family
        },
    )
    data = resp.json()["data"]
    assert data["document"]["sourceType"] == "md"
    types = [c["chunkType"] for c in data["chunks"]]
    assert "parent" in types and "text" in types


def test_graphql_document_not_found_returns_null_not_error(client):
    resp = client.post("/graphql", json={"query": '{ document(docId: "nope") { status } }'})
    assert resp.status_code == 200
    assert resp.json()["data"]["document"] is None


def test_graphql_rbac_roles_twelve(client):
    resp = client.post("/graphql", json={"query": "{ rbacRoles { code layer human } }"})
    roles = resp.json()["data"]["rbacRoles"]
    assert len(roles) == 12
    layers = {r["code"]: r["layer"] for r in roles}
    assert layers["A1"] == "P1" and layers["C3"] == "P4" and layers["D1"] == "P3"


def test_graphql_kpi_panel_and_audits(client):
    resp = client.post(
        "/graphql",
        json={"query": "{ kpiPanel { records oee } audits(limit: 5) { tenantId } }"},
    )
    data = resp.json()["data"]
    assert data["kpiPanel"] is not None
    assert isinstance(data["audits"], list)


def test_graphql_limit_clamped_against_abuse(client):
    _seed_document(client)
    resp = client.post("/graphql", json={"query": "{ documents(limit: 99999) { docId } }"})
    assert resp.status_code == 200
    assert len(resp.json()["data"]["documents"]) <= 100


def test_graphql_invalid_query_returns_errors_field(client):
    resp = client.post("/graphql", json={"query": "{ nosuchfield }"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("errors")


def test_graphql_mutation_clear_cache(client):
    resp = client.post("/graphql", json={"query": "mutation { clearSemanticCache }"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["clearSemanticCache"], int)


def test_graphql_endpoint_appears_in_routes(client):
    paths = [str(getattr(r, "path", "")) for r in client.app.routes]
    assert any("/graphql" in p for p in paths)
