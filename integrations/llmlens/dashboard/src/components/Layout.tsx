interface Props {
  view: string;
  onView: (v: string) => void;
  project: string;
  hours: number;
  adminKey: string;
  onProject: (v: string) => void;
  onHours: (v: number) => void;
  onAdminKey: (v: string) => void;
  onRefresh: () => void;
  children: React.ReactNode;
}

const VIEWS = ["overview", "traces", "cost", "errors", "alerts"];

export default function Layout(p: Props) {
  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-3 bg-slate-100 p-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">llmlens</h1>
          <p className="text-xs text-slate-500">LLM observability — traces, cost, latency, alerts.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <input
            value={p.project}
            onChange={(e) => p.onProject(e.target.value)}
            placeholder="project_id"
            className="w-32 rounded-lg border border-slate-300 px-2 py-1"
          />
          <select
            value={p.hours}
            onChange={(e) => p.onHours(Number(e.target.value))}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1"
          >
            {[1, 6, 24, 72, 168].map((h) => (
              <option key={h} value={h}>
                last {h}h
              </option>
            ))}
          </select>
          <input
            type="password"
            value={p.adminKey}
            onChange={(e) => p.onAdminKey(e.target.value)}
            placeholder="admin key"
            className="w-28 rounded-lg border border-slate-300 px-2 py-1"
          />
          <button
            onClick={p.onRefresh}
            className="rounded-lg bg-slate-800 px-3 py-1 font-medium text-white"
          >
            Refresh
          </button>
        </div>
      </header>

      <nav className="flex gap-1">
        {VIEWS.map((v) => (
          <button
            key={v}
            onClick={() => p.onView(v)}
            className={`rounded-lg px-3 py-1.5 text-sm capitalize ${
              p.view === v ? "bg-white font-medium text-slate-800 ring-1 ring-slate-200" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {v}
          </button>
        ))}
      </nav>

      <main className="flex-1 overflow-y-auto">{p.children}</main>
    </div>
  );
}
