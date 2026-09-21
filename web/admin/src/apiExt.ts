// P1-⑤ 扩展 API 客户端：industrial / documents / retrieval / graph 端点。
// 独立新增模块（不改动既有 api.ts）：复用其 Token 管理，401 时清 Token 并抛错。
import { clearToken, getToken } from "./api";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function callExt<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init?.headers as any) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (resp.status === 401) {
    clearToken();
    throw new Error("401 Unauthorized");
  }
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body?.detail ?? `${resp.status}`);
  return body as T;
}

// ---------- P1-⑤ 工业看板契约 ----------

export interface IndustrialOee {
  value: number | null;
  components: { availability: number; performance: number | null; quality: number };
  proxy_for: string;
  basis: string;
}

export interface IndustrialKpiPanel {
  generated_at: string;
  window: { source: string; limit: number; records: number };
  overall: {
    records: number;
    oee: IndustrialOee;
    first_pass_yield: { value: number; accepted: number; total: number; proxy_for: string; basis: string };
    defect_distribution: { items: { reason: string; count: number; ratio: number }[]; rejected: number; total: number; proxy_for: string; basis: string };
    energy_proxy: { events_per_hour: number; total_events: number; window_hours: number; proxy_for: string; basis: string };
  };
  tenants: Record<string, { records: number; oee: IndustrialOee }>;
  unavailable: string[];
}

export interface TimeSeriesPoint {
  ts: string;
  value: number;
}

export interface IndustrialTimeSeries {
  metric: string;
  hours: number;
  bucket_seconds: number;
  points: TimeSeriesPoint[];
  basis?: string;
}

// ---------- 文档契约（后端 /documents/* 由主线程接线） ----------

export interface DocumentItem {
  doc_id?: string;
  id?: string;
  source_name: string;
  source_type?: string;
  tenant_id?: string;
  status?: string;
  page_count?: number;
  pages?: number;
  chunk_count?: number;
  chunks?: number;
  created_at?: string;
  [key: string]: unknown;
}

export interface ChunkItem {
  seq: number;
  chunk_type: string;
  content: string;
  tokens?: number;
}

export interface HybridSearchResult {
  items: { id: string; score: number; title?: string | null }[];
  legs: Record<string, number>;
  degraded: boolean;
}

export interface GraphData {
  nodes: { id: string; label?: string }[];
  edges: { source: string; target: string; relation_type?: string }[];
}

export interface GraphSearchResult {
  keyword: string;
  results: { entity: string; type: string; mentions: number; relations?: number }[];
}

export interface GraphNeighborsResult {
  entity: string;
  hops: number;
  nodes: { entity: string; type?: string }[];
  edges: { source: string; target: string; relation?: string }[];
  [key: string]: unknown;
}

function b64EncodeUtf8(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary);
}

export const apiExt = {
  industrialKpis: () => callExt<IndustrialKpiPanel>("/industrial/kpis"),
  industrialTimeseries: (metric: string, hours: number) =>
    callExt<IndustrialTimeSeries>(`/industrial/timeseries?metric=${encodeURIComponent(metric)}&hours=${hours}`),

  documentsList: () => callExt<{ items: DocumentItem[] }>("/documents"),
  documentChunks: (docId: string) => callExt<{ items: ChunkItem[] }>(`/documents/${encodeURIComponent(docId)}/chunks`),
  documentIngest: (payload: { source_name: string; source_type: string; tenant_id: string; content_b64: string }) =>
    callExt<{ doc_id: string; status: string; chunks: number }>("/documents/ingest", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  knowledgeSearch: (payload: { query: string; top_k: number }) =>
    callExt<HybridSearchResult>("/retrieval/hybrid", { method: "POST", body: JSON.stringify(payload) }),

  graphSearch: (keyword: string) => callExt<GraphSearchResult>(`/graph/search?keyword=${encodeURIComponent(keyword)}`),
  graphNeighbors: (entity: string, hops = 1) =>
    callExt<GraphNeighborsResult>(`/graph/neighbors?entity=${encodeURIComponent(entity)}&hops=${hops}`),
  graphStats: () => callExt<{ nodes: number; edges: number }>("/graph/stats"),
};

export { b64EncodeUtf8 };
