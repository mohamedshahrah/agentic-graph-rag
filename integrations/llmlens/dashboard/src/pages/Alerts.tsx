import { useEffect, useState } from "react";
import { Card } from "../components/Stat";
import { api, getProject } from "../lib/api";
import { time } from "../lib/format";

const TYPES = ["error_rate", "cost_spike", "latency_p95", "volume"];

export default function Alerts({ refresh }: { refresh: number }) {
  const [rules, setRules] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [form, setForm] = useState({ name: "", type: "error_rate", threshold: 0.1, window_seconds: 300, webhook: "" });
  const [msg, setMsg] = useState("");

  function load() {
    api.alertRules().then((d) => setRules(d.rules || [])).catch(() => {});
    api.alertEvents().then((d) => setEvents(d.events || [])).catch(() => {});
  }
  useEffect(load, [refresh]);

  async function submit() {
    setMsg("");
    try {
      let channel_id: number | null = null;
      if (form.webhook) {
        const ch = await api.createChannel({ project_id: getProject(), kind: "webhook", target: form.webhook });
        channel_id = ch.id;
      }
      await api.createRule({
        project_id: getProject(),
        name: form.name || `${form.type} alert`,
        type: form.type,
        threshold: Number(form.threshold),
        window_seconds: Number(form.window_seconds),
        cooldown_seconds: 900,
        channel_id,
      });
      setMsg("Rule created.");
      setForm({ ...form, name: "", webhook: "" });
      load();
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function toggleRule(rule: any) {
    setMsg("");
    try {
      await api.toggleRule(rule.id, !rule.enabled);
      load();
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function deleteRule(rule: any) {
    if (!confirm(`Delete rule "${rule.name}" and its alert history?`)) return;
    setMsg("");
    try {
      await api.deleteRule(rule.id);
      load();
    } catch (e) {
      setMsg(String(e));
    }
  }

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card title="Create alert rule">
        <div className="space-y-2 text-sm">
          <input className="w-full rounded border border-slate-300 px-2 py-1" placeholder="name"
            value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="flex gap-2">
            <select className="rounded border border-slate-300 px-2 py-1"
              value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <input className="w-24 rounded border border-slate-300 px-2 py-1" type="number" step="any"
              value={form.threshold} onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })}
              placeholder="threshold" />
            <input className="w-24 rounded border border-slate-300 px-2 py-1" type="number"
              value={form.window_seconds} onChange={(e) => setForm({ ...form, window_seconds: Number(e.target.value) })}
              placeholder="window s" />
          </div>
          <input className="w-full rounded border border-slate-300 px-2 py-1" placeholder="webhook URL (optional)"
            value={form.webhook} onChange={(e) => setForm({ ...form, webhook: e.target.value })} />
          <button onClick={submit} className="rounded bg-blue-600 px-3 py-1 font-medium text-white">Create</button>
          {msg && <p className="text-xs text-slate-500">{msg}</p>}
        </div>

        <h4 className="mt-4 mb-1 text-xs font-medium text-slate-500">Rules</h4>
        <ul className="space-y-1 text-xs">
          {rules.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 rounded bg-slate-50 px-2 py-1">
              <span className={r.enabled ? "" : "text-slate-400"}>
                {r.name}
                {!r.enabled && <span className="ml-1 rounded bg-slate-200 px-1 text-[10px]">paused</span>}
              </span>
              <span className="flex items-center gap-2">
                <span className="text-slate-500">{r.type} &gt; {r.threshold} / {r.window_seconds}s</span>
                <button
                  onClick={() => toggleRule(r)}
                  className="rounded border border-slate-300 px-1.5 py-0.5 text-slate-600 hover:bg-white"
                  title={r.enabled ? "Pause this rule" : "Resume this rule"}
                >
                  {r.enabled ? "pause" : "resume"}
                </button>
                <button
                  onClick={() => deleteRule(r)}
                  className="rounded border border-red-200 px-1.5 py-0.5 text-red-600 hover:bg-red-50"
                  title="Delete this rule and its alert history"
                >
                  delete
                </button>
              </span>
            </li>
          ))}
          {rules.length === 0 && <li className="text-slate-400">No rules yet.</li>}
        </ul>
      </Card>

      <Card title="Recent alerts">
        <ul className="space-y-1 text-xs">
          {events.map((e) => (
            <li key={e.id} className="rounded bg-red-50 px-2 py-1">
              <div className="flex justify-between">
                <span className="font-medium text-red-700">{e.rule_name}</span>
                <span className="text-slate-400">{time(e.fired_at)}</span>
              </div>
              <span className="text-slate-600">{e.message}</span>
            </li>
          ))}
          {events.length === 0 && <li className="text-slate-400">No alerts fired.</li>}
        </ul>
      </Card>
    </div>
  );
}
