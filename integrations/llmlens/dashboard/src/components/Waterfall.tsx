import { useState } from "react";
import { cost as fmtCost, ms as fmtMs, num } from "../lib/format";

interface Span {
  span_id: string;
  name: string;
  kind: string;
  provider: string;
  model: string;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  status: string;
  status_message: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  content: { role: string; content: string }[];
  children: Span[];
}

const KIND_COLOR: Record<string, string> = {
  generation: "#3b82f6",
  tool: "#f59e0b",
  span: "#94a3b8",
  trace: "#64748b",
  event: "#a78bfa",
};

function flatten(nodes: Span[], depth = 0, out: { node: Span; depth: number }[] = []) {
  for (const n of nodes) {
    out.push({ node: n, depth });
    flatten(n.children || [], depth + 1, out);
  }
  return out;
}

export default function Waterfall({ spans }: { spans: Span[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = flatten(spans);
  if (!rows.length) return <p className="text-sm text-slate-400">No spans.</p>;

  const min = Math.min(...rows.map((r) => r.node.start_ms));
  const max = Math.max(...rows.map((r) => r.node.end_ms));
  const total = Math.max(1, max - min);

  return (
    <div className="space-y-1">
      {rows.map(({ node, depth }) => {
        const left = ((node.start_ms - min) / total) * 100;
        const width = Math.max(1.5, (Math.max(1, node.end_ms - node.start_ms) / total) * 100);
        const color = KIND_COLOR[node.kind] || "#94a3b8";
        const expanded = open === node.span_id;
        return (
          <div key={node.span_id}>
            <button
              onClick={() => setOpen(expanded ? null : node.span_id)}
              className="grid w-full grid-cols-[1fr_auto] items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-slate-50"
            >
              <div style={{ paddingLeft: depth * 14 }}>
                <div className="flex items-center gap-2">
                  {node.status === "error" && <span className="text-red-500">●</span>}
                  <span className="font-medium text-slate-700">{node.name || node.kind}</span>
                  {node.model && <span className="text-slate-400">{node.model}</span>}
                </div>
                <div className="mt-1 h-2 rounded bg-slate-100">
                  <div
                    className="h-2 rounded"
                    style={{ marginLeft: `${left}%`, width: `${width}%`, background: color }}
                  />
                </div>
              </div>
              <div className="whitespace-nowrap text-right text-slate-500">
                {fmtMs(node.duration_ms)}
                {node.total_tokens ? ` · ${num(node.total_tokens)} tok` : ""}
                {node.cost_usd ? ` · ${fmtCost(node.cost_usd)}` : ""}
              </div>
            </button>
            {expanded && (
              <div className="ml-4 space-y-2 rounded-lg bg-slate-50 p-2 text-xs ring-1 ring-slate-200">
                {node.status === "error" && (
                  <p className="text-red-600">error: {node.status_message}</p>
                )}
                {node.content.length === 0 && <p className="text-slate-400">No recorded content.</p>}
                {node.content.map((c, i) => (
                  <div key={i}>
                    <p className="font-medium text-slate-500">{c.role}</p>
                    <pre className="whitespace-pre-wrap text-slate-700">{c.content}</pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
