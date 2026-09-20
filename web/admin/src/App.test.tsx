import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Card } from "./components/Card";
import { StatusDot } from "./components/StatusDot";
import { clearToken } from "./api";
import App from "./App";

const TOKEN_KEY = "ekb.admin.token";

beforeEach(() => {
  clearToken();
  window.sessionStorage.setItem(TOKEN_KEY, "test-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Card", () => {
  it("renders title and children", () => {
    render(<Card title="运行健康">hello</Card>);
    expect(screen.getByText("运行健康")).toBeTruthy();
    expect(screen.getByText("hello")).toBeTruthy();
  });
});

describe("StatusDot", () => {
  it("marks ok and degraded states", () => {
    const ok = render(<StatusDot ok label="ready" />);
    expect(ok.getByText("ready")).toBeTruthy();
  });
});

describe("App theme toggle", () => {
  it("flips data-theme on click", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    render(<App />);
    const btn = screen.getByLabelText("切换主题");
    await userEvent.click(btn);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    await userEvent.click(btn);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});

describe("App auth gate (B-3)", () => {
  it("shows the login page when no token is stored", () => {
    window.sessionStorage.clear();
    render(<App />);
    expect(screen.getByRole("button", { name: "进入控制台" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "运行健康" })).toBeNull();
  });

  it("enters the console after a successful login submit", async () => {
    window.sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    render(<App />);
    await userEvent.type(screen.getByLabelText("管理 Token"), "abc");
    await userEvent.click(screen.getByRole("button", { name: "进入控制台" }));
    expect(await screen.findByRole("button", { name: "运行健康" })).toBeTruthy();
  });
});

describe("App 401 handling (B-3)", () => {
  it("clears the token and returns to the login page when an API call returns 401", async () => {
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBe("test-token");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 401, json: async () => ({ detail: "unauthorized" }) }))
    );
    render(<App />);
    // 初始 readyz 收到 401 → 清空 Token → 回到登录页
    expect(await screen.findByRole("button", { name: "进入控制台" })).toBeTruthy();
    expect(window.sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});

const capacityResult = {
  estimated_qps: 1200,
  estimated_llm_qps: 300,
  estimated_heavy_llm_qps: 90,
  recommended_a100_80g: 2,
  estimated_cross_region_qps: 60,
  estimated_failover_peak_qps: 1380,
  recommended_gateway_vcpu: 16,
  recommended_control_plane_vcpu: 8,
};

const auditResult = {
  count: 2,
  items: [
    { id: 1, created_at: "2026-09-20T10:00:00", tenant_id: "group", skill: "s-a:1.0.0", tool: "tool-a", decision_reason: "allow:low-risk", accepted: true },
    { id: 2, created_at: "2026-09-20T10:01:00", tenant_id: "group", skill: "s-b:2.0.0", tool: "tool-b", decision_reason: "deny:policy", accepted: false },
  ],
};

function stubApi(overrides: Record<string, unknown> = {}) {
  return vi.fn(async (input: unknown) => {
    const url = String(input);
    if (url.includes("/capacity/estimate")) {
      return { ok: true, status: 200, json: async () => overrides.capacity ?? capacityResult };
    }
    if (url.includes("/audit/query")) {
      return { ok: true, status: 200, json: async () => overrides.audit ?? auditResult };
    }
    if (url.includes("/metrics")) {
      return { ok: true, status: 200, text: async () => "# HELP ekb_test mock\n" };
    }
    return { ok: true, status: 200, json: async () => ({ status: "ready", event_publisher_backend: "memory", outbox: { pending: 0, published: 3 } }) };
  });
}

describe("App capacity tab (B-4/B-5)", () => {
  it("shows metric cards, bar chart and a success toast after estimating", async () => {
    vi.stubGlobal("fetch", stubApi());
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "容量估算" }));
    await userEvent.click(screen.getByRole("button", { name: "按默认基线估算（10 万在线）" }));

    expect(await screen.findByTestId("toast-success")).toBeTruthy();
    expect(screen.getByText("容量估算完成")).toBeTruthy();
    expect(screen.getAllByTestId("metric-card")).toHaveLength(4);
    expect(screen.getAllByText("1200").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("hbars")).toBeTruthy();
  });

  it("shows an error toast when the estimate request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("boom"))));
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "容量估算" }));
    await userEvent.click(screen.getByRole("button", { name: "按默认基线估算（10 万在线）" }));

    expect(await screen.findByTestId("toast-error")).toBeTruthy();
    expect(screen.queryByText("容量估算完成")).toBeNull();
  });
});

describe("App audit tab (B-1)", () => {
  it("renders audit records in the DataTable with colored accepted marks", async () => {
    vi.stubGlobal("fetch", stubApi());
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "审计查询" }));

    expect(await screen.findByRole("columnheader", { name: "租户" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "tool-a" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "tool-b" })).toBeTruthy();
    expect(screen.getByText("✓").className).toBe("dt-ok");
    expect(screen.getByText("✗").className).toBe("dt-bad");
  });

  it("shows the empty state when there are no audit records", async () => {
    vi.stubGlobal("fetch", stubApi({ audit: { count: 0, items: [] } }));
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "审计查询" }));

    expect(await screen.findByTestId("empty-state")).toBeTruthy();
    expect(screen.getByText("暂无审计记录")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
