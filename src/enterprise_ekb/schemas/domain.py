"""Business capability / domain coverage bounded context."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from enterprise_ekb.schemas.common import BusinessDomain


class CapabilityMaturity(str, Enum):
    planned = "planned"
    implemented = "implemented"
    validated = "validated"


class BusinessCapabilityManifest(BaseModel):
    domain: BusinessDomain
    capability_type: str = Field(min_length=2)
    title: str = Field(min_length=2)
    description: str = Field(default="")
    owner: str = Field(min_length=2)
    maturity: CapabilityMaturity = CapabilityMaturity.planned
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DomainCapabilitySearchRequest(BaseModel):
    domain: BusinessDomain | None = None
    query: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


class DomainCapabilitySearchResult(BaseModel):
    count: int
    items: list[BusinessCapabilityManifest]


class DomainCoverageItem(BaseModel):
    domain: BusinessDomain
    required_count: int
    implemented_count: int
    planned_count: int
    status: str
    missing_capabilities: list[str]
    implemented_capabilities: list[str]


class DomainCoverageResponse(BaseModel):
    summary: dict[str, int]
    items: list[DomainCoverageItem]


class DomainBootstrapRequest(BaseModel):
    owner: str = Field(default="domain-pmo")
