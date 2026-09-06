from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_domain_capabilities_bootstrap_search_and_coverage() -> None:
    client = TestClient(create_app())

    bootstrap_resp = client.post("/domain/capabilities/bootstrap", json={"owner": "qa-team"})
    assert bootstrap_resp.status_code == 200
    assert bootstrap_resp.json()["inserted"] > 0

    search_resp = client.post(
        "/domain/capabilities/search",
        json={"domain": "quality", "query": "defect", "limit": 50},
    )
    assert search_resp.status_code == 200
    payload = search_resp.json()
    assert payload["count"] >= 1

    coverage_resp = client.get("/domain/capabilities/coverage")
    assert coverage_resp.status_code == 200
    summary = coverage_resp.json()["summary"]
    assert summary["total"] >= 10


def test_domain_capability_upsert_promotes_coverage() -> None:
    client = TestClient(create_app())

    upsert_resp = client.post(
        "/domain/capabilities/upsert",
        json={
            "domain": "manufacturing",
            "capability_type": "yield_optimization",
            "title": "yield optimization playbook",
            "description": "Factory-level yield optimization and root cause linkage",
            "owner": "manufacturing-center",
            "maturity": "implemented",
            "tags": ["manufacturing", "yield"],
            "metadata": {"source": "implementation"},
        },
    )
    assert upsert_resp.status_code == 200
    assert upsert_resp.json()["status"] == "ok"

    search_resp = client.post(
        "/domain/capabilities/search",
        json={"domain": "manufacturing", "query": "yield", "limit": 10},
    )
    assert search_resp.status_code == 200
    result = search_resp.json()
    assert result["count"] >= 1
