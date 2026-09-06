import { useEffect, useState } from "react";
import { api } from "./api";
import { WorkshopScreen } from "./pages/WorkshopScreen";
import { Card } from "./components/Card";
import { StatusDot } from "./components/StatusDot";
import { JsonView } from "./components/JsonView";
import { getLocale, setLocale, t, type Locale, type TranslationKey } from "./i18n";

type Tab = "health" | "capacity" | "skills" | "audit" | "workshop";

const tabs: { key: Tab; labelKey: TranslationKey }[] = [
  { key: "health", labelKey: "tab.health" },
  { key: "capacity", labelKey: "tab.capacity" },
  { key: "skills", labelKey: "tab.skills" },
  { key: "audit", labelKey: "tab.audit" },
  { key: "workshop", labelKey: "tab.workshop" },
];

const inputStyle = { padding: "var(--space-2) var(--space-3)", borderRadius: "var(--radius-input)", border: "1px solid var(--color-border)", width: "100%", boxSizing: "border-box" } as const;
const buttonStyle = { padding: "var(--space-2) var(--space-4)", borderRadius: "var(--radius-input)", border: "none", background: "var(--color-brand-primary)", color: "#fff", cursor: "pointer" } as const;
const toolbarButtonStyle = { padding: "var(--space-1) var(--space-3)", borderRadius: "var(--radius-input)", border: "1px solid var(--color-border)", background: "var(--color-surface-card)", color: "var(--color-surface-text)", cursor: "pointer" } as const;

export default function App() {
  const [tab, setTab] = useState<Tab>("health");
  const [error, setError] = useState("");
  const [ready, setReady] = useState<Awaited<ReturnType<typeof api.readyz>> | null>(null);
  const [metrics, setMetrics] = useState("");
  const [capResult, setCapResult] = useState<string>("");
  const [skillMsg, setSkillMsg] = useState("");
  const [audit, setAudit] = useState<string>("");
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [locale, setLocaleState] = useState<Locale>(() => getLocale());

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    (async () => {
      try {
        setReady(await api.readyz());
        setMetrics(await api.metrics());
      } catch (e) {
        setError(String(e));
      }
    })();
  }, []);

  const switchLocale = () => {
    const next: Locale = locale === "zh-CN" ? "en" : "zh-CN";
    setLocale(next);
    setLocaleState(next);
  };

  return (
    <div style={{ fontFamily: "var(--typography-family)", background: "var(--color-surface-bg)", color: "var(--color-surface-text)", minHeight: "100vh", padding: "var(--space-6)" }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: "var(--space-4)", marginBottom: "var(--space-4)" }}>
        <h1 style={{ fontSize: "var(--typography-size-h1)", margin: 0 }}>{t("app.title")}</h1>
        {ready && (
          <>
            <StatusDot ok={ready.status === "ready"} label={t("status.readyLabel", { status: ready.status, backend: ready.event_publisher_backend, pending: ready.outbox?.pending ?? 0 })} />
          </>
        )}
        <button
          aria-label={t("theme.toggle")}
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
          style={{ ...toolbarButtonStyle, marginLeft: "auto" }}
        >
          {theme === "light" ? t("theme.dark") : t("theme.light")}
        </button>
        <button aria-label={t("header.language")} onClick={switchLocale} style={toolbarButtonStyle}>
          {locale === "zh-CN" ? "EN" : "中"}
        </button>
      </header>
      <nav style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}>
        {tabs.map((tabItem) => (
          <button key={tabItem.key} onClick={() => setTab(tabItem.key)} style={{ ...buttonStyle, background: tab === tabItem.key ? "var(--color-brand-primary)" : "var(--color-surface-card)", color: tab === tabItem.key ? "#fff" : "var(--color-surface-text)", border: "1px solid var(--color-border)" }}>
            {t(tabItem.labelKey)}
          </button>
        ))}
      </nav>
      {error && <Card title={t("status.requestError")}><p style={{ color: "var(--color-brand-danger)" }}>{error}</p></Card>}

      {tab === "health" && (
        <>
          <Card title={t("card.outbox")}>
            <JsonView value={ready?.outbox ?? {}} />
          </Card>
          <Card title={t("card.metrics")}>
            <pre style={{ whiteSpace: "pre-wrap", maxHeight: 320, overflow: "auto", margin: 0 }}>{metrics || t("status.loading")}</pre>
          </Card>
        </>
      )}

      {tab === "capacity" && (
        <Card title={t("card.capacity")}>
          <button style={buttonStyle} onClick={async () => {
            try {
              const r = await api.capacity({ online_users: 100000, active_ratio: 0.1, cache_hit_ratio: 0.5, complex_ratio: 0.3 });
              setCapResult(JSON.stringify(r, null, 2));
            } catch (e) { setCapResult(String(e)); }
          }}>{t("button.capacityEstimate")}</button>
          <pre style={{ whiteSpace: "pre-wrap", marginTop: "var(--space-3)" }}>{capResult || t("status.placeholder")}</pre>
        </Card>
      )}

      {tab === "skills" && (
        <Card title={t("card.skills")}>
          <button style={buttonStyle} onClick={async () => {
            try {
              const manifest = { skill_name: `ui-skill-${Date.now() % 100000}`, version: "1.0.0", owner: "admin-ui", description: "从管理台注册", allowed_tools: ["tool-a"], allowed_domains: ["manufacturing"], residency_scope: ["cn-north-1"], risk_level: "low", changelog: "ui-created" };
              await api.skillsRegister(manifest);
              for (const stage of ["review", "staging", "production"]) {
                await api.skillsPromote({ skill_name: manifest.skill_name, version: manifest.version, target_stage: stage });
              }
              setSkillMsg(t("message.skillsPromoted", { skill: manifest.skill_name }));
            } catch (e) { setSkillMsg(String(e)); }
          }}>{t("button.skillsPromote")}</button>
          <p style={{ marginTop: "var(--space-3)" }}>{skillMsg || t("status.placeholder")}</p>
        </Card>
      )}

      {tab === "workshop" && <WorkshopScreen />}

      {tab === "audit" && (
        <Card title={t("card.audit")}>
          <button style={buttonStyle} onClick={async () => {
            try {
              const r = await api.auditQuery({ tenant_id: "group", limit: 10 });
              setAudit(JSON.stringify(r, null, 2));
            } catch (e) { setAudit(String(e)); }
          }}>{t("button.auditQuery")}</button>
          <pre style={{ whiteSpace: "pre-wrap", marginTop: "var(--space-3)", maxHeight: 360, overflow: "auto" }}>{audit || t("status.placeholder")}</pre>
        </Card>
      )}
    </div>
  );
}
