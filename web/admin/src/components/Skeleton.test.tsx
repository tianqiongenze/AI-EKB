import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Skeleton } from "./Skeleton";

describe("Skeleton", () => {
  it("renders 3 shimmer bars by default with status role", () => {
    const { container } = render(<Skeleton />);
    expect(screen.getByTestId("skeleton")).toBeTruthy();
    expect(screen.getByRole("status")).toBeTruthy();
    expect(container.querySelectorAll(".skeleton-bar")).toHaveLength(3);
  });

  it("renders a custom number of bars", () => {
    const { container } = render(<Skeleton rows={5} />);
    expect(container.querySelectorAll(".skeleton-bar")).toHaveLength(5);
  });

  it("exposes a localized aria-label", () => {
    render(<Skeleton label="加载中" />);
    expect(screen.getByRole("status", { name: "加载中" })).toBeTruthy();
  });
});
