import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { ToastStack, TOAST_AUTO_DISMISS_MS, type ToastItem } from "./Toast";

describe("Toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders success and error toasts in a polite live region", () => {
    const toasts: ToastItem[] = [
      { id: 1, kind: "success", message: "估算完成" },
      { id: 2, kind: "error", message: "请求失败" },
    ];
    render(<ToastStack toasts={toasts} onDismiss={() => {}} />);
    const stack = screen.getByTestId("toast-stack");
    expect(stack.getAttribute("aria-live")).toBe("polite");
    expect(screen.getByTestId("toast-success").textContent).toContain("估算完成");
    expect(screen.getByTestId("toast-error").textContent).toContain("请求失败");
  });

  it("auto-dismisses after 3s and disappears once the parent removes it", async () => {
    const onDismiss = vi.fn();
    const toasts: ToastItem[] = [{ id: 7, kind: "success", message: "ok done" }];
    const { rerender } = render(<ToastStack toasts={toasts} onDismiss={onDismiss} />);
    expect(screen.getByText("ok done")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(TOAST_AUTO_DISMISS_MS);
    });
    expect(onDismiss).toHaveBeenCalledWith(7);

    // 父组件应用 dismiss 后条目消失
    rerender(<ToastStack toasts={[]} onDismiss={onDismiss} />);
    expect(screen.queryByText("ok done")).toBeNull();
  });

  it("keeps the toast visible before the 3s deadline", () => {
    const { rerender } = render(<ToastStack toasts={[{ id: 1, kind: "error", message: "wait" }]} onDismiss={() => {}} />);
    act(() => {
      vi.advanceTimersByTime(TOAST_AUTO_DISMISS_MS - 1);
    });
    rerender(<ToastStack toasts={[{ id: 1, kind: "error", message: "wait" }]} onDismiss={() => {}} />);
    expect(screen.getByText("wait")).toBeTruthy();
  });
});
