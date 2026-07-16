import type { Source } from "../api";

export default function Sources({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <div className="mt-1 space-y-1">
      <p className="text-xs font-medium text-slate-500">Sources</p>
      {sources.map((s) => (
        <details key={s.chunk_id} className="rounded-lg bg-slate-50 p-2 ring-1 ring-slate-200">
          <summary className="cursor-pointer text-xs text-slate-600">
            <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
              {s.retriever}
            </span>{" "}
            {s.source}
          </summary>
          <p className="mt-1 text-xs text-slate-500">{s.snippet}</p>
        </details>
      ))}
    </div>
  );
}
