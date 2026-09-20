// B-4 指标卡：大数字 + 标签（+ 可选单位），用于容量估算结果。
export function MetricCard({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="metric-card" data-testid="metric-card">
      <div className="metric-value">
        {value}
        {unit ? <span className="metric-unit">{unit}</span> : null}
      </div>
      <div className="metric-label">{label}</div>
    </div>
  );
}
