import { useEffect, useState } from "react";
import { api } from "./api";

type Tab = "health" | "capacity" | "skills" | "audit";

const tabs: { key: Tab; label: string }[] = [
  { key: "health", label: "运行健康" },
  { key: "capacity", label: "容量估算" },
  { key: "skills", label: "Skill 治理" },
  { key: "audit", label: "审计查询" },
];

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ background: "var(--color-surface-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", padding: "var(--space-4)", marginBottom: "var(--space-4)" }}>
      <h2 style={{ fontSize: "var(--typography-size-body)", fontWeight: 600, margin: "0 0 var(--space-3)" }}>{title}</h2>
      {children}
    </section>
  );
}

const inputStyle = { padding: "var(--space-2) var(--space-3)", borderRadius: "var(--radius-input)", border: "1px solid var(--color-border)", width: "100%", boxSizing: "border-box" } as const;
const buttonStyle = { padding: "var(--space-2) var(--space-4)", borderRadius: "var(--radius-input)", border: "none", background: "var(--color-brand-primary)", color: "#fff", cursor: "pointer" } as const;

export default function App() {
  const [tab, setTab] = useState<Tab>("health");
  const [error, setError] = useState("");
  const [ready, setReady] = useState<Awaited<ReturnType<typeof api.readyz>> | null>(null);
  const [metrics, setMetrics] = useState("");
  const [capResult, setCapResult] = useState<string>("");
  const [skillMsg, setSkillMsg] = useState("");
  const [audit, setAudit] = useState<string>("");

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

  return (
    <div style={{ fontFamily: "var(--typography-family)", background: "var(--color-surface-bg)", color: "var(--color-surface-text)", minHeight: "100vh", padding: "var(--space-6)" }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: "var(--space-4)", marginBottom: "var(--space-4)" }}>
        <h1 style={{ fontSize: "var(--typography-size-h1)", margin: 0 }}>雅迪 EKB 管理台</h1>
        {ready && (
          <span style={{ color: "var(--color-surface-muted)" }}>
            {ready.status} · 事件后端 {ready.event_publisher_backend} · Outbox 待发 {ready.outbox?.pending ?? 0}
          </span>
        )}
      </header>
      <nav style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}>
        {tabs.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{ ...buttonStyle, background: tab === t.key ? "var(--color-brand-primary)" : "var(--color-surface-card)", color: tab === t.key ? "#fff" : "var(--color-surface-text)", border: "1px solid var(--color-border)" }}>
            {t.label}
          </button>
        ))}
      </nav>
      {error && <Card title="请求错误"><p style={{ color: "var(--color-brand-danger)" }}>{error}</p></Card>}

      {tab === "health" && (
        <>
          <Card title="Outbox 状态">
            <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(ready?.outbox ?? {}, null, 2)}</pre>
          </Card>
          <Card title="/metrics（Prometheus）">
            <pre style={{ whiteSpace: "pre-wrap", maxHeight: 320, overflow: "auto" }}>{metrics || "加载中…"}</pre>
          </Card>
        </>
      )}

      {tab === "capacity" && (
        <Card title="容量估算">
          <button style={buttonStyle} onClick={async () => {
            try {
              const r = await api.capacity({ online_users: 100000, active_ratio: 0.1, cache_hit_ratio: 0.5, complex_ratio: 0.3 });
              setCapResult(JSON.stringify(r, null, 2));
            } catch (e) { setCapResult(String(e)); }
          }}>按默认基线估算（10 万在线）</button>
          <pre style={{ whiteSpace: "pre-wrap", marginTop: "var(--space-3)" }}>{capResult || "—"}</pre>
        </Card>
      )}

      {tab === "skills" && (
        <Card title="注册 + 三级晋级 Skill">
          <button style={buttonStyle} onClick={async () => {
            try {
              const manifest = { skill_name: `ui-skill-${Date.now() % 100000}`, version: "1.0.0", owner: "admin-ui", description: "从管理台注册", allowed_tools: ["tool-a"], allowed_domains: ["manufacturing"], residency_scope: ["cn-north-1"], risk_level: "low", changelog: "ui-created" };
              await api.skillsRegister(manifest);
              for (const stage of ["review", "staging", "production"]) {
                await api.skillsPromote({ skill_name: manifest.skill_name, version: manifest.version, target_stage: stage });
              }
              setSkillMsg(`${manifest.skill_name} 已晋级 production ✅`);
            } catch (e) { setSkillMsg(String(e)); }
          }}>一键注册并晋级</button>
          <p style={{ marginTop: "var(--space-3)" }}>{skillMsg || "—"}</p>
        </Card>
      )}

      {tab === "audit" && (
        <Card title="最近审计（tenant=group）">
          <button style={buttonStyle} onClick={async () => {
            try {
              const r = await api.auditQuery({ tenant_id: "group", limit: 10 });
              setAudit(JSON.stringify(r, null, 2));
            } catch (e) { setAudit(String(e)); }
          }}>查询</button>
          <pre style={{ whiteSpace: "pre-wrap", marginTop: "var(--space-3)", maxHeight: 360, overflow: "auto" }}>{audit || "—"}</pre>
        </Card>
      )}
    </div>
  );
}
