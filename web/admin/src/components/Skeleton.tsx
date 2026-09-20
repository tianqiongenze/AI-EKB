// B-2 Skeleton：卡片加载态（默认 3 行灰条 shimmer 动画，样式见 app.css）。
import { t } from "../i18n";

export function Skeleton({ rows = 3, label }: { rows?: number; label?: string }) {
  const count = Math.max(1, rows);
  return (
    <div className="skeleton" role="status" aria-label={label ?? t("status.loading")} data-testid="skeleton">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-bar" />
      ))}
    </div>
  );
}
