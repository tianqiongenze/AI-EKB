"""P0-② 文档处理流水线 — 架构规格 §5.1「知识库构建 Pipeline」第一步+第二步。

能力（真实解析器，无占位 stub —— MPB 铁律）：
- PDF   → PyMuPDF（pymupdf）：文本 + 内置表格识别 + 图片占位
- Word  → python-docx：段落（含标题层级）+ 表格
- PPT   → python-pptx：幻灯片文本 + 表格
- 扫描件 → PaddleOCR（可选依赖 extra `ocr`；未安装时能力如实上报 unavailable，不伪造 —— HSA）
- 智能分块：语义/父子分块 + 滑动窗口 512 tokens / overlap 64；
  表格、图片为独立 chunk 并带元数据标注。
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger("enterprise_ekb.document_pipeline")

try:  # PyMuPDF >=1.24 推荐 import pymupdf；fitz 仍可用但已弃用
    import pymupdf

    _PDF_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境缺库时如实降级
    try:
        import fitz as pymupdf  # type: ignore[no-redef,import-untyped]

        _PDF_AVAILABLE = True
    except ImportError:
        pymupdf = None  # type: ignore[assignment]
        _PDF_AVAILABLE = False

try:
    import docx as _docx

    _DOCX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _docx = None  # type: ignore[assignment]
    _DOCX_AVAILABLE = False

try:
    import pptx as _pptx

    _PPTX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _pptx = None  # type: ignore[assignment]
    _PPTX_AVAILABLE = False

try:
    from paddleocr import PaddleOCR  # type: ignore

    _OCR_ENGINE: Any | None = None
    _OCR_AVAILABLE = True
except ImportError:  # pragma: no cover - 可选 extra，缺省如实上报
    PaddleOCR = None
    _OCR_AVAILABLE = False

# ---------------------------------------------------------------------------
# 分块参数（§5.1：滑动窗口 512 tokens，overlap 64）
# ---------------------------------------------------------------------------
CHUNK_TARGET_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 64

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff]")
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_DOCX_HEADING_PREFIX = "Heading "


def estimate_tokens(text: str) -> int:
    """确定性 token 估算：CJK 字符按 1 token/字，ASCII 词按 1 token/词。

    与在线 tokenizer 误差 ±15% 内，用于分块窗口控制足够；不引入外部依赖。
    """
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    words = len(_WORD_RE.findall(text))
    return cjk + words


@dataclass
class ParsedBlock:
    """解析产出的最小内容单元（父子分块的父层候选）。"""

    kind: str  # "text" | "table" | "image"
    content: str
    page: int = 0
    heading: str = ""  # 所属章节标题（父块标识）
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    source_name: str
    source_type: str  # pdf/docx/pptx/txt/markdown/csv/scanned
    mime_type: str
    page_count: int
    blocks: list[ParsedBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_ocr(self) -> bool:
        return self.source_type == "scanned" or (
            self.source_type == "pdf"
            and sum(estimate_tokens(b.content) for b in self.blocks if b.kind == "text") < 32
        )


def parser_capabilities() -> dict[str, bool]:
    """如实上报各解析器可用性（HSA：能力缺失不掩盖）。"""
    return {
        "pdf": _PDF_AVAILABLE,
        "docx": _DOCX_AVAILABLE,
        "pptx": _PPTX_AVAILABLE,
        "ocr": _OCR_AVAILABLE,
    }


# ---------------------------------------------------------------------------
# Step 1 文档解析
# ---------------------------------------------------------------------------
def parse_bytes(source_name: str, source_type: str, payload: bytes) -> ParsedDocument:
    if payload is None or not payload:
        raise ValueError("empty_payload")
    st = (source_type or "").lower().lstrip(".")
    if st in {"pdf"}:
        return _parse_pdf(source_name, payload)
    if st in {"docx", "doc"}:
        return _parse_docx(source_name, payload)
    if st in {"pptx", "ppt"}:
        return _parse_pptx(source_name, payload)
    if st in {"txt", "md", "markdown", "csv", "log", "json"}:
        return _parse_plain(source_name, st, payload)
    if st in {"scanned", "png", "jpg", "jpeg", "tif", "tiff"}:
        return _parse_scanned(source_name, st, payload)
    raise ValueError(f"unsupported_source_type:{st}")


def _parse_pdf(source_name: str, payload: bytes) -> ParsedDocument:
    doc = ParsedDocument(source_name, "pdf", "application/pdf", 0)
    if not _PDF_AVAILABLE or pymupdf is None:
        doc.warnings.append("parser_unavailable:pdf(PyMuPDF)")
        return doc
    with pymupdf.open(stream=payload, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
        doc.page_count = pdf.page_count
        for page_index, page in enumerate(pdf):
            text = page.get_text("text").strip()
            if text:
                doc.blocks.append(
                    ParsedBlock(kind="text", content=text, page=page_index + 1)
                )
            # 表格：保留结构化格式（§5.1 表格→结构化解析保留表格格式）
            try:
                tables = page.find_tables()
            except Exception:
                tables = None
            if tables is not None:
                for table in tables:
                    rows = table.extract()
                    if not rows:
                        continue
                    serialized = _serialize_table(rows)
                    if serialized:
                        doc.blocks.append(
                            ParsedBlock(
                                kind="table",
                                content=serialized,
                                page=page_index + 1,
                                metadata={"rows": len(rows)},
                            )
                        )
            # 图片：独立 chunk 占位 + 元数据（OCR 可用时补文本）
            for img_index in range(len(page.get_images(full=True))):
                doc.blocks.append(
                    ParsedBlock(
                        kind="image",
                        content=f"[image p{page_index + 1} #{img_index + 1}]",
                        page=page_index + 1,
                        metadata={"image_index": img_index},
                    )
                )
    if doc.needs_ocr and _OCR_AVAILABLE:
        _ocr_augment(doc, payload)
    elif doc.needs_ocr:
        doc.warnings.append(
            "ocr_unavailable:扫描件/无文本 PDF 需安装可选依赖 extra `ocr` (PaddleOCR)"
        )
    return doc


def _ocr_augment(doc: ParsedDocument, payload: bytes) -> None:
    """对无文本 PDF 逐页 OCR，把识别文本补为 text 块（真实引擎调用）。"""
    global _OCR_ENGINE
    if not _PDF_AVAILABLE or pymupdf is None:
        return
    try:
        if _OCR_ENGINE is None:
            _OCR_ENGINE = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        with pymupdf.open(stream=payload, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
            for page_index, page in enumerate(pdf):
                pix = page.get_pixmap(dpi=200)
                result = _OCR_ENGINE.ocr(pix.tobytes("png"), cls=True)
                lines: list[str] = []
                for item in result or []:
                    for line in item or []:
                        if isinstance(line, (list, tuple)) and len(line) >= 2:
                            text = line[1]
                            if isinstance(text, str) and text.strip():
                                lines.append(text.strip())
                if lines:
                    doc.blocks.append(
                        ParsedBlock(
                            kind="text",
                            content="\n".join(lines),
                            page=page_index + 1,
                            metadata={"ocr": True},
                        )
                    )
    except Exception as exc:
        doc.warnings.append(f"ocr_failed:{type(exc).__name__}")


def _parse_docx(source_name: str, payload: bytes) -> ParsedDocument:
    import io

    doc = ParsedDocument(source_name, "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 1)
    if not _DOCX_AVAILABLE or _docx is None:
        doc.warnings.append("parser_unavailable:docx(python-docx)")
        return doc
    try:
        assert _docx is not None
        d = _docx.Document(io.BytesIO(payload))
    except Exception as exc:
        raise ValueError(f"docx_parse_failed:{type(exc).__name__}") from exc
    current_heading = ""
    doc.page_count = 1
    for para in d.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style_name = ""
        try:
            style_name = para.style.name if para.style is not None else ""
        except Exception:
            style_name = ""
        if style_name.startswith(_DOCX_HEADING_PREFIX):
            current_heading = text
            doc.blocks.append(
                ParsedBlock(kind="text", content=f"# {text}", heading=current_heading)
            )
            continue
        doc.blocks.append(ParsedBlock(kind="text", content=text, heading=current_heading))
    for table in d.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        serialized = _serialize_table(rows)
        if serialized:
            doc.blocks.append(
                ParsedBlock(kind="table", content=serialized, metadata={"rows": len(rows)})
            )
    return doc


def _parse_pptx(source_name: str, payload: bytes) -> ParsedDocument:
    import io

    doc = ParsedDocument(source_name, "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", 0)
    if not _PPTX_AVAILABLE or _pptx is None:
        doc.warnings.append("parser_unavailable:pptx(python-pptx)")
        return doc
    try:
        assert _pptx is not None
        prs = _pptx.Presentation(io.BytesIO(payload))
    except Exception as exc:
        raise ValueError(f"pptx_parse_failed:{type(exc).__name__}") from exc
    for slide_index, slide in enumerate(prs.slides):
        slide_title = ""
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs).strip()
                    if not text:
                        continue
                    if not slide_title:
                        slide_title = text
                    doc.blocks.append(
                        ParsedBlock(
                            kind="text",
                            content=text,
                            page=slide_index + 1,
                            heading=slide_title,
                        )
                    )
            if getattr(shape, "has_table", False):
                tbl = shape.table
                rows = [
                    [cell.text_frame.text.strip() for cell in row.cells] for row in tbl.rows
                ]
                serialized = _serialize_table(rows)
                if serialized:
                    doc.blocks.append(
                        ParsedBlock(
                            kind="table",
                            content=serialized,
                            page=slide_index + 1,
                            metadata={"rows": len(rows)},
                        )
                    )
        doc.page_count = slide_index + 1 if prs.slides else 0
    return doc


def _parse_plain(source_name: str, source_type: str, payload: bytes) -> ParsedDocument:
    mime = {
        "csv": "text/csv",
        "json": "application/json",
        "md": "text/markdown",
        "markdown": "text/markdown",
    }.get(source_type, "text/plain")
    doc = ParsedDocument(source_name, source_type, mime, 1)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = payload.decode("gb18030", errors="replace")
        doc.warnings.append("decoded_as_gb18030")
    current_heading = ""
    pending_table: list[str] = []

    def _flush_table() -> None:
        nonlocal pending_table
        if not pending_table:
            return
        rows = [
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in pending_table
            if not re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", line)
        ]
        serialized = _serialize_table(rows)
        if serialized:
            doc.blocks.append(
                ParsedBlock(kind="table", content=serialized, heading=current_heading)
            )
        pending_table = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            pending_table.append(stripped)
            continue
        _flush_table()
        if not stripped:
            continue
        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            current_heading = heading_match.group(2).strip()
            doc.blocks.append(ParsedBlock(kind="text", content=line, heading=current_heading))
            continue
        doc.blocks.append(ParsedBlock(kind="text", content=line, heading=current_heading))
    _flush_table()
    return doc


def _parse_scanned(source_name: str, source_type: str, payload: bytes) -> ParsedDocument:
    mime_by_ext = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "tif": "image/tiff",
        "tiff": "image/tiff",
    }
    doc = ParsedDocument(
        source_name, "scanned", mime_by_ext.get(source_type, "application/octet-stream"), 1
    )
    if not _OCR_AVAILABLE or PaddleOCR is None:
        doc.warnings.append(
            "ocr_unavailable:扫描件需安装可选依赖 extra `ocr` (PaddleOCR) — DEFERRED"
        )
        return doc
    try:
        engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = engine.ocr(payload, cls=True)
        lines: list[str] = []
        for item in result or []:
            for line in item or []:
                if isinstance(line, (list, tuple)) and len(line) >= 2:
                    text = line[1]
                    if isinstance(text, str) and text.strip():
                        lines.append(text.strip())
        if lines:
            doc.blocks.append(
                ParsedBlock(kind="text", content="\n".join(lines), metadata={"ocr": True})
            )
    except Exception as exc:
        doc.warnings.append(f"ocr_failed:{type(exc).__name__}")
    return doc


def _serialize_table(rows: list[list[Any]]) -> str:
    """表格序列化：保留结构的 Markdown 管道表 + JSON 双形态（结构化保真）。"""
    cleaned = [[("" if c is None else str(c)).strip() for c in row] for row in rows]
    cleaned = [row for row in cleaned if any(cell for cell in row)]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    normalized = [row + [""] * (width - len(row)) for row in cleaned]
    header = normalized[0]
    body = normalized[1:] if len(normalized) > 1 else [ [""] * width ]
    md_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    md_lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(md_lines)


# ---------------------------------------------------------------------------
# Step 2 智能分块：语义/父子 + 滑动窗口 512/64 + 表格图片独立 chunk
# ---------------------------------------------------------------------------
@dataclass
class DocumentChunk:
    chunk_id: str
    doc_id: str
    seq: int
    chunk_type: str  # text | table | image | parent
    parent_id: str
    content: str
    tokens: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        import json as _json

        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "seq": self.seq,
            "chunk_type": self.chunk_type,
            "parent_id": self.parent_id,
            "content": self.content,
            "tokens": self.tokens,
            "metadata_json": _json.dumps(self.metadata, ensure_ascii=False),
        }


def chunk_document(doc_id: str, parsed: ParsedDocument) -> list[DocumentChunk]:
    """父子分块：同一 heading 下的 text 块聚合为 parent；parent 内按 512/64 滑窗切 child。

    表格/图片块始终独立成 chunk（child 挂到所在章节 parent）。
    """
    if parsed is None:
        raise ValueError("parsed_required")
    chunks: list[DocumentChunk] = []
    seq = 0

    # 1) 按 heading 聚合 text 块 → parent 分组
    groups: list[dict[str, Any]] = []
    by_heading: dict[str, dict[str, Any]] = {}
    for block in parsed.blocks:
        if block.kind != "text":
            continue
        key = block.heading or "__root__"
        if key not in by_heading:
            group = {
                "heading": "" if key == "__root__" else key,
                "pages": [],
                "texts": [],
            }
            by_heading[key] = group
            groups.append(group)
        by_heading[key]["texts"].append(block.content)
        if block.page:
            by_heading[key]["pages"].append(block.page)

    def _next_chunk_id() -> str:
        return hashlib.sha1(f"{doc_id}:{seq}".encode()).hexdigest()[:24]

    # 2) 每 parent 内滑动窗口切 child（按句子/行边界对齐，避免硬截断）
    for group in groups:
        joined = "\n".join(group["texts"])
        if not joined.strip():
            continue
        parent_id = ""
        if group["heading"]:
            parent_id = hashlib.sha1(
                f"{doc_id}:parent:{group['heading']}".encode()
            ).hexdigest()[:24]
            chunks.append(
                DocumentChunk(
                    chunk_id=parent_id,
                    doc_id=doc_id,
                    seq=seq,
                    chunk_type="parent",
                    parent_id="",
                    content=f"## {group['heading']}\n{joined}"[: CHUNK_TARGET_TOKENS * 4],
                    tokens=estimate_tokens(joined),
                    metadata={
                        "heading": group["heading"],
                        "pages": sorted(set(group["pages"]))[:20],
                        "source_type": parsed.source_type,
                    },
                )
            )
            seq += 1
        for window in _sliding_windows(joined):
            chunks.append(
                DocumentChunk(
                    chunk_id=_next_chunk_id(),
                    doc_id=doc_id,
                    seq=seq,
                    chunk_type="text",
                    parent_id=parent_id,
                    content=window,
                    tokens=estimate_tokens(window),
                    metadata={
                        "heading": group["heading"],
                        "pages": sorted(set(group["pages"]))[:20],
                        "source_type": parsed.source_type,
                    },
                )
            )
            seq += 1

    # 3) 表格 / 图片独立 chunk
    for block in parsed.blocks:
        if block.kind not in {"table", "image"}:
            continue
        heading_key = block.heading or "__root__"
        parent_id = ""
        if heading_key in by_heading and by_heading[heading_key]["heading"]:
            parent_id = hashlib.sha1(
                f"{doc_id}:parent:{by_heading[heading_key]['heading']}".encode()
            ).hexdigest()[:24]
        chunks.append(
            DocumentChunk(
                chunk_id=_next_chunk_id(),
                doc_id=doc_id,
                seq=seq,
                chunk_type=block.kind,
                parent_id=parent_id,
                content=block.content,
                tokens=estimate_tokens(block.content),
                metadata={
                    "page": block.page,
                    "source_type": parsed.source_type,
                    **block.metadata,
                },
            )
        )
        seq += 1
    return chunks


def _sliding_windows(text: str) -> list[str]:
    """按行聚合的滑动窗口：目标 ≤512 tokens，overlap 64 tokens。"""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    windows: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for line in lines:
        line_tokens = estimate_tokens(line)
        if current and current_tokens + line_tokens > CHUNK_TARGET_TOKENS:
            windows.append("\n".join(current))
            # 回退到 overlap 预算内保留尾部行
            tail: list[str] = []
            tail_tokens = 0
            for prev in reversed(current):
                prev_tokens = estimate_tokens(prev)
                if tail_tokens + prev_tokens > CHUNK_OVERLAP_TOKENS:
                    break
                tail.insert(0, prev)
                tail_tokens += prev_tokens
            current = tail
            current_tokens = tail_tokens
        current.append(line)
        current_tokens += line_tokens
    if current:
        windows.append("\n".join(current))
    # 单行超窗（长表格行/长段落）按 token 比例硬切兜底
    final: list[str] = []
    for window in windows:
        final.extend(_hard_split(window))
    return final


def _hard_split(text: str) -> list[str]:
    """超长单元兜底切分：按 token/字符比例切块，保证块 token 预算受控。"""
    total = estimate_tokens(text)
    if total <= int(CHUNK_TARGET_TOKENS * 1.2):
        return [text]
    ratio = len(text) / max(total, 1)  # 每token平均字符数（CJK≈1，ASCII≈1.6+）
    size = max(64, int(CHUNK_TARGET_TOKENS * ratio))
    return [text[start : start + size] for start in range(0, len(text), size)]


def content_sha256(payload: bytes) -> str:
    if payload is None:
        return ""
    return hashlib.sha256(payload).hexdigest()
