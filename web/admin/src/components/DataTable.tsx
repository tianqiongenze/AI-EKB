// B-1 DataTable：列定义（key/label/width?/render?）+ 斑马纹 + 行悬停 + 单元格溢出省略（title 提示）+ 空态走 EmptyState。
// 表格形态样式（斑马纹/悬停/省略）在 app.css 的 .dt-* 类中，颜色令牌来自 tokens.css。
import type { ReactNode } from "react";
import { EmptyState } from "./EmptyState";
import { t } from "../i18n";

export interface DataTableColumn<Row> {
  key: string;
  label: string;
  width?: number | string;
  render?: (row: Row) => ReactNode;
}

export function DataTable<Row extends Record<string, unknown>>({
  columns,
  rows,
  empty,
}: {
  columns: DataTableColumn<Row>[];
  rows: Row[];
  empty?: ReactNode;
}) {
  if (rows.length === 0) {
    return <>{empty ?? <EmptyState title={t("empty.default")} />}</>;
  }
  return (
    <div className="dt-wrap">
      <table className="dt-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} scope="col" style={col.width !== undefined ? { width: col.width } : undefined}>
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id ?? index)}>
              {columns.map((col) => {
                const raw = row[col.key];
                const text = raw === null || raw === undefined || typeof raw === "object" ? "" : String(raw);
                return (
                  <td key={col.key} className="dt-cell" title={text || undefined}>
                    {col.render ? col.render(row) : text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
