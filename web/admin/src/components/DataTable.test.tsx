import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTable } from "./DataTable";
import { setLocale } from "../i18n";

const rows = [
  { id: 1, name: "alpha", ok: true },
  { id: 2, name: "beta", ok: false },
];

describe("DataTable", () => {
  it("renders column headers and cell values (plain + render columns)", () => {
    render(
      <DataTable
        columns={[
          { key: "name", label: "名称" },
          { key: "ok", label: "结果", render: (r) => (r.ok ? <span className="dt-ok">✓</span> : <span className="dt-bad">✗</span>) },
        ]}
        rows={rows}
      />
    );
    expect(screen.getByRole("columnheader", { name: "名称" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "结果" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "alpha" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "beta" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "✓" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "✗" })).toBeTruthy();
    // 表头 + 2 数据行
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("sets title tooltip from raw cell values for overflow ellipsis", () => {
    render(<DataTable columns={[{ key: "name", label: "N" }]} rows={rows} />);
    expect(screen.getByRole("cell", { name: "alpha" }).getAttribute("title")).toBe("alpha");
  });

  it("renders EmptyState with default copy when rows are empty", () => {
    setLocale("zh-CN");
    render(<DataTable columns={[{ key: "name", label: "N" }]} rows={[]} />);
    expect(screen.getByTestId("empty-state")).toBeTruthy();
    expect(screen.getByText("暂无数据")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders a custom empty node when provided", () => {
    render(<DataTable columns={[{ key: "name", label: "N" }]} rows={[]} empty={<div data-testid="custom-empty">custom</div>} />);
    expect(screen.getByTestId("custom-empty")).toBeTruthy();
    expect(screen.getByText("custom")).toBeTruthy();
  });
});
