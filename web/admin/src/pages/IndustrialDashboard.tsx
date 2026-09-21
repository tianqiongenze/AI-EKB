// 工业 KPI 看板（P1-⑤ 前端）：OEE/直通率/缺陷帕累托/能耗 proxy，纯 SVG 时序，零图表依赖。
import { useEffect, useMemo, useState } from "react";
import { apiExt, type IndustrialKpiPanel, type IndustrialTimeSeries } from "../apiExt";
import { Bars } from "../components/Bars";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { Skeleton } from "../components/Skeleton";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function TimeSeries({ points }: { points: { ts: string; value: number }[] }) {
  if (points.length === 0) return <EmptyState title="无时序数据" description="窗口内无事件" />;
  const maxV = Math.max(...points.map((p) => p.value), 1);
  const W = 640;
  const H = 140;
  const step = points.length > 1 ? W / (points.length - 1) : W;
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(H - (p.value / maxV) * (H - 20)).toFixed(1)}`)
    .join(" ");
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="kpi-timeseries">
      <path d={path} fill="none" stroke="var(--color-brand-primary, #1677ff)" strokeWidth="2" />
      <line x1="0" y1={H - 1} x2={W} y2={H - 1} stroke="var(--color-border)" />
      <text x={4} y={12} fontSize={11} fill="var(--color-surface-text-secondary, #888)">
        max {maxV}
      </text>
    </svg>
  );
}

export function IndustrialDashboard() {
  const [panel, setPanel] = useState<IndustrialKpiPanel | null>(null);
  const [series, setSeries] = useState<IndustrialTimeSeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [p, s] = await Promise.all([
          apiExt.industrialKpis(),
          apiExt.industrialTimeseries("audit_events", 24),
        ]);
        if (!cancelled) {
          setPanel(p);
          setSeries(s);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const defectBars = useMemo(
    () =>
      (panel?.overall.defect_distribution.items ?? []).map((d) => ({
        label: d.reason,
        value: d.count,
      })),
    [panel],
  );

  if (loading) return <Skeleton rows={6} />;
  if (error) return <EmptyState title="看板加载失败" description={error} />;
  if (!panel) return <EmptyState title="无数据" description="看板未返回数据" />;

  const o = panel.overall;
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
        <Card title={`设备 OEE${o.oee.proxy_for ? " (proxy)" : ""}`}>
          <div style={{ fontSize: 32, fontWeight: 700 }}>{pct(o.oee.value)}</div>
          <div style={{ fontSize: 12, color: "#888" }}>
            可用率 {pct(o.oee.components.availability)} · 性能{" "}
            {o.oee.components.performance == null ? "—" : pct(o.oee.components.performance)} · 良率{" "}
            {pct(o.oee.components.quality)}
          </div>
        </Card>
        <Card title="产线直通率 (proxy)">
          <div style={{ fontSize: 32, fontWeight: 700 }}>{pct(o.first_pass_yield.value)}</div>
          <div style={{ fontSize: 12, color: "#888" }}>
            {o.first_pass_yield.accepted}/{o.first_pass_yield.total} 通过
          </div>
        </Card>
        <Card title="事件能耗 proxy">
          <div style={{ fontSize: 32, fontWeight: 700 }}>{o.energy_proxy.events_per_hour.toFixed(1)}</div>
          <div style={{ fontSize: 12, color: "#888" }}>事件/小时 · 共 {o.energy_proxy.total_events} 条</div>
        </Card>
      </div>

      <Card title={`缺陷帕累托（拒绝 ${o.defect_distribution.rejected}/${o.defect_distribution.total}）`}>
        {defectBars.length === 0 ? (
          <EmptyState title="无缺陷记录" description="窗口内质量数据为空" />
        ) : (
          <Bars items={defectBars} />
        )}
      </Card>

      <Card title="审计事件时序（近 24h / 分钟桶）">
        <TimeSeries points={series?.points ?? []} />
      </Card>

      <p style={{ fontSize: 11, color: "#999" }}>
        口径说明：OEE/直通率/能耗为平台侧 proxy 指标，基于控制面审计事件推导；真实电表/MES 设备直连见 unavailable:{" "}
        {panel.unavailable.join("、") || "无"}。
      </p>
    </div>
  );
}
