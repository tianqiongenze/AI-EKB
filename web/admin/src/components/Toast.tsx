// B-5 Toast：右上角轻通知（success/error 两色，3s 自动消失，aria-live="polite"）。
// 容器常驻（aria-live region 需要在内容变化前就存在）；单项由 Toast 定时器驱动 onDismiss。
import { useEffect } from "react";

export type ToastKind = "success" | "error";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

export const TOAST_AUTO_DISMISS_MS = 3000;

export function ToastStack({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: number) => void }) {
  return (
    <div className="toast-stack" aria-live="polite" data-testid="toast-stack">
      {toasts.map((item) => (
        <Toast key={item.id} item={item} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(item.id), TOAST_AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [item.id, onDismiss]);
  return (
    <div className={`toast toast-${item.kind}`} role="status" data-testid={`toast-${item.kind}`}>
      <span aria-hidden>{item.kind === "success" ? "✓" : "✕"}</span>
      <span>{item.message}</span>
    </div>
  );
}
