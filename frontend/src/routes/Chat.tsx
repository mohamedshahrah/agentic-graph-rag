import { FileText, PanelRightOpen } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  streamQuery,
  threads as threadsApi,
  type LimitDetail,
  type ThreadInfo,
} from "../api";
import { DocumentsPanel } from "../components/DocumentsPanel";
import { Composer } from "../components/chat/Composer";
import { Message, type Turn } from "../components/chat/Message";
import { QuotaBanner } from "../components/chat/QuotaBanner";
import { ThreadSidebar } from "../components/chat/ThreadSidebar";
import { Alert, Button, EmptyState } from "../components/ui";
import { useAuth } from "../lib/auth";

const STYLE_KEY = "graphrag_style";
const MODEL_KEY = "graphrag_model";

export default function Chat() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { threadId } = useParams();

  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(true);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [quota, setQuota] = useState<LimitDetail | null>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [style, setStyle] = useState(() => localStorage.getItem(STYLE_KEY) ?? "detailed");
  const [model, setModel] = useState(
    () => localStorage.getItem(MODEL_KEY) ?? me?.default_model ?? "",
  );

  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => localStorage.setItem(STYLE_KEY, style), [style]);
  useEffect(() => localStorage.setItem(MODEL_KEY, model), [model]);

  const loadThreads = useCallback(async () => {
    try {
      setThreads((await threadsApi.list()).threads);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load conversations.");
    } finally {
      setLoadingThreads(false);
    }
  }, []);

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

  // Load a conversation's transcript when the route changes. History lives on
  // the server now, so a reload or another device shows the same thing.
  useEffect(() => {
    if (!threadId) {
      setTurns([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await threadsApi.messages(threadId);
        if (cancelled) return;
        setTurns(
          data.messages.map((m) => ({
            role: m.role,
            content: m.content,
            sources: m.sources?.length ? m.sources : undefined,
          })),
        );
      } catch {
        if (!cancelled) navigate("/chat", { replace: true });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, navigate]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function createThread() {
    try {
      const thread = await threadsApi.create();
      setThreads((prev) => [thread, ...prev]);
      navigate(`/chat/${thread.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.limit) setQuota(err.limit);
      else setError(err instanceof Error ? err.message : "Could not start a conversation.");
    }
  }

  async function removeThread(id: string) {
    await threadsApi.remove(id);
    setThreads((prev) => prev.filter((t) => t.id !== id));
    if (id === threadId) navigate("/chat", { replace: true });
  }

  function stop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
  }

  async function send() {
    const question = input.trim();
    if (!question || busy) return;

    setError("");
    setQuota(null);
    setInput("");
    setBusy(true);

    // A conversation is created on the first message rather than up front, so
    // opening the app doesn't litter the sidebar with empty threads.
    let id = threadId;
    if (!id) {
      try {
        const thread = await threadsApi.create();
        setThreads((prev) => [thread, ...prev]);
        id = thread.id;
        navigate(`/chat/${thread.id}`, { replace: true });
      } catch (err) {
        setBusy(false);
        if (err instanceof ApiError && err.limit) setQuota(err.limit);
        else setError(err instanceof Error ? err.message : "Could not start a conversation.");
        return;
      }
    }

    setTurns((prev) => [...prev, { role: "user", content: question }, { role: "assistant", content: "" }]);

    const controller = new AbortController();
    abortRef.current = controller;

    const patchLast = (patch: Partial<Turn>) =>
      setTurns((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], ...patch };
        return next;
      });

    try {
      await streamQuery(
        question,
        style,
        id,
        (token) =>
          setTurns((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            next[next.length - 1] = {
              ...last,
              content: last.content + token,
              activity: undefined,
            };
            return next;
          }),
        (sources) => patchLast({ sources }),
        (tool) => patchLast({ activity: tool }),
        model || undefined,
        controller.signal,
      );
      // The title is set server-side from the first question; reflect it.
      void loadThreads();
    } catch (err) {
      if (controller.signal.aborted) {
        patchLast({ activity: undefined });
      } else if (err instanceof ApiError && err.limit) {
        setQuota(err.limit);
        setTurns((prev) => prev.slice(0, -1)); // drop the empty assistant turn
      } else {
        patchLast({
          error: err instanceof Error ? err.message : "Something went wrong.",
          activity: undefined,
        });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full">
      <ThreadSidebar
        threads={threads}
        activeId={threadId ?? null}
        loading={loadingThreads}
        onSelect={(id) => navigate(`/chat/${id}`)}
        onCreate={createThread}
        onDelete={removeThread}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center justify-end border-b border-border px-4">
          {!showDocs && (
            <Button size="sm" variant="ghost" onClick={() => setShowDocs(true)}>
              <PanelRightOpen className="h-3.5 w-3.5" />
              Documents
            </Button>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {quota && <QuotaBanner detail={quota} />}
            {error && <Alert>{error}</Alert>}

            {turns.length === 0 && !quota && (
              <EmptyState
                icon={<FileText className="h-6 w-6" />}
                title="Ask your documents anything"
                description="Upload a file, then ask a question. Answers cite the passages they came from."
                action={
                  <Button variant="secondary" onClick={() => setShowDocs(true)}>
                    Add documents
                  </Button>
                }
              />
            )}

            {turns.map((turn, i) => (
              <Message key={i} turn={turn} />
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        <Composer
          value={input}
          onChange={setInput}
          onSend={send}
          onStop={stop}
          busy={busy}
          style={style}
          onStyleChange={setStyle}
          model={model}
          onModelChange={setModel}
          models={me?.models ?? []}
        />
      </section>

      {showDocs && <DocumentsPanel onClose={() => setShowDocs(false)} />}
    </div>
  );
}
