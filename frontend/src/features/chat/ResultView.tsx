import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ChartSpec, Column } from "../../api/types";
import { formatCell, formatMoney, humanizeColumn } from "../../lib/format";

const COLORS = ["#2f6fed", "#10b981", "#f59e0b"];
const MAX_TABLE_ROWS = 100;

function axisTick(value: number) {
  return Math.abs(value) >= 1e6 ? formatMoney(value) : new Intl.NumberFormat("vi-VN").format(value);
}

export function ResultChart({ spec, columns, rows }: { spec: ChartSpec; columns: Column[]; rows: unknown[][] }) {
  const names = columns.map((c) => c.name);
  const data = rows.map((r) => Object.fromEntries(names.map((n, i) => [n, r[i]])));

  if (spec.type === "kpi") {
    const key = spec.y[0];
    return (
      <div className="rounded-lg bg-brand-50 px-5 py-4">
        <p className="text-xs font-medium uppercase tracking-wide text-brand-700">{humanizeColumn(key)}</p>
        <p className="mt-1 text-3xl font-semibold text-slate-900">{formatCell(key, data[0]?.[key])}</p>
      </div>
    );
  }

  // year+month / year+quarter results: build a readable label column.
  let xKey = spec.x;
  if (!xKey) {
    xKey = "__label";
    data.forEach((d) => {
      d.__label = d.month !== undefined ? `${String(d.month).padStart(2, "0")}/${d.year}` : `Q${d.quarter}/${d.year}`;
    });
  }
  const xFormatter = (v: unknown) => formatCell(xKey ?? "", v);
  const common = {
    data,
    margin: { top: 8, right: 16, left: 8, bottom: 8 },
  };
  const children = [
    <CartesianGrid key="g" strokeDasharray="3 3" stroke="#e2e8f0" />,
    <XAxis key="x" dataKey={xKey} tickFormatter={xFormatter} tick={{ fontSize: 12 }} />,
    <YAxis key="y" tickFormatter={axisTick} tick={{ fontSize: 12 }} width={80} />,
    <Tooltip
      key="t"
      labelFormatter={(v) => xFormatter(v)}
      formatter={(value, name) => [formatCell(String(name), value), humanizeColumn(String(name))]}
    />,
    spec.y.length > 1 ? <Legend key="l" formatter={(v) => humanizeColumn(String(v))} /> : null,
  ];
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        {spec.type === "line" ? (
          <LineChart {...common}>
            {children}
            {spec.y.map((k, i) => (
              <Line key={k} type="monotone" dataKey={k} stroke={COLORS[i]} strokeWidth={2} dot={{ r: 3 }} />
            ))}
          </LineChart>
        ) : (
          <BarChart {...common}>
            {children}
            {spec.y.map((k, i) => (
              <Bar key={k} dataKey={k} fill={COLORS[i]} radius={[4, 4, 0, 0]} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

export function ResultTable({ columns, rows }: { columns: Column[]; rows: unknown[][] }) {
  return (
    <div className="scroll-thin max-h-80 overflow-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {columns.map((c) => (
              <th key={c.name} className={`px-3 py-2 font-semibold ${c.type === "number" ? "text-right" : ""}`}>
                {humanizeColumn(c.name)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.slice(0, MAX_TABLE_ROWS).map((row, i) => (
            <tr key={i} className="hover:bg-slate-50">
              {row.map((v, j) => (
                <td key={j} className={`px-3 py-1.5 ${columns[j]?.type === "number" ? "text-right tabular-nums" : ""}`}>
                  {formatCell(columns[j]?.name ?? "", v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_TABLE_ROWS && (
        <p className="bg-slate-50 px-3 py-1.5 text-xs text-slate-500">Hiển thị {MAX_TABLE_ROWS}/{rows.length} dòng</p>
      )}
    </div>
  );
}
