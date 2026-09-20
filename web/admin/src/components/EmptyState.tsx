// B-2 EmptyState：内联 SVG 插画 + 主文案 + 副文案 + 可选 CTA，用于异步卡片空态。
export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
}: {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="empty-state" data-testid="empty-state">
      <svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true">
        <rect x="8" y="24" width="40" height="24" rx="4" fill="none" stroke="var(--color-surface-muted)" strokeWidth="2" opacity="0.55" />
        <path d="M8 32 L20 32 L23 38 L33 38 L36 32 L48 32" fill="none" stroke="var(--color-surface-muted)" strokeWidth="2" opacity="0.55" />
        <path d="M18 12 h20" stroke="var(--color-brand-primary)" strokeWidth="2" strokeLinecap="round" opacity="0.7" />
        <path d="M18 18 h12" stroke="var(--color-brand-primary)" strokeWidth="2" strokeLinecap="round" opacity="0.5" />
      </svg>
      <p className="empty-title">{title}</p>
      {description ? <p className="empty-desc">{description}</p> : null}
      {actionLabel && onAction ? (
        <button type="button" className="empty-cta" onClick={onAction} style={{ padding: "var(--space-2) var(--space-4)", borderRadius: "var(--radius-input)", border: "none", background: "var(--color-brand-primary)", color: "#fff", cursor: "pointer", marginTop: "var(--space-2)" }}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
