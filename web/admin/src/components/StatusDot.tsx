export function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  const color = ok ? "var(--color-surface-ok)" : "var(--color-surface-warn)";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-2)" }} data-testid="status-dot">
      <span aria-hidden style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
      <span style={{ color: "var(--color-surface-muted)" }}>{label}</span>
    </span>
  );
}
