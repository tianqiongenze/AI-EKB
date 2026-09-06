import type { ReactNode } from "react";

export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      style={{
        background: "var(--color-surface-card)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-card)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-4)",
      }}
      aria-label={title}
    >
      <h2 style={{ fontSize: "var(--typography-size-body)", fontWeight: 600, margin: "0 0 var(--space-3)" }}>{title}</h2>
      {children}
    </section>
  );
}
