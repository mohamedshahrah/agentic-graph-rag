// Tiny dependency-free SVG charts: a multi-line time series and a horizontal
// bar list. Enough for cost / latency / error dashboards without a chart lib.

interface Line {
  key: string;
  color: string;
  label: string;
}

interface LineChartProps {
  points: Record<string, number>[];
  lines: Line[];
  height?: number;
}

export function LineChart({ points, lines, height = 180 }: LineChartProps) {
  const w = 640;
  const h = height;
  const pad = 28;
  if (!points.length) return <Empty height={h} />;

  const all = lines.flatMap((l) => points.map((p) => p[l.key] ?? 0));
  const max = Math.max(1, ...all);
  const step = (w - 2 * pad) / Math.max(1, points.length - 1);
  const y = (v: number) => h - pad - (v / max) * (h - 2 * pad);
  const path = (key: string) =>
    points.map((p, i) => `${i ? "L" : "M"}${pad + i * step},${y(p[key] ?? 0)}`).join(" ");

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full">
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#e2e8f0" />
        <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="#e2e8f0" />
        {lines.map((l) => (
          <path key={l.key} d={path(l.key)} fill="none" stroke={l.color} strokeWidth={2} />
        ))}
      </svg>
      <div className="flex gap-4 text-xs text-slate-500">
        {lines.map((l) => (
          <span key={l.key} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: l.color }} />
            {l.label}
          </span>
        ))}
      </div>
    </div>
  );
}

interface BarItem {
  label: string;
  value: number;
}

export function BarList({ items, format }: { items: BarItem[]; format: (v: number) => string }) {
  if (!items.length) return <p className="text-sm text-slate-400">No data.</p>;
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="space-y-1.5">
      {items.map((it) => (
        <div key={it.label} className="text-xs">
          <div className="flex justify-between">
            <span className="truncate text-slate-700">{it.label}</span>
            <span className="text-slate-500">{format(it.value)}</span>
          </div>
          <div className="mt-0.5 h-2 rounded bg-slate-100">
            <div
              className="h-2 rounded bg-blue-500"
              style={{ width: `${(it.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function Empty({ height }: { height: number }) {
  return (
    <div className="flex items-center justify-center text-sm text-slate-400" style={{ height }}>
      No data in this window.
    </div>
  );
}
