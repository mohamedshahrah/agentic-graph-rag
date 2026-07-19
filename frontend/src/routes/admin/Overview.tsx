import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { admin, type SystemStatus, type UsageSeries } from "../../api";
import { Alert, Card, CardTitle, Select, Skeleton } from "../../components/ui";

export default function Overview() {
  const [usage, setUsage] = useState<UsageSeries | null>(null);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [u, s] = await Promise.all([admin.usage(days), admin.system()]);
        setUsage(u);
        setSystem(s);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load the overview.");
      }
    })();
  }, [days]);

  return (
    <div className="space-y-4">
      {error && <Alert>{error}</Alert>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Users" value={system?.users} sub={`${system?.active_users ?? 0} active`} />
        <Stat label="Conversations" value={system?.threads} />
        <Stat label="Documents" value={system?.files} />
        <Stat
          label={`Messages (${days}d)`}
          value={usage?.totals.messages}
          sub={`${(usage?.totals.tokens ?? 0).toLocaleString()} tokens`}
        />
      </div>

      <Card>
        <CardTitle
          action={
            <Select
              value={String(days)}
              onChange={(e) => setDays(Number(e.target.value))}
              className="h-7 w-auto text-[12px]"
              aria-label="Time range"
            >
              <option value="7">7 days</option>
              <option value="30">30 days</option>
              <option value="90">90 days</option>
            </Select>
          }
        >
          Activity
        </CardTitle>

        {!usage ? (
          <Skeleton className="h-56 w-full" />
        ) : usage.points.length === 0 ? (
          <p className="py-16 text-center text-[13px] text-muted">
            No activity in this period.
          </p>
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={usage.points} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="messages" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="bucket"
                  tickFormatter={shortDate}
                  tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "rgb(var(--text-muted))" }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "rgb(var(--surface))",
                    border: "1px solid rgb(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelFormatter={(label) => shortDate(String(label))}
                />
                <Area
                  type="monotone"
                  dataKey="messages"
                  stroke="rgb(var(--accent))"
                  strokeWidth={2}
                  fill="url(#messages)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value?: number; sub?: string }) {
  return (
    <Card>
      <p className="text-[12px] text-muted">{label}</p>
      {value === undefined ? (
        <Skeleton className="mt-1.5 h-7 w-16" />
      ) : (
        <p className="mt-1 text-2xl font-semibold tracking-tight text-strong">
          {value.toLocaleString()}
        </p>
      )}
      {sub && <p className="mt-0.5 text-[12px] text-muted">{sub}</p>}
    </Card>
  );
}

function shortDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
