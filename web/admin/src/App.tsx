import { useCallback, useEffect, useRef, useState } from "react";
import { api, hasToken, setUnauthorizedHandler, type AuditRecord, type CapacityEstimate } from "./api";
import { WorkshopScreen } from "./pages/WorkshopScreen";
import { LoginPage } from "./pages/LoginPage";
import { Card } from "./components/Card";
import { StatusDot } from "./components/StatusDot";
import { JsonView } from "./components/JsonView";
import { DataTable, type DataTableColumn } from "./components/DataTable";
import { Skeleton } from "./components/Skeleton";
import { EmptyState } from "./components/EmptyState";
import { Logo } from "./components/Logo";
import { MetricCard } from "./components/MetricCard";
import { Bars } from "./components/Bars";
import { ToastStack, type ToastItem, type ToastKind } from "./components/Toast";
import { buttonStyle, toolbarButtonStyle } from "./components/styles";
import { getLocale, setLocale, t, type Locale, type TranslationKey } from "./i18n";

type Tab = "health" | "capacity" | "skills" | "audit" | "workshop";

const tabs: { key: Tab; labelKey: TranslationKey }[] = [
  { key: "health", labelKey: "tab.health" },
  { key: "capacity", labelKey: "tab.capacity" },
  { key: "skills", labelKey: "tab.skills" },
  { key: "audit", labelKey: "tab.audit" },
  { key: "workshop", labelKey: "tab.workshop" },
];

// B-1 审计列：accepted 用 ✓/✗ 着色；列文案走 i18n（每次渲染取当前语言）。
function auditColumns(): DataTableColumn<AuditRecord>[] {
  return [
    { key: "created_at", label: t("audit.col.time"), width: 170 },
    { key: "tenant_id", label: t("audit.col.tenant"), width: 90 },
    { key: "skill", label: t("audit.col.skill") },
    { key: "tool", label: t("audit.col.tool") },
    { key: "decision_reason", label: t("audit.col.decision") },
    {
      key: "accepted",
      label: t("audit.col.accepted"),
      width: 70,
      render: (row) =>
        row.accepted ? <span className="dt-ok">✓</span> : <span className="dt-bad">✗</span>,
    },
  ];
}

