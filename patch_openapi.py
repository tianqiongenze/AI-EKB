import re

with open("contracts/openapi/control-plane.openapi.yaml", "r") as f:
    content = f.read()

sub_agent_paths = """
  /a2a/sub-agent/delegate:
    post:
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SubAgentTaskRequest'
      responses:
        '200':
          description: delegated
"""

sub_agent_schemas = """
    SubAgentTaskRequest:
      type: object
      required:
        - supervisor_id
        - sub_agent_type
        - task_objective
      properties:
        supervisor_id:
          type: string
        sub_agent_type:
          type: string
        task_objective:
          type: string
        context_payload:
          type: object
        timeout_seconds:
          type: integer
    SubAgentTaskResult:
      type: object
      required:
        - task_id
        - sub_agent_type
        - status
      properties:
        task_id:
          type: string
        sub_agent_type:
          type: string
        status:
          type: string
        result_payload:
          type: object
"""

if "/a2a/sub-agent/delegate:" not in content:
    content = content.replace("  /a2a/consume:", sub_agent_paths + "  /a2a/consume:")
    content = content + sub_agent_schemas
    with open("contracts/openapi/control-plane.openapi.yaml", "w") as f:
        f.write(content)

