import re

with open("src/enterprise_ekb/schemas.py", "r") as f:
    content = f.read()

new_classes = """

class SubAgentTaskRequest(BaseModel):
    supervisor_id: str
    sub_agent_type: str
    task_objective: str
    context_payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


class SubAgentTaskResult(BaseModel):
    task_id: str
    sub_agent_type: str
    status: str
    result_payload: dict[str, Any] = Field(default_factory=dict)
"""

if "SubAgentTaskRequest" not in content:
    with open("src/enterprise_ekb/schemas.py", "a") as f:
        f.write(new_classes)
