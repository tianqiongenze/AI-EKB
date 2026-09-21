// 知识图谱探索页（P1-⑥ 前端）：关键词检索 + 多跳邻居 + 简化力导向 SVG（≤50 节点截断）。
import { useState } from "react";
import { apiExt, type GraphNeighborsResult, type GraphSearchResult } from "../apiExt";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import { buttonStyle, inputStyle } from "../components/styles";

const NODE_LIMIT = 50;

type GraphNode = { id: string; type?: string };
type GraphEdge = { source: string; target: string; relation?: string };

function circularLayout(nodes: GraphNode[], size = 420) {
  const cx = size / 2;
  const r = size / 2 - 40;
  return nodes.map((n, i) => {
    const angle = (i / Math.max(nodes.length, 1)) * 2 * Math.PI;
    return { ...n, x: cx + r * Math.cos(angle), y: cx + r * Math.sin(angle) };
  });
}

function GraphCanvas({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const truncated = nodes.length > NODE_LIMIT;
  const visible = nodes.slice(0, NODE_LIMIT);
  const ids = new Set(visible.map((n) => n.id));
  const visibleEdges = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const placed = circularLayout(visible);
  const pos = new Map(placed.map((n) => [n.id, n]));
  return (
    <div>
      {truncated && <p style={{ fontSize: 12, color: "#d46b08" }}>节点超过 {NODE_LIMIT}，仅展示前 {NODE_LIMIT} 个</p>}
      <svg width="100%" viewBox="0 0 420 420" role="img" aria-label="knowledge-graph">
        {visibleEdges.map((e, i) => {
          const a = pos.get(e.source);
          const b = pos.get(e.target);
          if (!a || !b) return null;
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="var(--color-border)"
              strokeDasharray={e.relation === "co_occurs" ? "4 3" : undefined}
            />
          );
        })}
        {placed.map((n) => (
          <g key={n.id}>
            <circle cx={n.x} cy={n.y} r={10} fill="var(--color-brand-primary, #1677ff)" opacity={0.85} />
            <text x={n.x} y={n.y - 14} textAnchor="middle" fontSize={10} fill="var(--color-surface-text)">
              {n.id.length > 12 ? `${n.id.slice(0, 12)}…` : n.id}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export function GraphExplorer() {
  const [keyword, setKeyword] = useState("");
  const [searchResult, setSearchResult] = useState<GraphSearchResult | null>(null);
  const [neighbors, setNeighbors] = useState<GraphNeighborsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const runSearch = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    setError("");
    try {
      const s = await apiExt.graphSearch(keyword);
      setSearchResult(s);
      setNeighbors(null);
      if ((s.results ?? []).length > 0) {
        setNeighbors(await apiExt.graphNeighbors((s.results as unknown as { entity: string }[])[0].entity, 1));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const expand = async (entity: string) => {
    setLoading(true);
    try {
      setNeighbors(await apiExt.graphNeighbors(entity, 1));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Card title="图谱探索 / Graph Explorer">
        <div style={{ display: "flex", gap: 8 }}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            value={keyword}
            placeholder="实体关键词，如：TTFAR / 电池 / 产线"
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            aria-label="graph-keyword"
          />
          <button style={buttonStyle} onClick={runSearch} disabled={loading || !keyword.trim()}>
            探索
          </button>
        </div>
      </Card>
      {loading && <Skeleton rows={4} />}
      {error && <EmptyState title="图谱查询失败" description={error} />}
      {searchResult && (
        <Card title={`命中实体（${searchResult.results?.length ?? 0}）`}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {(searchResult.results ?? []).map((r) => (
              <button
                key={r.entity}
                style={buttonStyle}
                onClick={() => expand(r.entity)}
                aria-label={`expand-${r.entity}`}
              >
                {r.entity} · {r.type ?? "?"}
              </button>
            ))}
          </div>
        </Card>
      )}
      {neighbors && (
        <Card title={`邻居子图 · ${neighbors.entity}（${neighbors.nodes?.length ?? 0} 节点）`}>
          <GraphCanvas
            nodes={(neighbors.nodes ?? []).map((n) => ({ id: n.entity, type: n.type }))}
            edges={neighbors.edges ?? []}
          />
        </Card>
      )}
    </div>
  );
}
