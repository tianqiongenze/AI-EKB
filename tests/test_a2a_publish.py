from enterprise_ekb.app import create_app
from litestar.testing import TestClient


def test_a2a_publish_enqueues_message() -> None:
    app = create_app()
    client = TestClient(app)
    payload = {
        "message_id": "msg-12345678",
        "correlation_id": "corr-12345678",
        "tenant_id": "group",
        "region_id": "cn-east-1",
        "plant_id": "plant-x",
        "agent_id": "planner",
        "target_agent": "executor",
        "intent": "route_task",
        "priority": "normal",
        "idempotency_key": "idem-001",
        "created_at": "2026-03-29T00:00:00Z",
        "ttl_seconds": 300,
        "payload": {"task": "dispatch"},
        "metadata": {"trace_id": "trace-1"},
    }

    resp = client.post("/a2a/publish", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["message_id"] == "msg-12345678"

    relay = client.post("/events/relay", json={"batch_size": 100})
    assert relay.status_code == 200
