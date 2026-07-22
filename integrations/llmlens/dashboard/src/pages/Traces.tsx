import { useEffect, useState } from "react";
import Waterfall from "../components/Waterfall";
import { api } from "../lib/api";
import { cost, ms, num, time } from "../lib/format";

export default function Traces({ refresh }: { refresh: number }) {
  const [rows, setRows] = useState<any[]>([]);
  const [sel, setSel] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setErr("");
    api.traces().then((d) => setRows(d.traces || [])).catch((e) => setErr(String(e)));
  }, [refresh]);

  function open(id: string) {
    api.trace(id).then(setSel).catch((e) => setErr(String(e)));
  }

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="rounded-xl bg-white ring-1 ring-slate-200">
        {err && <p className="p-3 text-sm text-red-600">{err}</p>}
        <table className="w-full text-xs">
          <thead className="border-b text-left text-slate-400">
            <tr>
              <th className="p-2">Trace</th>
              <th className="p-2">When</th>
              <th className="p-2">Duration</th>
              <th className="p-2">Cost</th>
              <th className="p-2">Spans</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.trace_id}
                onClick={() => open(r.trace_id)}
                className="cursor-pointer border-b hover:bg-slate-50"
              >
                <td className="p-2">
                  <span className="flex items-center gap-1">
                    {r.has_error && <span className="text-red-500">●</span>}
                    <span className="text-slate-700">{r.name || r.trace_id.slice(0, 8)}</span>
                  </span>
                  <span className="text-slate-400">{r.user_id || ""}</span>
                </td>
                <td className="p-2 text-slate-500">{time(r.start_time)}</td>
                <td className="p-2 text-slate-500">{ms(r.duration_ms)}</td>
                <td className="p-2 text-slate-500">{cost(Number(r.cost_usd))}</td>
                <td className="p-2 text-slate-500">{num(r.spans)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="p-4 text-center text-slate-400">
                  No traces in this window.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl bg-white p-3 ring-1 ring-slate-200">
        <h3 className="mb-3 text-sm font-medium text-slate-600">
          {sel ? `Trace ${sel.trace_id.slice(0, 12)}` : "Select a trace"}
        </h3>
        {sel ? <Waterfall spans={sel.spans} /> : <p className="text-sm text-slate-400">Click a trace to see its span waterfall.</p>}
      </div>
    </div>
  );
}
