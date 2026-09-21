"""P0-② 文档流水线测试：真实解析器（PyMuPDF/python-docx/python-pptx）+ 分块 + API 全链路。

实测模式：REAL（真实 PyMuPDF 生成 PDF、真实 python-docx 生成 docx、真实分块器）；
OCR 用例因可选依赖未装而标记为能力上报断言（非 mock 通过）。
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from enterprise_ekb.document_pipeline import (
    CHUNK_TARGET_TOKENS,
    ParsedDocument,
    chunk_document,
    estimate_tokens,
    parse_bytes,
    parser_capabilities,
)


def _client(tmp_path):
    from enterprise_ekb.app import create_app

    return TestClient(create_app(db_path=str(tmp_path / "documents.db")))


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------------
# 单元：token 估算与分块
# ---------------------------------------------------------------------------
def test_estimate_tokens_cjk_and_ascii():
    assert estimate_tokens("") == 0
    assert estimate_tokens("电池") == 2
    assert estimate_tokens("battery cell") == 2
    assert estimate_tokens("电池battery") == 3  # 2 CJK 字 + 1 ASCII 词


def test_parser_capabilities_reported_honestly():
    caps = parser_capabilities()
    assert set(caps) == {"pdf", "docx", "pptx", "ocr"}
    assert caps["pdf"] and caps["docx"] and caps["pptx"]


def test_chunk_parent_child_and_table_independent():
    parsed = ParsedDocument("t.md", "md", "text/markdown", 1)
    from enterprise_ekb.document_pipeline import ParsedBlock

    parsed.blocks = [
        ParsedBlock(kind="text", content="# 电池工艺", heading="电池工艺"),
        ParsedBlock(kind="text", content="TTFAR 电池采用石墨烯技术。", heading="电池工艺"),
        ParsedBlock(kind="table", content="| 电压 | 48V |", heading="电池工艺"),
    ]
    chunks = chunk_document("d1", parsed)
    types = {c.chunk_type for c in chunks}
    assert {"parent", "text", "table"} <= types
    table = next(c for c in chunks if c.chunk_type == "table")
    parent = next(c for c in chunks if c.chunk_type == "parent")
    assert table.parent_id == parent.chunk_id
    assert [c.seq for c in chunks] == list(range(len(chunks)))


def test_chunk_sliding_window_respects_budget():
    from enterprise_ekb.document_pipeline import _sliding_windows

    long_line = "电池产线工艺参数说明。" * 300
    windows = _sliding_windows(long_line)
    assert len(windows) > 1
    assert all(
        estimate_tokens(w) <= int(CHUNK_TARGET_TOKENS * 1.25) for w in windows
    ), [estimate_tokens(w) for w in windows]


def test_chunk_overlap_present_between_windows():
    from enterprise_ekb.document_pipeline import _sliding_windows

    lines = [f"工序{i}参数校验说明条目内容。" for i in range(120)]
    windows = _sliding_windows("\n".join(lines))
    assert len(windows) >= 2
    # 相邻窗口应有共享行（overlap 机制）
    shared = set(windows[0].splitlines()) & set(windows[1].splitlines())
    assert shared, "expected overlap between consecutive windows"


def test_chunk_invalid_input_defended():
    with pytest.raises(ValueError):
        chunk_document("d", None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 真实解析器：PDF（PyMuPDF 生成→解析）
# ---------------------------------------------------------------------------
def _make_real_pdf() -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Battery Process Overview")
    page.insert_text((72, 100), "TTFAR battery uses graphene technology.")
    payload = doc.tobytes()
    doc.close()
    return payload


def test_parse_real_pdf():
    payload = _make_real_pdf()
    parsed = parse_bytes("spec.pdf", "pdf", payload)
    assert parsed.page_count == 1
    joined = "\n".join(b.content for b in parsed.blocks if b.kind == "text")
    assert "TTFAR" in joined and "graphene" in joined


def test_parse_unsupported_type_raises():
    with pytest.raises(ValueError):
        parse_bytes("x.exe", "exe", b"binary")
    with pytest.raises(ValueError):
        parse_bytes("empty.pdf", "pdf", b"")


def test_parse_scanned_reports_ocr_capability():
    parsed = parse_bytes("scan.png", "png", b"\x89PNG fake")
    assert parsed.source_type == "scanned"
    if not parser_capabilities()["ocr"]:
        assert any("ocr_unavailable" in w for w in parsed.warnings)


# ---------------------------------------------------------------------------
# 真实解析器：docx（python-docx 生成→解析，含标题层级与表格）
# ---------------------------------------------------------------------------
def test_parse_real_docx_with_heading_and_table():
    docx_module = pytest.importorskip("docx")
    import io

    d = docx_module.Document()
    d.add_heading("装配工艺", level=1)
    d.add_paragraph("车架装配采用扭矩扳手校准。")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "工序"
    table.cell(0, 1).text = "标准"
    table.cell(1, 0).text = "装配"
    table.cell(1, 1).text = "12Nm"
    buf = io.BytesIO()
    d.save(buf)
    parsed = parse_bytes("asm.docx", "docx", buf.getvalue())
    texts = "\n".join(b.content for b in parsed.blocks if b.kind == "text")
    tables = "\n".join(b.content for b in parsed.blocks if b.kind == "table")
    assert "扭矩扳手" in texts
    assert "12Nm" in tables
    chunks = chunk_document("dx1", parsed)
    assert any(c.chunk_type == "table" for c in chunks)
    assert any(c.chunk_type == "parent" for c in chunks)


# ---------------------------------------------------------------------------
# API 全链路（真实 app + SQLite 存储）
# ---------------------------------------------------------------------------
def test_ingest_markdown_full_flow(tmp_path):
    client = _client(tmp_path)
    body = {
        "source_name": "工艺.md",
        "source_type": "md",
        "tenant_id": "group",
        "content_b64": _b64(
            "# 电池工艺\nTTFAR 电池采用石墨烯技术。\n"
            "| 项目 | 标准 |\n|---|---|\n| 电压 | 48V |\n"
        ),
    }
    resp = client.post("/documents/ingest", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "indexed"
    assert data["chunks"] >= 3
    doc_id = data["doc_id"]

    detail = client.get(f"/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json()["source_type"] == "md"

    chunks = client.get(f"/documents/{doc_id}/chunks")
    assert chunks.status_code == 200
    types = {item["chunk_type"] for item in chunks.json()["items"]}
    assert {"parent", "text", "table"} <= types

    tables = client.get(f"/documents/{doc_id}/chunks?chunk_type=table")
    assert tables.json()["count"] == 1
    assert "48V" in tables.json()["items"][0]["content"]

    listing = client.get("/documents")
    assert listing.json()["count"] == 1


def test_ingest_real_pdf_via_api(tmp_path):
    client = _client(tmp_path)
    body = {
        "source_name": "spec.pdf",
        "source_type": "pdf",
        "content_b64": base64.b64encode(_make_real_pdf()).decode("ascii"),
    }
    resp = client.post("/documents/ingest", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pages"] == 1
    assert data["chunks"] >= 1
    assert data["capabilities"]["pdf"] is True


def test_ingest_idempotent_same_content(tmp_path):
    client = _client(tmp_path)
    body = {
        "source_name": "same.md",
        "source_type": "md",
        "content_b64": _b64("# 标题\n内容一致。"),
    }
    first = client.post("/documents/ingest", json=body).json()
    second = client.post("/documents/ingest", json=body).json()
    assert first["doc_id"] == second["doc_id"]
    assert second["idempotent"] is True


def test_ingest_rejects_bad_base64_and_unknown_type(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/documents/ingest",
        json={"source_name": "x.md", "source_type": "md", "content_b64": "!!!not-b64"},
    )
    assert resp.status_code == 400
    resp2 = client.post(
        "/documents/ingest",
        json={"source_name": "x.exe", "source_type": "exe", "content_b64": _b64("xx")},
    )
    assert resp2.status_code == 400


def test_document_not_found_404(tmp_path):
    client = _client(tmp_path)
    assert client.get("/documents/nonexistent").status_code == 404
    assert client.get("/documents/nonexistent/chunks").status_code == 404


def test_document_delete_flow(tmp_path):
    client = _client(tmp_path)
    body = {
        "source_name": "del.md",
        "source_type": "md",
        "content_b64": _b64("# 删除\n内容"),
    }
    doc_id = client.post("/documents/ingest", json=body).json()["doc_id"]
    resp = client.delete(f"/documents/{doc_id}")
    assert resp.status_code == 200
    assert client.get(f"/documents/{doc_id}").json()["status"] == "deleted"
    assert client.get(f"/documents/{doc_id}/chunks").json()["count"] == 0


# ---------------------------------------------------------------------------
# 覆盖率补充：解析器缺失降级 / 坏输入 / 表格序列化边界
# ---------------------------------------------------------------------------
def test_real_docx_generated_and_table_parsing():
    docx_module = pytest.importorskip("docx")
    import io

    d = docx_module.Document()
    table = d.add_table(rows=3, cols=3)
    for r in range(3):
        for c in range(3):
            table.cell(r, c).text = f"r{r}c{c}"
    buf = io.BytesIO()
    d.save(buf)
    parsed = parse_bytes("t3.docx", "docx", buf.getvalue())
    tables = [b for b in parsed.blocks if b.kind == "table"]
    assert len(tables) == 1
    assert "r2c2" in tables[0].content
    assert tables[0].metadata.get("rows") == 3


def test_real_pptx_generated_and_slides():
    pptx_module = pytest.importorskip("pptx")
    import io

    prs = pptx_module.Presentation()
    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = "产线介绍"
    body = slide.placeholders[1]
    body.text = "整车装配包含电池检测工序"
    tbl_frame = slide.shapes.add_table(2, 2, 0, 0, 100, 60).table
    tbl_frame.cell(0, 0).text = "工序"
    tbl_frame.cell(0, 1).text = "节拍"
    tbl_frame.cell(1, 0).text = "装配"
    tbl_frame.cell(1, 1).text = "45s"
    buf = io.BytesIO()
    prs.save(buf)
    parsed = parse_bytes("line.pptx", "pptx", buf.getvalue())
    joined = "\n".join(b.content for b in parsed.blocks if b.kind == "text")
    tables = "\n".join(b.content for b in parsed.blocks if b.kind == "table")
    assert "产线介绍" in joined and "整车装配" in joined
    assert "45s" in tables
    chunks = chunk_document("ppt1", parsed)
    assert any(c.chunk_type == "table" for c in chunks)


def test_corrupted_docx_raises_valueerror():
    pytest.importorskip("docx")
    with pytest.raises(ValueError, match="docx_parse_failed"):
        parse_bytes("bad.docx", "docx", b"PK\x03\x04 not really a zip")


def test_corrupted_pptx_raises_valueerror():
    pytest.importorskip("pptx")
    with pytest.raises(ValueError, match="pptx_parse_failed"):
        parse_bytes("bad.pptx", "pptx", b"PK\x03\x04 garbage")


def test_empty_table_rows_dropped():
    from enterprise_ekb.document_pipeline import _serialize_table

    assert _serialize_table([["", ""], [None, None]]) == ""
    assert _serialize_table([]) == ""
    out = _serialize_table([["a"]])
    assert out.startswith("| a |")


def test_hard_split_short_text_passthrough():
    from enterprise_ekb.document_pipeline import _hard_split

    assert _hard_split("短文本") == ["短文本"]
    # 超长 CJK 切分不丢字符
    long_text = "电" * 2000
    parts = _hard_split(long_text)
    assert sum(len(p) for p in parts) == 2000


def test_needs_ocr_flag_on_textless_pdf():
    # 无文本层 PDF（构造空页）触发 needs_ocr 判定
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()
    parsed = parse_bytes("scan.pdf", "pdf", payload)
    if not parser_capabilities()["ocr"]:
        assert any("ocr_unavailable" in w for w in parsed.warnings)
    else:
        assert parsed.needs_ocr
