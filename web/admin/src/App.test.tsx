import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Card } from "./components/Card";
import { StatusDot } from "./components/StatusDot";
import App from "./App";

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
