// P0-②/P1-⑤⑥⑦ 新页面渲染冒烟测试：mock apiExt，验证关键 UI 元素出现。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../apiExt", () => ({
  b64EncodeUtf8: (t: string) => Buffer.from(t, "utf-8").toString("base64"),
  apiExt: {
    industrialKpis: vi.fn().mockResolvedValue({
      generated_at: "t",
      window: { source: "recent_audits", limit: 100, records: 0 },
      overall: {
        records: 0,
        oee: { value: 0, components: { availability: 0, performance: null, quality: 0 }, proxy_for: "equipment_oee", basis: "b" },
        first_pass_yield: { value: 0, accepted: 0, total: 0, proxy_for: "pfy", basis: "b" },
        defect_distribution: { items: [{ reason: "bad", count: 3, ratio: 1 }], rejected: 3, total: 9, proxy_for: "pareto", basis: "b" },
        energy_proxy: { events_per_hour: 1.5, total_events: 36, window_hours: 24, proxy_for: "energy", basis: "b" },
      },
      tenants: {},
      unavailable: [],
    }),
    industrialTimeseries: vi.fn().mockResolvedValue({ metric: "audit_events", hours: 24, bucket_seconds: 60, points: [] }),
    documentsList: vi.fn().mockResolvedValue({ items: [{ doc_id: "d1", source_name: "工艺.md", source_type: "md", status: "indexed", page_count: 1, chunk_count: 3 }] }),
    documentChunks: vi.fn().mockResolvedValue({ items: [{ seq: 0, chunk_type: "text", content: "hello", tokens: 1 }] }),
    knowledgeSearch: vi.fn().mockResolvedValue({ items: [{ id: "capability:x", score: 0.8, title: "TTFAR 电池工艺" }], legs: { lexical: 1 }, degraded: false }),
    graphSearch: vi.fn().mockResolvedValue({ keyword: "TTFAR", results: [{ entity: "TTFAR", type: "通用", mentions: 1 }] }),
    graphNeighbors: vi.fn().mockResolvedValue({
      entity: "TTFAR", hops: 1,
      nodes: [{ entity: "TTFAR", type: "通用" }, { entity: "电池产线", type: "设备" }],
      edges: [{ source: "TTFAR", target: "电池产线", relation: "co_occurs" }],
    }),
    graphStats: vi.fn().mockResolvedValue({ nodes: 2, edges: 1 }),
  },
}));

import { Documents } from "./Documents";
import { KnowledgeSearch } from "./KnowledgeSearch";
import { GraphExplorer } from "./GraphExplorer";
import { IndustrialDashboard } from "./IndustrialDashboard";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Documents page", () => {
  it("lists documents from backend", async () => {
    render(<Documents />);
    await waitFor(() => expect(screen.getByText(/工艺\.md/)).toBeTruthy());
  });
});

describe("KnowledgeSearch page", () => {
  it("renders results with highlight after search", async () => {
    const user = userEvent.setup();
    render(<KnowledgeSearch />);
    await user.type(screen.getByLabelText("search-query"), "TTFAR");
    await user.click(screen.getByText("检索"));
    await waitFor(() => expect(screen.getByText(/结果 1 条/)).toBeTruthy());
  });
});

describe("GraphExplorer page", () => {
  it("expands neighbors after search", async () => {
    const user = userEvent.setup();
    render(<GraphExplorer />);
    await user.type(screen.getByLabelText("graph-keyword"), "TTFAR");
    await user.click(screen.getByText("探索"));
    await waitFor(() => expect(screen.getByText(/命中实体（1）/)).toBeTruthy());
  });
});

describe("IndustrialDashboard page", () => {
  it("renders KPI cards with proxy basis", async () => {
    render(<IndustrialDashboard />);
    await waitFor(() => {
      expect(screen.getByText(/设备 OEE/)).toBeTruthy();
      expect(screen.getByText(/缺陷帕累托/)).toBeTruthy();
      expect(screen.getByText(/口径说明/)).toBeTruthy();
    });
  });
});
