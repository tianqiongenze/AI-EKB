// 共享内联样式（从 App.tsx 下沉，供 App/LoginPage/EmptyState 复用；令牌均引用 tokens.css）。
export const inputStyle = { padding: "var(--space-2) var(--space-3)", borderRadius: "var(--radius-input)", border: "1px solid var(--color-border)", width: "100%", boxSizing: "border-box" } as const;

export const buttonStyle = { padding: "var(--space-2) var(--space-4)", borderRadius: "var(--radius-input)", border: "none", background: "var(--color-brand-primary)", color: "#fff", cursor: "pointer" } as const;

export const toolbarButtonStyle = { padding: "var(--space-1) var(--space-3)", borderRadius: "var(--radius-input)", border: "1px solid var(--color-border)", background: "var(--color-surface-card)", color: "var(--color-surface-text)", cursor: "pointer" } as const;
