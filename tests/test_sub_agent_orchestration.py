import os
from pathlib import Path

from litestar.testing import TestClient

from enterprise_ekb.app import create_app


def test_sub_agent_delegate_and_query_flow(tmp_path: Path) -> None:
    os.environ["EKB_AUTH_TOKEN"] = "test-token"
    db_path = tmp_path / "sub_agent_flow.db"
    client = TestClient(create_app(db_path=str(db_path)))
    headers = {"Authorization": "Bearer test-token"}

    delegate_resp = client.post(
        "/a2a/sub-agent/delegate",
        json={
            "tenant_id": "group",
            "region_id": "cn-east-1",
            "supervisor_id": "planner",
            "sub_agent_type": "executor",
            "task_objective": "prepare route",
            "context_payload": {"order": "SO-1001"},
            "idempotency_key": "idem-sub-agent-001",
            "priority": "high",
        },
        headers=headers,
    )
    assert delegate_resp.status_code == 200
    body = delegate_resp.json()
    assert body["status"] == "queued"
    task_id = body["task_id"]

    same_delegate_resp = client.post(
        "/a2a/sub-agent/delegate",
        json={
            "tenant_id": "group",
            "region_id": "cn-east-1",
            "supervisor_id": "planner",
            "sub_agent_type": "executor",
            "task_objective": "prepare route",
            "context_payload": {"order": "SO-1001"},
            "idempotency_key": "idem-sub-agent-001",
            "priority": "high",
        },
        headers=headers,
    )
    assert same_delegate_resp.status_code == 200
    assert same_delegate_resp.json()["task_id"] == task_id

    running_resp = client.post(
        "/a2a/sub-agent/result",
        json={
            "task_id": task_id,
            "sub_agent_type": "executor",
            "status": "running",
            "worker_id": "worker-1",
        },
        headers=headers,
    )
    assert running_resp.status_code == 200
    assert running_resp.json()["status"] == "running"
    assert running_resp.json()["attempt_count"] == 1

    completed_resp = client.post(
        "/a2a/sub-agent/result",
        json={
            "task_id": task_id,
            "sub_agent_type": "executor",
            "status": "completed",
            "result_payload": {"plan": "ok"},
            "worker_id": "worker-1",
        },
        headers=headers,
    )
    assert completed_resp.status_code == 200
    assert completed_resp.json()["status"] == "completed"
    assert completed_resp.json()["result_payload"]["plan"] == "ok"

    task_resp = client.get(f"/a2a/sub-agent/tasks/{task_id}", headers=headers)
    assert task_resp.status_code == 200
    assert task_resp.json()["task_id"] == task_id

    list_resp = client.get(
        "/a2a/sub-agent/tasks",
        params={"supervisor_id": "planner", "limit": 10},
        headers=headers,
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1
    assert list_resp.json()[0]["supervisor_id"] == "planner"


def test_sub_agent_result_not_found(tmp_path: Path) -> None:
    os.environ["EKB_AUTH_TOKEN"] = "test-token"
    db_path = tmp_path / "sub_agent_not_found.db"
    client = TestClient(create_app(db_path=str(db_path)))
    headers = {"Authorization": "Bearer test-token"}

    resp = client.post(
        "/a2a/sub-agent/result",
        json={
            "task_id": "missing-task",
            "sub_agent_type": "executor",
            "status": "failed",
            "error": "not found",
        },
        headers=headers,
    )
    assert resp.status_code == 404


def test_sub_agent_failed_goes_retry_then_dlq(tmp_path: Path) -> None:
    os.environ["EKB_AUTH_TOKEN"] = "test-token"
    db_path = tmp_path / "sub_agent_retry_dlq.db"
    client = TestClient(create_app(db_path=str(db_path)))
    headers = {"Authorization": "Bearer test-token"}

    delegate_resp = client.post(
        "/a2a/sub-agent/delegate",
        json={
            "tenant_id": "group",
            "region_id": "cn-east-1",
            "supervisor_id": "planner",
            "sub_agent_type": "executor",
            "task_objective": "retry flow",
            "idempotency_key": "idem-sub-agent-retry-001",
        },
        headers=headers,
    )
    assert delegate_resp.status_code == 200
    task_id = delegate_resp.json()["task_id"]

    for _ in range(4):
        fail_resp = client.post(
            "/a2a/sub-agent/result",
            json={
                "task_id": task_id,
                "sub_agent_type": "executor",
                "status": "failed",
                "error": "transient",
                "worker_id": "worker-retry",
            },
            headers=headers,
        )
        assert fail_resp.status_code == 200
        assert fail_resp.json()["status"] in {"retrying", "failed"}

    final_fail = client.post(
        "/a2a/sub-agent/result",
        json={
            "task_id": task_id,
            "sub_agent_type": "executor",
            "status": "failed",
            "error": "permanent",
            "worker_id": "worker-retry",
        },
        headers=headers,
    )
    assert final_fail.status_code == 200
    assert final_fail.json()["status"] == "failed"
