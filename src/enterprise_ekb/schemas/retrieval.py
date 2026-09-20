"""Retrieval bounded context: hybrid retrieval plus graph/vector knowledge-store primitives."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HybridRetrievalItem(BaseModel):
    id: str
    score: float
    title: str | None = None


class HybridRetrievalResult(BaseModel):
    items: list[HybridRetrievalItem]
    legs: dict[str, int]
    degraded: bool


class HybridRetrievalRequest(BaseModel):
    tenant_id: str
    region_id: str
    query: str | None = None
    vector: list[float] | None = None
    collection_name: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)


class GraphRelation(BaseModel):
    source: str
    target: str
    relation_type: str


class GraphUpsertRequest(BaseModel):
    rows: list[GraphRelation]


class VectorUpsertRequest(BaseModel):
    collection_name: str
    rows: list[dict[str, Any]]


class VectorSearchRequest(BaseModel):
    collection_name: str
    vectors: list[list[float]]
    limit: int = Field(default=10, ge=1, le=200)


class VectorSearchResult(BaseModel):
    results: Any
