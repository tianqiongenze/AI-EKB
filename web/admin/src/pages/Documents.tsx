// 文档管理页（P0-② 前端）：上传→解析状态→chunk 展开。
import { useCallback, useEffect, useState } from "react";
import { apiExt, b64EncodeUtf8, type ChunkItem, type DocumentItem } from "../apiExt";
import { Card } from "../components/Card";
import { DataTable, type DataTableColumn } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import { buttonStyle, inputStyle } from "../components/styles";

const SOURCE_TYPE_OPTIONS = ["md", "txt", "pdf", "docx", "pptx", "csv", "json"];

export function Documents() {
  const [items, setItems] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceType, setSourceType] = useState("md");
  const [fileText, setFileText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems((await apiExt.documentsList()).items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const upload = async () => {
    if (!sourceName.trim() || !fileText.trim()) {
      setUploadMsg("请填写文档名并粘贴内容");
      return;
    }
    setUploading(true);
    setUploadMsg("");
    try {
      const resp = await apiExt.documentIngest({
        source_name: sourceName,
        source_type: sourceType,
        tenant_id: "group",
        content_b64: b64EncodeUtf8(fileText),
      });
      setUploadMsg(`✓ 已索引：${resp.chunks} 个分块（${resp.status}）`);
      await refresh();
    } catch (e) {
      setUploadMsg(`✗ ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
  };

  const toggleChunks = async (docId: string) => {
    if (expandedDoc === docId) {
      setExpandedDoc(null);
      return;
    }
    setExpandedDoc(docId);
    setChunksLoading(true);
    try {
      setChunks((await apiExt.documentChunks(docId)).items ?? []);
    } catch {
      setChunks([]);
    } finally {
      setChunksLoading(false);
    }
  };

  const columns: DataTableColumn<DocumentItem>[] = [
    { key: "source_name", label: "文档名" },
    { key: "source_type", label: "类型", width: 80 },
    { key: "status", label: "状态", width: 90 },
    { key: "page_count", label: "页数", width: 70 },
    { key: "chunk_count", label: "分块", width: 70 },
    {
      key: "ops",
      label: "操作",
      width: 90,
      render: (row) => (
        <button
          style={buttonStyle}
          onClick={() => toggleChunks(row.doc_id ?? row.id ?? "")}
          aria-label={`chunks-${row.doc_id ?? row.id}`}
        >
          分块
        </button>
      ),
    },
  ];

  return (
    <div>
      <Card title="上传文档 / Ingest">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input
            style={{ ...inputStyle, maxWidth: 220 }}
            placeholder="文档名（如 电池工艺.md）"
            value={sourceName}
            onChange={(e) => setSourceName(e.target.value)}
            aria-label="doc-name"
          />
          <select value={sourceType} onChange={(e) => setSourceType(e.target.value)} aria-label="doc-type">
            {SOURCE_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button style={buttonStyle} onClick={upload} disabled={uploading}>
            {uploading ? "解析中…" : "上传并解析"}
          </button>
        </div>
        <textarea
          style={{ ...inputStyle, marginTop: 8, minHeight: 90, fontFamily: "monospace" }}
          placeholder="粘贴文档内容（文本类）…"
          value={fileText}
          onChange={(e) => setFileText(e.target.value)}
          aria-label="doc-content"
        />
        {uploadMsg && <p style={{ margin: "8px 0 0" }}>{uploadMsg}</p>}
      </Card>

      <Card title={`文档列表（${items.length}）`}>
        {loading ? (
          <Skeleton rows={4} />
        ) : error ? (
          <EmptyState title="加载失败" description={error} />
        ) : items.length === 0 ? (
          <EmptyState title="暂无文档" description="上传第一份知识文档" />
        ) : (
          <DataTable columns={columns} rows={items} />
        )}
      </Card>

      {expandedDoc && chunksLoading && <Skeleton rows={3} />}
      {expandedDoc && !chunksLoading && (
        <Card title={`分块明细（${chunks.length}）`}>
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {chunks.map((c) => (
              <li key={c.seq} style={{ padding: "8px 0", borderBottom: "1px solid var(--color-border)" }}>
                <span
                  style={{
                    fontSize: 11,
                    padding: "1px 6px",
                    borderRadius: 4,
                    background: c.chunk_type === "table" ? "#e6f7ff" : c.chunk_type === "parent" ? "#f6ffed" : "#f5f5f5",
                    marginRight: 8,
                  }}
                >
                  {c.chunk_type}
                </span>
                <span style={{ fontSize: 11, color: "#888" }}>#{c.seq} · {c.tokens ?? "-"} tokens</span>
                <div style={{ fontSize: 12, marginTop: 4, whiteSpace: "pre-wrap", maxHeight: 80, overflow: "hidden" }}>
                  {c.content.slice(0, 300)}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
