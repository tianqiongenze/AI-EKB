"""Skill lifecycle bounded context: manifest, risk levels and promotion."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SkillRiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SkillStage(str, Enum):
    draft = "draft"
    review = "review"
    staging = "staging"
    production = "production"
    deprecated = "deprecated"


class SkillManifest(BaseModel):
    skill_name: str = Field(min_length=2)
    version: str = Field(min_length=1)
    owner: str = Field(min_length=2)
    risk_level: SkillRiskLevel
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    residency_scope: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    changelog: str = Field(default="")


class SkillPromotionRequest(BaseModel):
    skill_name: str
    version: str
    target_stage: SkillStage
