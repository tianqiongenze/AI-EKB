from enterprise_ekb.mcp_gateway import MCPGateway
from enterprise_ekb.policy import PolicyEngine
from enterprise_ekb.schemas import (
    GatewayInvokeRequest,
    SkillManifest,
    SkillRiskLevel,
    SkillStage,
)
from enterprise_ekb.skill_registry import SkillRegistry


def test_gateway_blocks_non_production_skill() -> None:
    registry = SkillRegistry()
    manifest = SkillManifest(
        skill_name="qa-agent",
        version="0.1.0",
        owner="ai-team",
        risk_level=SkillRiskLevel.low,
        allowed_tools=["qa.query"],
        allowed_domains=["quality"],
        residency_scope=["cn-south-1"],
        changelog="test",
    )
    registry.register(manifest)

    gateway = MCPGateway(policy_engine=PolicyEngine(skill_registry=registry))
    req = GatewayInvokeRequest(
        tenant_id="group",
        region_id="cn-south-1",
        plant_id="plant-gz",
        domain="quality",
        user_or_agent_id="user-001",
        skill_name="qa-agent",
        skill_version="0.1.0",
        tool_name="qa.query",
    )
    result = gateway.invoke(req)
    assert not result.accepted
    assert result.decision_reason == "skill_not_in_production"


def test_gateway_allows_production_skill_and_allowed_tool() -> None:
    registry = SkillRegistry()
    manifest = SkillManifest(
        skill_name="qa-agent",
        version="1.0.0",
        owner="ai-team",
        risk_level=SkillRiskLevel.low,
        allowed_tools=["qa.query"],
        allowed_domains=["quality"],
        residency_scope=["cn-south-1"],
        changelog="release",
    )
    registry.register(manifest)
    registry.promote("qa-agent", "1.0.0", SkillStage.review)
    registry.promote("qa-agent", "1.0.0", SkillStage.staging)
    registry.promote("qa-agent", "1.0.0", SkillStage.production)

    gateway = MCPGateway(policy_engine=PolicyEngine(skill_registry=registry))
    req = GatewayInvokeRequest(
        tenant_id="group",
        region_id="cn-south-1",
        plant_id="plant-gz",
        domain="quality",
        user_or_agent_id="user-002",
        skill_name="qa-agent",
        skill_version="1.0.0",
        tool_name="qa.query",
    )
    result = gateway.invoke(req)
    assert result.accepted
    assert result.decision_reason == "ok"
    assert "answer" in result.data  # P0-①: stub replaced with real LLM response
