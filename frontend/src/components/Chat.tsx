import { useRef, useState } from "react";
import { streamQuery, type Source } from "../api";
import Message from "./Message";
import Sources from "./Sources";

interface Turn {
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
}

export default function Chat({ style }: { style: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const threadId = useRef(Math.random().toString(36).slice(2));

  async function send() {
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    setTurns((t) => [...t, { role: "user", text: question }, { role: "assistant", text: "" }]);

    const update = (fn: (turn: Turn) => Turn) =>
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? fn(turn) : turn)));

    try {
      await streamQuery(
        question,
        style,
        threadId.current,
        (token) => update((turn) => ({ ...turn, text: turn.text + token })),
        (sources) => update((turn) => ({ ...turn, sources })),
      );
    } catch (err) {
      update((turn) => ({ ...turn, text: turn.text + `\n\n[error] ${String(err)}` }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto p-1">
        {turns.length === 0 && (
          <p className="mt-10 text-center text-sm text-slate-400">
            Ask a question about your ingested documents.
          </p>
        )}
        {turns.map((turn, i) => (
          <div key={i} className="space-y-1">
            <Message role={turn.role} text={turn.text} />
            {turn.role === "assistant" && <Sources sources={turn.sources ?? []} />}
          </div>
        ))}
      </div>

      <div className="mt-3 flex gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={1}
          placeholder="Ask anything…"
          className="flex-1 resize-none rounded-xl border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={send}
          disabled={busy}
          className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
