from __future__ import annotations

from dataclasses import dataclass

from enterprise_ekb.schemas import GatewayInvokeRequest
from enterprise_ekb.skill_registry import SkillRegistry


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    def __init__(self, skill_registry: SkillRegistry) -> None:
        self.skill_registry = skill_registry

    def evaluate_invoke(self, request: GatewayInvokeRequest) -> PolicyDecision:
        try:
            skill = self.skill_registry.get(request.skill_name, request.skill_version)
        except KeyError:
            return PolicyDecision(allowed=False, reason="skill_not_found")

        if skill.stage.value != "production":
            return PolicyDecision(allowed=False, reason="skill_not_in_production")

        manifest = skill.manifest
        if request.tool_name not in manifest.allowed_tools:
            return PolicyDecision(allowed=False, reason="tool_not_allowed")

        if request.domain not in manifest.allowed_domains:
            return PolicyDecision(allowed=False, reason="domain_not_allowed")

        if request.region_id not in manifest.residency_scope:
            return PolicyDecision(allowed=False, reason="residency_violation")

        return PolicyDecision(allowed=True, reason="ok")
