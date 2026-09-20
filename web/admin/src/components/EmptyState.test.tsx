import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders illustration, title and description", () => {
    const { container } = render(<EmptyState title="暂无数据" description="试试刷新" />);
    expect(screen.getByTestId("empty-state")).toBeTruthy();
    expect(screen.getByText("暂无数据")).toBeTruthy();
    expect(screen.getByText("试试刷新")).toBeTruthy();
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("renders optional CTA and fires onAction", async () => {
    const onAction = vi.fn();
    render(<EmptyState title="暂无数据" actionLabel="重新加载" onAction={onAction} />);
    await userEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("renders no button without CTA props", () => {
    render(<EmptyState title="暂无数据" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