export default function App() {
  // B-3 鉴权门：无 Token 显示登录页；401 时 api.ts 回调清空并回到登录页。
  const [authed, setAuthed] = useState(() => hasToken());
  const [tab, setTab] = useState<Tab>("health");
  const [error, setError] = useState("");
  const [healthLoading, setHealthLoading] = useState(true);
  const [ready, setReady] = useState<Awaited<ReturnType<typeof api.readyz>> | null>(null);
  const [metrics, setMetrics] = useState("");
  const [capLoading, setCapLoading] = useState(false);
  const [capResult, setCapResult] = useState<CapacityEstimate | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditItems, setAuditItems] = useState<AuditRecord[]>([]);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [locale, setLocaleState] = useState<Locale>(() => getLocale());
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const toastSeq = useRef(0);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthed(false));
    return () => setUnauthorizedHandler(null);
  }, []);

  // B-5 Toast：右上角轻通知，3s 自动消失（定时器在 Toast 组件内）。
  const pushToast = useCallback((kind: ToastKind, message: string) => {
    toastSeq.current += 1;
    const id = toastSeq.current;
    setToasts((prev) => [...prev, { id, kind, message }]);
  }, []);
  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  // 运行健康：登录后加载（未登录不发无谓的 401 请求）。
  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    setHealthLoading(true);
    (async () => {
      try {
        const r = await api.readyz();
        if (!cancelled) setReady(r);
        const m = await api.metrics();
        if (!cancelled) setMetrics(m);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setHealthLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authed]);

  // B-1/B-2 审计：进入页签自动查询，三态（loading/empty/data）。
  useEffect(() => {
    if (!authed || tab !== "audit") return;
    let cancelled = false;
    setAuditLoading(true);
    (async () => {
      try {
        const r = await api.auditQuery({ tenant_id: "group", limit: 10 });
        if (!cancelled) setAuditItems(r.items ?? []);
      } catch (e) {
        if (!cancelled) {
          setAuditItems([]);
          setError(String(e));
        }
      } finally {
        if (!cancelled) setAuditLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authed, tab]);

  const loadAudit = async (manual: boolean) => {
    setAuditLoading(true);
    try {
      const r = await api.auditQuery({ tenant_id: "group", limit: 10 });
      setAuditItems(r.items ?? []);
      if (manual) pushToast("success", t("toast.auditLoaded", { count: r.count ?? r.items?.length ?? 0 }));
    } catch (e) {
      pushToast("error", String(e));
    } finally {
      setAuditLoading(false);
    }
  };

  const runCapacity = async () => {
    setCapLoading(true);
    try {
      const r = await api.capacity({ online_users: 100000, active_ratio: 0.1, cache_hit_ratio: 0.5, complex_ratio: 0.3 });
      setCapResult(r);
      pushToast("success", t("toast.capacityDone"));
    } catch (e) {
      pushToast("error", String(e));
    } finally {
      setCapLoading(false);
    }
  };

  const runSkillsPromote = async () => {
    try {
      const manifest = { skill_name: `ui-skill-${Date.now() % 100000}`, version: "1.0.0", owner: "admin-ui", description: "从管理台注册", allowed_tools: ["tool-a"], allowed_domains: ["manufacturing"], residency_scope: ["cn-north-1"], risk_level: "low", changelog: "ui-created" };
      await api.skillsRegister(manifest);
      for (const stage of ["review", "staging", "production"]) {
        await api.skillsPromote({ skill_name: manifest.skill_name, version: manifest.version, target_stage: stage });
      }
      pushToast("success", t("message.skillsPromoted", { skill: manifest.skill_name }));
    } catch (e) {
      pushToast("error", String(e));
    }
  };

  const switchLocale = () => {
    const next: Locale = locale === "zh-CN" ? "en" : "zh-CN";
    setLocale(next);
    setLocaleState(next);
  };

  if (!authed) {
    return <LoginPage onSuccess={() => setAuthed(true)} />;
  }

  const outbox = ready?.outbox ?? {};
  const hasOutbox = Object.keys(outbox).length > 0;

  return (
    <div className="app-shell">
      <aside className="app-side">
        <div className="app-brand">
          <Logo size={28} />
          <h1 style={{ fontSize: "var(--typography-size-h1)", margin: 0 }}>{t("app.title")}</h1>
        </div>
        <div className="app-controls">
          <button
            aria-label={t("theme.toggle")}
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            style={toolbarButtonStyle}
          >
            {theme === "light" ? t("theme.dark") : t("theme.light")}
          </button>
          <button aria-label={t("header.language")} onClick={switchLocale} style={toolbarButtonStyle}>
            {locale === "zh-CN" ? "EN" : "中"}
          </button>
        </div>
        <div className="app-status">
          {ready && (
            <StatusDot
              ok={ready.status === "ready"}
              label={t("status.readyLabel", { status: ready.status, backend: ready.event_publisher_backend, pending: ready.outbox?.pending ?? 0 })}
            />
          )}
        </div>
        <nav className="app-nav" aria-label={t("app.title")}>
          {tabs.map((tabItem) => (
            <button
              key={tabItem.key}
              onClick={() => setTab(tabItem.key)}
              aria-current={tab === tabItem.key ? "page" : undefined}
              style={{
                ...buttonStyle,
                background: tab === tabItem.key ? "var(--color-brand-primary)" : "var(--color-surface-card)",
                color: tab === tabItem.key ? "#fff" : "var(--color-surface-text)",
                border: "1px solid var(--color-border)",
              }}
            >
              {t(tabItem.labelKey)}
            </button>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        {error && (
          <Card title={t("status.requestError")}>
            <p style={{ color: "var(--color-brand-danger)" }}>{error}</p>
          </Card>
        )}

        {tab === "health" && (
          <>
            <Card title={t("card.outbox")}>
              {healthLoading ? (
                <Skeleton />
              ) : hasOutbox ? (
                <JsonView value={outbox} />
              ) : (
                <EmptyState title={t("empty.outbox.title")} />
              )}
            </Card>
            <Card title={t("card.metrics")}>
              {healthLoading ? (
                <Skeleton rows={5} />
              ) : metrics ? (
                <pre style={{ whiteSpace: "pre-wrap", maxHeight: 320, overflow: "auto", margin: 0 }}>{metrics}</pre>
              ) : (
                <EmptyState title={t("empty.metrics.title")} />
              )}
            </Card>
          </>
        )}

        {tab === "capacity" && (
          <Card title={t("card.capacity")}>
            <button style={buttonStyle} disabled={capLoading} onClick={runCapacity}>
              {t("button.capacityEstimate")}
            </button>
            {capLoading ? (
              <div style={{ marginTop: "var(--space-3)" }}>
                <Skeleton />
              </div>
            ) : capResult ? (
              <>
                <div className="metric-grid">
                  <MetricCard label={t("capacity.metric.estimatedQps")} value={capResult.estimated_qps} />
                  <MetricCard label={t("capacity.metric.heavyLlmQps")} value={capResult.estimated_heavy_llm_qps} />
                  <MetricCard label={t("capacity.metric.a100")} value={capResult.recommended_a100_80g} unit={t("capacity.metric.gpuUnit")} />
                  <MetricCard label={t("capacity.metric.failoverPeak")} value={capResult.estimated_failover_peak_qps} />
                </div>
                <h3 className="chart-title">{t("capacity.chart.title")}</h3>
                <Bars
                  items={[
                    { label: t("capacity.bar.total"), value: capResult.estimated_qps },
                    { label: t("capacity.bar.llm"), value: capResult.estimated_llm_qps },
                    { label: t("capacity.bar.heavy"), value: capResult.estimated_heavy_llm_qps },
                    { label: t("capacity.bar.crossRegion"), value: capResult.estimated_cross_region_qps },
                    { label: t("capacity.bar.failoverPeak"), value: capResult.estimated_failover_peak_qps },
                  ]}
                />
              </>
            ) : (
              <EmptyState
                title={t("capacity.empty.title")}
                description={t("capacity.empty.desc")}
                actionLabel={t("capacity.empty.action")}
                onAction={runCapacity}
              />
            )}
          </Card>
        )}

        {tab === "skills" && (
          <Card title={t("card.skills")}>
            <button style={buttonStyle} onClick={runSkillsPromote}>
              {t("button.skillsPromote")}
            </button>
            <p style={{ marginTop: "var(--space-3)", color: "var(--color-surface-muted)" }}>{t("skills.hint")}</p>
          </Card>
        )}

        {tab === "workshop" && <WorkshopScreen />}

        {tab === "audit" && (
          <Card title={t("card.audit")}>
            <button style={buttonStyle} disabled={auditLoading} onClick={() => loadAudit(true)}>
              {t("button.auditQuery")}
            </button>
            <div style={{ marginTop: "var(--space-3)" }}>
              {auditLoading ? (
                <Skeleton />
              ) : (
                <DataTable
                  columns={auditColumns()}
                  rows={auditItems}
                  empty={
                    <EmptyState
                      title={t("audit.empty.title")}
                      description={t("audit.empty.desc")}
                      actionLabel={t("audit.empty.action")}
                      onAction={() => loadAudit(true)}
                    />
                  }
                />
              )}
            </div>
          </Card>
        )}
      </main>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
