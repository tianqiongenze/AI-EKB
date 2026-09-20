// B-4 水平对比条形图（纯 SVG，零依赖）：从车间大屏 WorkshopScreen 抽取复用，保证两处图表风格一致。
export function Bars({ items, width = 420 }: { items: { label: string; value: number; color?: string }[]; width?: number }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  const barH = 26;
  const gap = 10;
  return (
    <svg width={width} height={items.length * (barH + gap)} role="img" aria-label="capacity-bars" data-testid="hbars">
      {items.map((it, i) => {
        const w = (it.value / max) * (width - 170);
        const y = i * (barH + gap);
        return (
          <g key={it.label}>
            <text x={0} y={y + 17} fontSize={13} fill="var(--color-surface-muted)">{it.label}</text>
            <rect x={160} y={y} width={Math.max(w, 2)} height={barH} rx={6} fill={it.color ?? "var(--color-brand-primary)"} />
            <text x={166 + Math.max(w, 2)} y={y + 17} fontSize={13} fill="var(--color-surface-text)">{it.value}</text>
          </g>
        );
      })}
    </svg>
  );
}
