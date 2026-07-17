import { useEffect, useMemo, useState } from "react";
import { streamQuery, type Source } from "../api";
import Message from "./Message";
import Sources from "./Sources";

interface Turn {
  role: "user" | "assistant";
  text: string;
  sources?: Source[];
}

interface Thread {
  id: string;
  title: string;
}

// Threads are stored per user in localStorage; the server keeps the matching
// conversation memory under the same thread id, so reopening a thread resumes
// its context (the id is what the checkpointer keys on).
const threadsKey = (user: string) => `graphrag_threads:${user}`;
const turnsKey = (user: string, thread: string) => `graphrag_turns:${user}:${thread}`;

function loadJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

const newId = () => Math.random().toString(36).slice(2);

export default function Chat({ style, user }: { style: string; user: string }) {
  const [threads, setThreads] = useState<Thread[]>(() =>
    loadJSON(threadsKey(user), [] as Thread[]),
  );
  const [activeId, setActiveId] = useState<string>(() => threads[0]?.id ?? newId());
  const [turns, setTurns] = useState<Turn[]>(() =>
    loadJSON(turnsKey(user, activeId), [] as Turn[]),
  );
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState<string | null>(null);

  useEffect(() => {
    localStorage.setItem(threadsKey(user), JSON.stringify(threads));
  }, [threads, user]);

  useEffect(() => {
    localStorage.setItem(turnsKey(user, activeId), JSON.stringify(turns));
  }, [turns, user, activeId]);

  const activeTitle = useMemo(
    () => threads.find((t) => t.id === activeId)?.title,
    [threads, activeId],
  );

  function openThread(id: string) {
    if (busy) return;
    setActiveId(id);
    setTurns(loadJSON(turnsKey(user, id), [] as Turn[]));
  }

  function newThread() {
    if (busy) return;
    const id = newId();
    setActiveId(id);
    setTurns([]);
  }

  function removeThread(id: string) {
    if (busy) return;
    localStorage.removeItem(turnsKey(user, id));
    const rest = threads.filter((t) => t.id !== id);
    setThreads(rest);
    if (id === activeId) {
      const next = rest[0]?.id ?? newId();
      setActiveId(next);
      setTurns(loadJSON(turnsKey(user, next), [] as Turn[]));
    }
  }

  async function send() {
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    setActivity(null);
    if (!activeTitle) {
      const title = question.length > 42 ? question.slice(0, 42) + "…" : question;
      setThreads((prev) => [{ id: activeId, title }, ...prev.filter((t) => t.id !== activeId)]);
    }
    setTurns((t) => [...t, { role: "user", text: question }, { role: "assistant", text: "" }]);

    const update = (fn: (turn: Turn) => Turn) =>
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? fn(turn) : turn)));

    try {
      await streamQuery(
        question,
        style,
        activeId,
        (token) => {
          setActivity(null);
          update((turn) => ({ ...turn, text: turn.text + token }));
        },
        (sources) => update((turn) => ({ ...turn, sources })),
        (tool) => setActivity(tool),
      );
    } catch (err) {
      update((turn) => ({ ...turn, text: turn.text + `\n\n[error] ${String(err)}` }));
    } finally {
      setBusy(false);
      setActivity(null);
    }
  }

  return (
    <div className="flex h-full gap-3">
      <aside className="flex w-40 shrink-0 flex-col gap-1 overflow-y-auto">
        <button
          onClick={newThread}
          className="rounded-lg bg-blue-600 px-2 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={busy}
        >
          + New chat
        </button>
        {threads.map((t) => (
          <div
            key={t.id}
            className={`group flex items-center justify-between rounded-lg px-2 py-1.5 text-xs ${
              t.id === activeId
                ? "bg-white text-slate-800 ring-1 ring-slate-300"
                : "text-slate-600 hover:bg-white"
            }`}
          >
            <button onClick={() => openThread(t.id)} className="truncate text-left" title={t.title}>
              {t.title}
            </button>
            <button
              onClick={() => removeThread(t.id)}
              className="ml-1 hidden shrink-0 text-slate-400 hover:text-red-600 group-hover:block"
              title="Delete thread"
            >
              ×
            </button>
          </div>
        ))}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 space-y-3 overflow-y-auto p-1">
          {turns.length === 0 && (
            <p className="mt-10 text-center text-sm text-slate-400">
              Ask a question about your ingested documents.
            </p>
          )}
          {turns.map((turn, i) => (
            <div key={i} className="space-y-1">
              <Message
                role={turn.role}
                text={turn.text}
                pending={busy && i === turns.length - 1}
                activity={busy && i === turns.length - 1 ? activity : null}
              />
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
    </div>
  );
}
