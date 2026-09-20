// 车间大屏（M2 前置页）：轻量内联 SVG 图表，零新增依赖（对标 ECharts 大屏但保首包预算）。
// 设计令牌复用 tokens.css；数据源 /readyz + /metrics；大屏场景建议 1080p 全屏展示。
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Bars } from "../components/Bars";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";
import { t } from "../i18n";

type Readyz = { status: string; event_publisher_backend: string; outbox: Record<string, number> };

function Donut({ parts, size = 180 }: { parts: { label: string; value: number; color: string }[]; size?: number }) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  const r = size / 2 - 12;
  const cx = size / 2;
  let acc = 0;
  return (
    <svg width={size} height={size} role="img" aria-label="outbox-donut">
      {parts.map((p) => {
        const frac = p.value / total;
        const start = acc * 2 * Math.PI - Math.PI / 2;
        const end = (acc + frac) * 2 * Math.PI - Math.PI / 2;
        acc += frac;
        const large = frac > 0.5 ? 1 : 0;
        const d = `M ${cx + r * Math.cos(start)} ${cx + r * Math.sin(start)} A ${r} ${r} 0 ${large} 1 ${cx + r * Math.cos(end)} ${cx + r * Math.sin(end)}`;
        return <path key={p.label} d={d} stroke={p.color} strokeWidth={18} fill="none" />;
      })}
      <text x={cx} y={cx + 5} textAnchor="middle" fontSize={20} fill="var(--color-surface-text)">{total}</text>
    </svg>
  );
}

function parseOutboxSeries(metrics: string): { ts: string; count: number }[] {
  const rows = metrics
    .split("\n")
    .filter((l) => l.startsWith("ekb_http_request_duration_seconds_count") && l.includes('path="/events/relay"'));
  return rows.map((r) => ({ ts: r.match(/status="(\d+)"/)?.[1] ?? "?", count: Number(r.split(" ").pop() ?? 0) }));
}

export function WorkshopScreen() {
  const [ready, setReady] = useState<Readyz | null>(null);
  const [metrics, setMetrics] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setReady(await api.readyz());
        setMetrics(await api.metrics());
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const outbox = ready?.outbox ?? {};
  const outboxTotal = useMemo(() => Object.values(outbox).reduce((s, v) => s + v, 0), [ready]);
  const donutParts = useMemo(
    () => [
      { label: "published", value: outbox.published ?? 0, color: "var(--color-surface-ok)" },
      { label: "pending", value: outbox.pending ?? 0, color: "var(--color-surface-warn)" },
      { label: "processing", value: outbox.processing ?? 0, color: "var(--color-brand-primary)" },
      { label: "dead", value: outbox.dead ?? 0, color: "var(--color-brand-danger)" },
    ],
    [ready]
  );
  const relaySeries = parseOutboxSeries(metrics);

  return (
    <div style={{ padding: "var(--space-2) 0", color: "var(--color-surface-text)" }}>
      <h1 style={{ fontSize: "var(--typography-size-h1)", marginTop: 0 }}>车间大屏 · 事件与容量总览</h1>
      {error && <p style={{ color: "var(--color-brand-danger)" }}>{error}</p>}
      <div style={{ display: "flex", gap: "var(--space-6)", flexWrap: "wrap" }}>
        <section style={{ background: "var(--color-surface-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", padding: "var(--space-4)" }}>
          <h2 style={{ fontSize: "var(--typography-size-body)", marginTop: 0 }}>Outbox 事件分布</h2>
          {loading ? (
            <Skeleton />
          ) : outboxTotal > 0 ? (
            <>
              <Donut parts={donutParts} />
              <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", marginTop: "var(--space-3)" }}>
                {donutParts.map((p) => (
                  <span key={p.label} style={{ fontSize: 13, color: "var(--color-surface-muted)" }}>
                    <span style={{ color: p.color }}>●</span> {p.label} {p.value}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <EmptyState title={t("empty.outbox.title")} />
          )}
        </section>
        <section style={{ background: "var(--color-surface-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", padding: "var(--space-4)" }}>
          <h2 style={{ fontSize: "var(--typography-size-body)", marginTop: 0 }}>Relay 吞吐（按状态计数）</h2>
          {loading ? (
            <Skeleton />
          ) : relaySeries.length > 0 ? (
            <Bars items={relaySeries.map((r) => ({ label: `status ${r.ts}`, value: r.count }))} />
          ) : (
            <EmptyState title={t("empty.relay.title")} description="生产开启后台 relay 后可见" />
          )}
        </section>
        <section style={{ background: "var(--color-surface-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", padding: "var(--space-4)" }}>
          <h2 style={{ fontSize: "var(--typography-size-body)", marginTop: 0 }}>运行状态</h2>
          {loading ? (
            <Skeleton />
          ) : (
            <>
              <p>状态：{ready?.status ?? "—"}</p>
              <p>事件后端：{ready?.event_publisher_backend ?? "—"}</p>
              <p style={{ color: "var(--color-surface-muted)" }}>建议 1080p 全屏展示；刷新间隔可经 /metrics 抓取（15s）</p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
