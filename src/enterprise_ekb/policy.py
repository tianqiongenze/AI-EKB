from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from enterprise_ekb.schemas import GatewayInvokeRequest
from enterprise_ekb.skill_registry import SkillRegistry


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    def __init__(self, skill_registry: SkillRegistry, cache: Any | None = None) -> None:
        self.skill_registry = skill_registry
        self._cache = cache

    def evaluate_invoke(self, request: GatewayInvokeRequest) -> PolicyDecision:
        if self._cache is not None:
            cache_key = self._cache.key(
                "policy",
                self.skill_registry.epoch,
                request.skill_name,
                request.skill_version,
                request.tool_name,
                request.domain,
                request.region_id,
            )
            hit, cached = self._cache.get_json(cache_key)
            if hit and isinstance(cached, dict):
                return PolicyDecision(**cached)
        decision = self._evaluate_uncached(request)
        if self._cache is not None:
            self._cache.set_json(cache_key, {"allowed": decision.allowed, "reason": decision.reason})
        return decision

    def _evaluate_uncached(self, request: GatewayInvokeRequest) -> PolicyDecision:
        try:
            skill = self.skill_registry.get(request.skill_name, request.skill_version)
        except KeyError:
            return PolicyDecision(allowed=False, reason="skill_not_found")

        stage_val = skill.stage.value if hasattr(skill.stage, "value") else str(skill.stage)
        if stage_val != "production":
            return PolicyDecision(allowed=False, reason="skill_not_in_production")

        manifest = skill.manifest
        if request.tool_name not in manifest.allowed_tools:
            return PolicyDecision(allowed=False, reason="tool_not_allowed")

        if request.domain not in manifest.allowed_domains:
            return PolicyDecision(allowed=False, reason="domain_not_allowed")

        if request.region_id not in manifest.residency_scope:
            return PolicyDecision(allowed=False, reason="residency_violation")

        return PolicyDecision(allowed=True, reason="ok")
