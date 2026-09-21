"""P1-6 KnowledgeGraphService unit tests (extraction / relations / BFS / stats)."""

from __future__ import annotations

import functools

import pytest

from enterprise_ekb.knowledge_graph import KnowledgeGraphService


def test_chinese_entity_extraction_with_book_title() -> None:
    service = KnowledgeGraphService()
    report = service.build_from_chunks(
        [{"content": "《雅迪电池工艺手册》规定石墨烯电池必须经过老化测试。", "source": "doc-1"}]
    )
    assert report["nodes"] >= 2
    results = {item["entity"] for item in service.search("电池")}
    assert any("石墨烯电池" in name for name in results)


def test_english_entity_extraction() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks(
        [{"content": "Graphene Battery and TTFAR Motor are produced in Plant Two."}]
    )
    for expected in ("Graphene Battery", "TTFAR Motor", "Plant Two"):
        assert [item for item in service.search(expected) if item["entity"] == expected], (
            f"missing English entity {expected}"
        )


def test_entity_types_are_classified() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks(
        [
            {"content": "电池产线负责装配作业。"},
            {"content": "质检部审核不良品。"},
        ]
    )
    # search("") returns [] (defensive); inspect via broad keywords instead.
    all_nodes = service.search("产", top_k=100) + service.search("质", top_k=100)
    types = {item["entity"]: item["type"] for item in all_nodes}
    assert types.get("电池产线") == "设备"
    assert any(t == "质量" for t in types.values())


def test_relation_extraction_verb_pattern() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks([{"content": "电池产线采用TTFAR电机。"}])
    result = service.neighbors("电池产线")
    edges = {(e["source"], e["relation"], e["target"]) for e in result["edges"]}
    assert ("电池产线", "采用", "TTFAR") in edges or ("电池产线", "采用", "TTFAR电机") in edges


def test_multi_hop_neighbors_and_clamp() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks(
        [
            {"content": "车架采用焊接工艺。", "source": "s1"},
            {"content": "焊接工艺属于涂装车间。", "source": "s2"},
        ]
    )
    one_hop = {n["entity"] for n in service.neighbors("车架", hops=1)["nodes"]}
    assert "焊接工艺" in one_hop
    assert "涂装车间" not in one_hop
    two_hop = {n["entity"] for n in service.neighbors("车架", hops=2)["nodes"]}
    assert "涂装车间" in two_hop
    # hops clamped to [1, 3]: 10 behaves like 3, never raises.
    clamped = service.neighbors("车架", hops=10)
    assert clamped["hops"] == 3


def test_edge_weight_accumulates_across_builds() -> None:
    service = KnowledgeGraphService()
    chunk = {"content": "车架采用焊接工艺。"}
    service.build_from_chunks([chunk])
    service.build_from_chunks([chunk])
    edges = service.neighbors("车架")["edges"]
    assert edges, "expected at least one edge"
    assert all(e["weight"] >= 2 for e in edges)


def test_unknown_entity_neighbors_is_empty_not_error() -> None:
    service = KnowledgeGraphService()
    result = service.neighbors("不存在的实体")
    assert result["nodes"] == [] and result["edges"] == []


def test_search_ranking_and_top_k() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks(
        [
            {"content": "电池产线运行中。电池产线维护由质检部跟进。"},  # 电池产线 x2
            {"content": "电池规格说明。"},  # 电池 x1
        ]
    )
    results = service.search("电池", top_k=1)
    assert len(results) == 1
    assert results[0]["entity"] == "电池产线"  # higher mentions ranks first


def test_stats_counts() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks(
        [
            {"content": "车架采用焊接工艺。", "source": "s1"},
            {"content": "焊接工艺属于涂装车间。", "source": "s2"},
        ]
    )
    stats = service.stats()
    assert stats["nodes"] == 3
    assert stats["edges"] == 2
    assert stats["total_mentions"] >= 3
    assert stats["relations"].get("采用") == 1
    assert stats["relations"].get("属于") == 1


def test_defensive_inputs() -> None:
    service = KnowledgeGraphService()
    assert service.build_from_chunks(None) == {"nodes": 0, "edges": 0}
    assert service.build_from_chunks([{}, {"content": ""}, {"content": None}, "junk"]) == {
        "nodes": 0,
        "edges": 0,
    }
    assert service.search(None) == []
    assert service.search("") == []
    assert service.neighbors(None)["nodes"] == []
    service.clear()
    assert service.stats()["nodes"] == 0 and service.stats()["edges"] == 0


def test_clear_resets_graph() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks([{"content": "电池产线采用TTFAR电机。"}])
    assert service.stats()["nodes"] > 0
    service.clear()
    stats = service.stats()
    assert stats["nodes"] == 0 and stats["edges"] == 0


def test_sources_recorded_on_edges() -> None:
    service = KnowledgeGraphService()
    service.build_from_chunks([{"content": "车架采用焊接工艺。", "source": "manual-a"}])
    edge = service.neighbors("车架")["edges"][0]
    assert "manual-a" in edge["sources"]


# -- API-level tests (skipped until the main wiring mounts the routes) --------


@functools.lru_cache(maxsize=1)
def _graph_routes_mounted() -> bool:
    try:
        from enterprise_ekb.app import create_app
    except Exception:
        return False
    try:
        registered = {getattr(r, "path", "") for r in create_app().routes}
    except Exception:
        return False
    return "/graph/stats" in registered


@pytest.mark.skipif(
    not _graph_routes_mounted(),
    reason="/graph routes not wired into app yet (main thread wiring pending)",
)
def test_graph_api_endpoints() -> None:
    import os

    from litestar.testing import TestClient

    from enterprise_ekb.app import create_app

    os.environ.setdefault("EKB_AUTH_TOKEN", "graph-p1-token")
    with TestClient(create_app()) as client:
        headers = {"Authorization": "Bearer graph-p1-token"}
        build = client.post(
            "/graph/build",
            json={"chunks": [{"content": "车架采用焊接工艺。", "chunk_id": "c1", "source": "s1"}]},
            headers=headers,
        )
        assert build.status_code == 200
        assert build.json()["nodes"] >= 2
        stats = client.get("/graph/stats")
        assert stats.status_code == 200 and stats.json()["nodes"] >= 2
        search = client.get("/graph/search", params={"keyword": "车架"})
        assert search.status_code == 200
        assert search.json()["results"]
        neighbors = client.get("/graph/neighbors", params={"entity": "车架", "hops": 1})
        assert neighbors.status_code == 200
        assert neighbors.json()["nodes"]


@pytest.mark.skipif(
    not _graph_routes_mounted(),
    reason="/graph routes not wired into app yet (main thread wiring pending)",
)
def test_graph_build_requires_admin(monkeypatch) -> None:
    from litestar.testing import TestClient

    from enterprise_ekb.app import create_app

    monkeypatch.setenv("EKB_AUTH_TOKEN", "graph-token")
    with TestClient(create_app()) as client:
        resp = client.post("/graph/build", json={"chunks": []})
        assert resp.status_code in {401, 503}
