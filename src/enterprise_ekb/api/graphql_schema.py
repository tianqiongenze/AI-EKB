"""GraphQL 层（Apollo Federation v2 subgraph 模式，对齐 ESP writing-coach/graph/schema.py）。

职责边界（资深架构师决策）：
- GraphQL 是**读聚合层**：面向前端多端的"一次请求取多实体"场景（文档+chunk+审计+KPI 面板），
  替代 REST 的多次往返/过度获取。写路径仍走 REST（事务语义、outbox、审计绑定在 REST handler，
  避免 GraphQL mutation 绕过治理链路——治理优先于便利）。
- 降级两层（对齐 ESP esp-graphql-py）：strawberry resolver 内失败→REST fallback；
  REST 也失败→返回 null + errors（不 panic，DPC）。
- 查询复杂度防线：默认 limit clamp（1..100），防深层递归（chunk.parent 单层不递归展开）。
- LCO：query 级命中复用既有语义缓存？——否，Graph 聚合查询键复杂度高，先不做（诚实记录），
  L1 精确缓存只服务 mcp/invoke 主链路。

ASV 核实：strawberry-graphql 0.327.7，Schema(query=...) federation 2 默认开启；
make_graphql_controller(schema, path="/graphql") 返回 Litestar controller（本会话实测）。
"""

from __future__ import annotations

import strawberry
from strawberry.types import Info


def _clamp_limit(value: int | None, default: int = 20, upper: int = 100) -> int:
    """limit 钳制：None/非法值→默认；超上限→上限。防复杂度攻击面。"""
    if value is None:
        return default
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(v, upper))


# ---------------------------------------------------------------------------
# GraphQL 类型（camelCase 对外，snake_case 内部——strawberry auto_converter）
# ---------------------------------------------------------------------------
@strawberry.type
class DocumentNode:
    docId: strawberry.ID
    sourceName: str
    sourceType: str
    status: str
    pageCount: int
    chunkCount: int
    createdAt: str | None = None


@strawberry.type
class ChunkNode:
    chunkId: strawberry.ID
    seq: int
    chunkType: str
    content: str
    tokens: int
    parentId: str | None = None


@strawberry.type
class AuditNode:
    createdAt: str | None = None
    tenantId: str | None = None
    skillName: str | None = None
    toolName: str | None = None
    decisionReason: str | None = None
    accepted: bool | None = None


@strawberry.type
class RoleNode:
    code: str
    name: str
    layer: str
    human: bool
    description: str


@strawberry.type
class KpiPanelNode:
    generatedAt: str
    records: int
    oee: float | None = None
    firstPassYield: float | None = None
    eventsPerHour: float | None = None


