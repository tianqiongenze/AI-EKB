import re

with open("src/enterprise_ekb/app.py", "r") as f:
    content = f.read()

sub_agent_endpoint = """
    @api.post("/a2a/sub-agent/delegate")
    def delegate_sub_agent(request: SubAgentTaskRequest, raw_request: Request) -> dict[str, object]:
        if config.auth_token:
            auth_header = raw_request.headers.get("authorization", "")
            if auth_header != f"Bearer {config.auth_token}":
                raise HTTPException(status_code=401, detail="unauthorized")
        limit_result = a2a_rate_limiter.allow()
        if not limit_result.allowed:
            raise HTTPException(status_code=429, detail="rate_limited")
            
        import uuid
        import time
        from enterprise_ekb.schemas import A2APriority
        
        task_id = f"subtask_{uuid.uuid4().hex[:8]}"
        
        store.enqueue_outbox(
            event_type="a2a.message",
            payload={
                "event_type": "a2a.message",
                "topic": f"persistent://system/a2a/global/{request.sub_agent_type}",
                "message_id": task_id,
                "correlation_id": task_id,
                "tenant_id": "system",
                "region_id": "global",
                "plant_id": "none",
                "agent_id": request.supervisor_id,
                "target_agent": request.sub_agent_type,
                "intent": "delegate_sub_task",
                "priority": A2APriority.high.value,
                "idempotency_key": task_id,
                "created_at": str(time.time()),
                "ttl_seconds": request.timeout_seconds,
                "payload": {
                    "objective": request.task_objective,
                    "context": request.context_payload
                },
                "metadata": {
                    "is_sub_agent_task": True,
                    "supervisor_id": request.supervisor_id
                }
            },
        )
        return {"status": "delegated", "task_id": task_id}

"""

if "def delegate_sub_agent" not in content:
    # insert before def consume_a2a() -> dict[str, object]:
    content = content.replace("    @api.post(\"/a2a/consume\")", sub_agent_endpoint + "    @api.post(\"/a2a/consume\")")
    with open("src/enterprise_ekb/app.py", "w") as f:
        f.write(content)
