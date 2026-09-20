import { createElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { getLocale, setLocale, t } from "./i18n";

const STORAGE_KEY = "ekb.admin.locale";

// Node 26 / vitest jsdom 环境默认不提供 localStorage（需 --localstorage-file）。
// 在模块加载前安装内存桩，保证 i18n 的持久化路径可被验证。
vi.hoisted(() => {
  const g = globalThis as unknown as { localStorage?: Storage };
  if (typeof g.localStorage === "undefined") {
    const store = new Map<string, string>();
    const shim = {
      getItem: (k: string) => (store.has(k) ? (store.get(k) as string) : null),
      setItem: (k: string, v: string) => { store.set(k, String(v)); },
      removeItem: (k: string) => { store.delete(k); },
      clear: () => { store.clear(); },
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      get length() { return store.size; },
    };
    Object.defineProperty(globalThis, "localStorage", { value: shim, configurable: true, writable: true });
  }
});

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.setItem("ekb.admin.token", "test-token");
  setLocale("zh-CN");
});

describe("i18n core", () => {
  it("defaults to zh-CN and t() returns Chinese", async () => {
    // 清空存储并重新加载模块，验证真正的默认行为
    window.localStorage.removeItem(STORAGE_KEY);
    vi.resetModules();
    const fresh = await import("./i18n");
    expect(fresh.getLocale()).toBe("zh-CN");
    expect(fresh.t("app.title")).toBe("雅迪 EKB 管理台");
    expect(fresh.t("tab.health")).toBe("运行健康");
    expect(fresh.t("status.loading")).toBe("加载中…");
    expect(fresh.t("status.placeholder")).toBe("—");
  });

  it("returns English after setLocale('en') and persists to localStorage", () => {
    setLocale("en");
    expect(getLocale()).toBe("en");
    expect(t("app.title")).toBe("EKB Admin");
    expect(t("tab.health")).toBe("Runtime Health");
    expect(t("status.requestError")).toBe("Request Error");
    expect(t("button.auditQuery")).toBe("Query");
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("en");
  });

  it("restores a previously stored locale on load", async () => {
    window.localStorage.setItem(STORAGE_KEY, "en");
    vi.resetModules();
    const fresh = await import("./i18n");
    expect(fresh.getLocale()).toBe("en");
  });

  it("interpolates params into translated text", () => {
    expect(t("message.skillsPromoted", { skill: "ui-skill-1" })).toBe("ui-skill-1 已晋级 production ✅");
    setLocale("en");
    expect(t("message.skillsPromoted", { skill: "ui-skill-1" })).toBe("ui-skill-1 promoted to production ✅");
  });
});

describe("App language switch", () => {
  it("renders Chinese title by default and shows English title after clicking the language button", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    render(createElement(App));
    expect(screen.getByText("雅迪 EKB 管理台")).toBeTruthy();
    expect(screen.getByRole("button", { name: "运行健康" })).toBeTruthy();

    await userEvent.click(screen.getByLabelText("切换语言"));

    expect(screen.getByText("EKB Admin")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Runtime Health" })).toBeTruthy();
    expect(screen.getByLabelText("Switch language")).toBeTruthy();
  });
});
