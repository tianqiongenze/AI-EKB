from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_healthz() -> None:
    client = TestClient(create_app(db_path=":memory:"))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_capacity_estimate_endpoint() -> None:
    client = TestClient(create_app(db_path=":memory:"))
    resp = client.post(
        "/capacity/estimate",
        json={
            "online_users": 100000,
            "active_ratio": 0.1,
            "cache_hit_ratio": 0.5,
            "complex_ratio": 0.3,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["estimated_qps"] == 10000
    assert body["estimated_llm_qps"] == 5000
    assert body["estimated_cross_region_qps"] == 0
    assert body["estimated_failover_peak_qps"] == 11500
    assert body["recommended_gateway_vcpu"] > 0
    assert body["recommended_control_plane_vcpu"] > 0
