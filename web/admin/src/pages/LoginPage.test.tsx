import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "./LoginPage";
import { clearToken, getToken } from "../api";

// 本环境 window.sessionStorage 是访问器属性且 tinyspy 无法在实例上拦截；
// 按任务要求用内存 mock 替换（window.sessionStorage configurable:true，可覆写）。
function installSessionStorageMock() {
  const store = new Map<string, string>();
  const calls: string[][] = [];
  const mock = {
    getItem: (k: string) => (store.has(k) ? (store.get(k) as string) : null),
    setItem: (k: string, v: string) => {
      calls.push([k, v]);
      store.set(k, String(v));
    },
    removeItem: (k: string) => {
      calls.push([k, null as unknown as string]);
      store.delete(k);
    },
    clear: () => store.clear(),
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size;
    },
  };
  Object.defineProperty(window, "sessionStorage", { value: mock, configurable: true, writable: true });
  return { store, calls };
}

describe("LoginPage", () => {
  beforeEach(() => {
    clearToken();
    installSessionStorageMock();
  });

  it("submits trimmed token to sessionStorage (ekb.admin.token) and calls onSuccess", async () => {
    const { store, calls } = installSessionStorageMock();
    const onSuccess = vi.fn();
    render(<LoginPage onSuccess={onSuccess} />);

    expect(screen.getByText("雅迪 EKB 管理台")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "运行健康" })).toBeNull();

    await userEvent.type(screen.getByLabelText("管理 Token"), "  tok-123  ");
    await userEvent.click(screen.getByRole("button", { name: "进入控制台" }));

    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(calls).toContainEqual(["ekb.admin.token", "tok-123"]);
    expect(store.get("ekb.admin.token")).toBe("tok-123");
    expect(getToken()).toBe("tok-123");
  });

  it("blocks empty submit with an inline error and does not store a token", async () => {
    const { store } = installSessionStorageMock();
    const onSuccess = vi.fn();
    render(<LoginPage onSuccess={onSuccess} />);
    await userEvent.click(screen.getByRole("button", { name: "进入控制台" }));

    expect(screen.getByRole("alert").textContent).toBe("请输入 Token");
    expect(onSuccess).not.toHaveBeenCalled();
    expect(store.has("ekb.admin.token")).toBe(false);
    expect(getToken()).toBe("");
  });
});
