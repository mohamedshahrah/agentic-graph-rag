import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { num, time } from "../lib/format";

export default function Errors({ refresh }: { refresh: number }) {
  const [rows, setRows] = useState<any[]>([]);

  useEffect(() => {
    api.errors().then((d) => setRows(d.errors || [])).catch(() => {});
  }, [refresh]);

  return (
    <div className="rounded-xl bg-white ring-1 ring-slate-200">
      <table className="w-full text-xs">
        <thead className="border-b text-left text-slate-400">
          <tr>
            <th className="p-2">Error</th>
            <th className="p-2">Model</th>
            <th className="p-2">Count</th>
            <th className="p-2">Last seen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b">
              <td className="p-2 text-slate-700">{r.status_message || "(no message)"}</td>
              <td className="p-2 text-slate-500">{r.model}</td>
              <td className="p-2 text-slate-500">{num(r.n)}</td>
              <td className="p-2 text-slate-500">{time(r.last_seen)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="p-4 text-center text-slate-400">
                No errors in this window. 🎉
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
