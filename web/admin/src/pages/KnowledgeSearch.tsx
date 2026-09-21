// 知识检索页（P0-③ 前端）：混合检索三腿结果 + 关键词高亮 + 腿来源徽标。
import { useState } from "react";
import { apiExt, type HybridSearchResult } from "../apiExt";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import { buttonStyle, inputStyle } from "../components/styles";

function highlight(text: string, query: string) {
  if (!query.trim()) return text;
  const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i} style={{ background: "var(--color-accent-bg, #ffe58f)", padding: "0 2px" }}>{part}</mark>
    ) : (
      part
    ),
  );
}

export function KnowledgeSearch() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<HybridSearchResult | null>(null);

  const search = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    try {
      setResult(await apiExt.knowledgeSearch({ query, top_k: 20 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Card title="知识检索 / Knowledge Search">
        <div style={{ display: "flex", gap: 8 }}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            value={query}
            placeholder="输入查询，如：TTFAR 电池 工艺"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            aria-label="search-query"
          />
          <button style={buttonStyle} onClick={search} disabled={loading || !query.trim()}>
            检索
          </button>
        </div>
      </Card>
      {loading && <Skeleton rows={4} />}
      {error && <EmptyState title="检索失败" description={error} />}
      {result && !loading && (
        <Card title={`结果 ${result.items?.length ?? 0} 条`}>
          {result.degraded && (
            <p style={{ color: "var(--color-warning, #d46b08)" }}>降级模式：部分检索腿不可用</p>
          )}
          {(result.items ?? []).length === 0 ? (
            <EmptyState title="无结果" description="换个关键词试试" />
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {(result.items ?? []).map((item) => (
                <li
                  key={item.id}
                  style={{
                    padding: "var(--space-3, 12px) 0",
                    borderBottom: "1px solid var(--color-border)",
                  }}
                >
                  <div style={{ fontWeight: 600 }}>
                    {highlight(item.title ?? item.id, query)}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--color-surface-text-secondary, #666)" }}>
                    score {item.score?.toFixed?.(4) ?? item.score} · {item.id.split(":")[0]}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
