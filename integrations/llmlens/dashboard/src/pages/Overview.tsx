import { useEffect, useState } from "react";
import { LineChart } from "../components/Chart";
import Stat, { Card } from "../components/Stat";
import { api } from "../lib/api";
import { cost, ms, num, pct } from "../lib/format";

export default function Overview({ refresh }: { refresh: number }) {
  const [ov, setOv] = useState<any>(null);
  const [pts, setPts] = useState<any[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    setErr("");
    api.overview().then(setOv).catch((e) => setErr(String(e)));
    api.timeseries().then((d) => setPts(d.points || [])).catch(() => {});
  }, [refresh]);

  return (
    <div className="space-y-4">
      {err && <p className="rounded-lg bg-red-50 p-2 text-sm text-red-600">{err} — check the admin key.</p>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Requests" value={num(ov?.requests || 0)} />
        <Stat label="Error rate" value={pct(ov?.error_rate || 0)} sub={`${num(ov?.errors || 0)} errors`} />
        <Stat label="Cost" value={cost(ov?.cost_usd || 0)} sub={`${num(ov?.tokens || 0)} tokens`} />
        <Stat
          label="Latency p95"
          value={ms(ov?.latency_p95 || 0)}
          sub={`p50 ${ms(ov?.latency_p50 || 0)} · p99 ${ms(ov?.latency_p99 || 0)}`}
        />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="Requests & errors">
          <LineChart
            points={pts}
            lines={[
              { key: "requests", color: "#3b82f6", label: "requests" },
              { key: "errors", color: "#ef4444", label: "errors" },
            ]}
          />
        </Card>
        <Card title="Cost over time ($)">
          <LineChart points={pts} lines={[{ key: "cost_usd", color: "#10b981", label: "cost" }]} />
        </Card>
        <Card title="Latency percentiles (ms)">
          <LineChart
            points={pts}
            lines={[
              { key: "latency_p50", color: "#94a3b8", label: "p50" },
              { key: "latency_p95", color: "#f59e0b", label: "p95" },
              { key: "latency_p99", color: "#ef4444", label: "p99" },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
