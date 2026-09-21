from enterprise_ekb.harness import HarnessGate
from enterprise_ekb.schemas import HarnessEvaluationRequest


def test_harness_accepts_good_scores() -> None:
    gate = HarnessGate()
    result = gate.evaluate(
        HarnessEvaluationRequest(
            tenant_id="group",
            skill_name="retrieval-agent",
            skill_version="1.2.0",
            quality_score=0.9,
            safety_score=0.95,
            regression_score=0.91,
            latency_ms=1800,
        )
    )
    assert result.accepted
    assert result.reasons == []


def test_harness_rejects_multi_gate_failures() -> None:
    gate = HarnessGate()
    result = gate.evaluate(
        HarnessEvaluationRequest(
            tenant_id="group",
            skill_name="retrieval-agent",
            skill_version="1.2.1",
            quality_score=0.7,
            safety_score=0.8,
            regression_score=0.85,
            latency_ms=2600,
        )
    )
    assert not result.accepted
    assert "quality_gate_failed" in result.reasons
    assert "safety_gate_failed" in result.reasons
    assert "regression_gate_failed" in result.reasons
    assert "latency_gate_failed" in result.reasons


def test_harness_endpoint_roundtrip() -> None:
    from litestar.testing import TestClient

    from enterprise_ekb.app import create_app

    app = create_app(db_path=":memory:")
    client = TestClient(app)
    resp = client.post(
        "/harness/evaluate",
        json={
            "tenant_id": "group",
            "skill_name": "retrieval-agent",
            "skill_version": "1.2.2",
            "quality_score": 0.95,
            "safety_score": 0.96,
            "regression_score": 0.92,
            "latency_ms": 900,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
