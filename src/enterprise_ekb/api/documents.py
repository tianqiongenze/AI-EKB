"""P0-② 文档接入 API — 文档解析→智能分块→存储→检索索引。

路由契约（前端 Documents.tsx 依赖）：
- POST /documents/ingest   {source_name, source_type, tenant_id, content_b64}
                           → {doc_id, status, chunks, warnings, capabilities}
- GET  /documents?tenant_id=&limit= → {items: [...]}
- GET  /documents/{doc_id}          → 文档详情
- GET  /documents/{doc_id}/chunks?chunk_type=&limit= → {items: [{seq, chunk_type, content, tokens, parent_id}]}
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging

from litestar import Request, delete, get, post
from litestar.exceptions import HTTPException
from pydantic import BaseModel, Field

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.document_pipeline import (
    chunk_document,
    content_sha256,
    parse_bytes,
    parser_capabilities,
)

_logger = logging.getLogger("enterprise_ekb.api.documents")

_SUPPORTED_TYPES = {"pdf", "docx", "pptx", "txt", "md", "markdown", "csv", "json", "log"}


class DocumentIngestRequest(BaseModel):
    source_name: str = Field(min_length=1, max_length=512)
    source_type: str = Field(min_length=1, max_length=32)
    tenant_id: str = Field(default="group", max_length=191)
    content_b64: str = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)


def routes(ctx: ControlPlaneContext) -> list:
    @post("/documents/ingest", status_code=200, sync_to_thread=True)
    def ingest_document(data: DocumentIngestRequest, request: Request) -> dict:
        ctx._require_admin_auth(request)
        source_type = data.source_type.lower().lstrip(".")
        if source_type not in _SUPPORTED_TYPES and source_type not in {
            "doc",
            "ppt",
            "scanned",
            "png",
            "jpg",
            "jpeg",
        }:
            raise HTTPException(status_code=400, detail="unsupported_source_type")
        try:
            payload = base64.b64decode(data.content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid_base64") from exc
        if not payload:
            raise HTTPException(status_code=400, detail="empty_payload")

        digest = content_sha256(payload)
        doc_id = hashlib.sha1(
            f"{data.tenant_id}:{data.source_name}:{digest}".encode()
        ).hexdigest()[:24]

        # 已有同内容文档 → 幂等返回
        existing = ctx.store.get_document(doc_id)
        if existing is not None and existing.get("status") == "indexed":
            return {
                "doc_id": doc_id,
                "status": "indexed",
                "chunks": int(existing.get("chunk_count", 0) or 0),
                "warnings": existing.get("metadata", {}).get("warnings", []),
                "capabilities": parser_capabilities(),
                "idempotent": True,
            }

        try:
            parsed = parse_bytes(data.source_name, source_type, payload)
        except ValueError as exc:
            ctx.store.upsert_document(
                {
                    "doc_id": doc_id,
                    "tenant_id": data.tenant_id,
                    "source_name": data.source_name,
                    "source_type": source_type,
                    "mime_type": "application/octet-stream",
                    "content_sha256": digest,
                    "status": "failed",
                    "error": str(exc),
                    "metadata": {"requested_by": "ingest"},
                }
            )
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        chunks = chunk_document(doc_id, parsed)
        ctx.store.upsert_document(
            {
                "doc_id": doc_id,
                "tenant_id": data.tenant_id,
                "source_name": data.source_name,
                "source_type": parsed.source_type,
                "mime_type": parsed.mime_type,
                "content_sha256": digest,
                "status": "parsed",
                "page_count": parsed.page_count,
                "chunk_count": len(chunks),
                "error": "",
                "metadata": {
                    "warnings": parsed.warnings,
                    "requested_metadata": data.metadata,
                    **({"ocr_flagged": True} if parsed.needs_ocr else {}),
                },
            }
        )
        ctx.store.replace_document_chunks(doc_id, [chunk.to_row() for chunk in chunks])
        ctx.store.upsert_document(
            {
                "doc_id": doc_id,
                "tenant_id": data.tenant_id,
                "source_name": data.source_name,
                "source_type": parsed.source_type,
                "mime_type": parsed.mime_type,
                "content_sha256": digest,
                "status": "indexed",
                "page_count": parsed.page_count,
                "chunk_count": len(chunks),
                "metadata": {
                    "warnings": parsed.warnings,
                    "requested_metadata": data.metadata,
                },
            }
        )
        ctx.store.enqueue_outbox(
            event_type="document.ingested",
            payload={
                "doc_id": doc_id,
                "tenant_id": data.tenant_id,
                "source_name": data.source_name,
                "source_type": parsed.source_type,
                "chunk_count": len(chunks),
                "content_sha256": digest,
            },
        )
        return {
            "doc_id": doc_id,
            "status": "indexed",
            "chunks": len(chunks),
            "pages": parsed.page_count,
            "warnings": parsed.warnings,
            "capabilities": parser_capabilities(),
            "idempotent": False,
        }

    @get("/documents", status_code=200, sync_to_thread=True)
    def list_documents(
        request: Request, tenant_id: str | None = None, limit: int = 50
    ) -> dict:
        ctx._require_auth(request)
        items = ctx.store.list_documents(tenant_id=tenant_id, limit=limit)
        return {"items": items, "count": len(items)}

    @get("/documents/{doc_id:str}", status_code=200, sync_to_thread=True)
    def get_document(request: Request, doc_id: str) -> dict:
        ctx._require_auth(request)
        doc = ctx.store.get_document(doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document_not_found")
        return doc

    @get("/documents/{doc_id:str}/chunks", status_code=200, sync_to_thread=True)
    def list_chunks(
        request: Request,
        doc_id: str,
        chunk_type: str | None = None,
        limit: int = 200,
    ) -> dict:
        ctx._require_auth(request)
        doc = ctx.store.get_document(doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document_not_found")
        items = ctx.store.list_document_chunks(
            doc_id, chunk_type=chunk_type, limit=limit
        )
        return {"items": items, "count": len(items)}

    @delete("/documents/{doc_id:str}", status_code=200, sync_to_thread=True)
    def delete_document(request: Request, doc_id: str) -> dict:
        ctx._require_admin_auth(request)
        doc = ctx.store.get_document(doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document_not_found")
        ctx.store.replace_document_chunks(doc_id, [])
        ctx.store.upsert_document(
            {**doc, "status": "deleted", "chunk_count": 0}
        )
        ctx.store.enqueue_outbox(
            event_type="document.deleted",
            payload={"doc_id": doc_id, "tenant_id": doc.get("tenant_id", "group")},
        )
        return {"doc_id": doc_id, "status": "deleted"}

    return [ingest_document, list_documents, get_document, list_chunks, delete_document]
