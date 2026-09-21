from enterprise_ekb.schemas import SkillManifest, SkillRiskLevel, SkillStage
from enterprise_ekb.skill_registry import SkillRegistry


def test_register_and_promote_to_production() -> None:
    registry = SkillRegistry()
    manifest = SkillManifest(
        skill_name="maintenance-advisor",
        version="1.0.0",
        owner="platform-ai",
        risk_level=SkillRiskLevel.medium,
        allowed_tools=["workorder.create"],
        allowed_domains=["maintenance"],
        residency_scope=["cn-north-1"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        changelog="initial",
    )

    stored = registry.register(manifest)
    assert stored.stage is SkillStage.draft

    registry.promote("maintenance-advisor", "1.0.0", SkillStage.review)
    registry.promote("maintenance-advisor", "1.0.0", SkillStage.staging)
    final = registry.promote("maintenance-advisor", "1.0.0", SkillStage.production)
    assert final.stage is SkillStage.production


def test_high_risk_requires_security_approved_tag() -> None:
    registry = SkillRegistry()
    manifest = SkillManifest(
        skill_name="global-risk-agent",
        version="2.1.0",
        owner="security",
        risk_level=SkillRiskLevel.high,
        allowed_tools=["risk.report"],
        allowed_domains=["safety"],
        residency_scope=["cn-east-1"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        changelog="prepared",
    )
    registry.register(manifest)
    registry.promote("global-risk-agent", "2.1.0", SkillStage.review)
    registry.promote("global-risk-agent", "2.1.0", SkillStage.staging)

    try:
        registry.promote("global-risk-agent", "2.1.0", SkillStage.production)
        raise AssertionError("promotion should be rejected")
    except ValueError as exc:
        assert "security-approved" in str(exc)
