"""Cross-context shared enums and base types for enterprise_ekb schemas.

Only types referenced by more than one bounded context live here; everything
else belongs to its context module. This module must not import any sibling
schema module (it is the dependency root).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BusinessDomain(str, Enum):
    strategy = "strategy"
    rnd = "rnd"
    manufacturing = "manufacturing"
    quality = "quality"
    procurement = "procurement"
    aftersales = "aftersales"
    hr = "hr"
    finance = "finance"
    materials = "materials"
    marketing = "marketing"
    iot = "iot"
    knowledge_graph = "knowledge_graph"


class A2ASupervisionAlert(BaseModel):
    """Shared alert structure used by both A2A and data-pipeline supervision scans."""

    alert_type: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