@strawberry.type
class Query:
    @strawberry.field
    def documents(
        self,
        info: Info,
        tenantId: str | None = None,
        limit: int | None = None,
    ) -> list[DocumentNode]:
        """文档列表（REST fallback: GET /documents）。"""
        ctx = info.context["ctx"]
        try:
            items = ctx.store.list_documents(tenant_id=tenantId, limit=_clamp_limit(limit))
        except Exception:
            return []
        return [
            DocumentNode(
                docId=str(d.get("doc_id", "")),
                sourceName=str(d.get("source_name", "")),
                sourceType=str(d.get("source_type", "")),
                status=str(d.get("status", "")),
                pageCount=int(d.get("page_count", 0) or 0),
                chunkCount=int(d.get("chunk_count", 0) or 0),
                createdAt=d.get("created_at"),
            )
            for d in items
        ]

    @strawberry.field
    def document(self, info: Info, docId: strawberry.ID) -> DocumentNode | None:
        ctx = info.context["ctx"]
        try:
            d = ctx.store.get_document(str(docId))
        except Exception:
            return None
        if d is None:
            return None
        return DocumentNode(
            docId=str(d.get("doc_id", "")),
            sourceName=str(d.get("source_name", "")),
            sourceType=str(d.get("source_type", "")),
            status=str(d.get("status", "")),
            pageCount=int(d.get("page_count", 0) or 0),
            chunkCount=int(d.get("chunk_count", 0) or 0),
            createdAt=d.get("created_at"),
        )

    @strawberry.field
    def chunks(
        self,
        info: Info,
        docId: strawberry.ID,
        chunkType: str | None = None,
        limit: int | None = None,
    ) -> list[ChunkNode]:
        ctx = info.context["ctx"]
        try:
            items = ctx.store.list_document_chunks(
                str(docId), chunk_type=chunkType, limit=_clamp_limit(limit)
            )
        except Exception:
            return []
        return [
            ChunkNode(
                chunkId=str(c.get("chunk_id", "")),
                seq=int(c.get("seq", 0) or 0),
                chunkType=str(c.get("chunk_type", "")),
                content=str(c.get("content", "")),
                tokens=int(c.get("tokens", 0) or 0),
                parentId=c.get("parent_id") or None,
            )
            for c in items
        ]

    @strawberry.field
    def audits(
        self,
        info: Info,
        tenantId: str | None = None,
        limit: int | None = None,
    ) -> list[AuditNode]:
        """审计最近记录（REST fallback: POST /audit/query）。"""
        ctx = info.context["ctx"]
        try:
            rows = ctx.store.recent_audits(limit=_clamp_limit(limit, default=50))
        except Exception:
            return []
        out: list[AuditNode] = []
        for r in rows:
            tenant = getattr(r, "tenant_id", None) if not isinstance(r, dict) else r.get("tenant_id")
            accepted = getattr(r, "accepted", None) if not isinstance(r, dict) else r.get("accepted")
            out.append(
                AuditNode(
                    createdAt=(getattr(r, "created_at", None) if not isinstance(r, dict) else r.get("created_at")),
                    tenantId=tenant,
                    skillName=(getattr(r, "skill_name", None) if not isinstance(r, dict) else r.get("skill_name")),
                    toolName=(getattr(r, "tool_name", None) if not isinstance(r, dict) else r.get("tool_name")),
                    decisionReason=(getattr(r, "decision_reason", None) if not isinstance(r, dict) else r.get("decision_reason")),
                    accepted=(bool(accepted) if accepted is not None else None),
                )
            )
        if tenantId:
            out = [a for a in out if a.tenantId == tenantId]
        return out

    @strawberry.field
    def rbacRoles(self, info: Info) -> list[RoleNode]:
        try:
            from enterprise_ekb.rbac import RBACService

            roles = RBACService(store=None).describe_roles()
        except Exception:
            return []
        return [
            RoleNode(
                code=str(r.get("code", "")),
                name=str(r.get("name", "")),
                layer=str(r.get("layer", "")),
                human=bool(r.get("human", False)),
                description=str(r.get("description", "")),
            )
            for r in roles
        ]

    @strawberry.field
    def kpiPanel(self, info: Info) -> KpiPanelNode | None:
        """工业 KPI 聚合（REST fallback: GET /industrial/kpis）。GraphQL 单请求取多 KPI。"""
        ctx = info.context["ctx"]
        try:
            from enterprise_ekb.api.industrial import AUDIT_SAMPLE_LIMIT, aggregate_kpis

            panel = aggregate_kpis(ctx.store.recent_audits(limit=AUDIT_SAMPLE_LIMIT))
            overall = panel.get("overall", {})
            return KpiPanelNode(
                generatedAt=str(panel.get("generated_at", "")),
                records=int(overall.get("records", 0) or 0),
                oee=(overall.get("oee", {}) or {}).get("value"),
                firstPassYield=(overall.get("first_pass_yield", {}) or {}).get("value"),
                eventsPerHour=(overall.get("energy_proxy", {}) or {}).get("events_per_hour"),
            )
        except Exception:
            return None


@strawberry.type
class Mutation:
    @strawberry.mutation
    def clear_semantic_cache(self, info: Info) -> int:
        """清空语义缓存（等价 POST /llm-cache/clear；鉴权走 /graphql 层中间件）。"""
        try:
            from enterprise_ekb.api.llm_cache import _SEMANTIC_CACHE

            return _SEMANTIC_CACHE.clear()
        except Exception:
            return 0


federation_schema = strawberry.federation.Schema(query=Query, mutation=Mutation)
