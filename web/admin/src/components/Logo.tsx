// B-3 品牌 Logo：盾形 + 书本几何图形（雅迪 EKB 知识库），主色走 var(--color-brand-primary) 随主题切换。
// index.html 的 favicon 是同款图形的 data URI 版本（favicon 上下文不支持 CSS 变量，用品牌色字面量）。
import { t } from "../i18n";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={t("a11y.logoLabel")} data-testid="logo">
      <path d="M16 2 L28 6 V15 C28 23 22.5 28 16 30 C9.5 28 4 23 4 15 V6 Z" fill="var(--color-brand-primary)" />
      <path d="M10 11.5 C12.4 10.3 14.9 10.4 16 11.5 C17.1 10.4 19.6 10.3 22 11.5 V20 C19.6 18.8 17.1 18.9 16 20 C14.9 18.9 12.4 18.8 10 20 Z" fill="#fff" />
      <path d="M16 11.5 V20" stroke="var(--color-brand-primary)" strokeWidth="1.4" />
    </svg>
  );
}
