from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from enterprise_ekb.policy import PolicyEngine
from enterprise_ekb.schemas import GatewayInvokeRequest


@dataclass(frozen=True)
class GatewayResponse:
    accepted: bool
    decision_reason: str
    data: dict[str, Any]


class MCPGateway:
    def __init__(self, policy_engine: PolicyEngine) -> None:
        self.policy_engine = policy_engine

    def invoke(self, request: GatewayInvokeRequest) -> GatewayResponse:
        decision = self.policy_engine.evaluate_invoke(request)
        if not decision.allowed:
            return GatewayResponse(
                accepted=False,
                decision_reason=decision.reason,
                data={},
            )

        response_payload = {
            "tenant_id": request.tenant_id,
            "skill": f"{request.skill_name}:{request.skill_version}",
            "tool": request.tool_name,
            "status": "executed",
        }
        return GatewayResponse(
            accepted=True,
            decision_reason=decision.reason,
            data=response_payload,
        )
