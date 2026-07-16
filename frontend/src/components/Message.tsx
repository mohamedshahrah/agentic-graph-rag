interface Props {
  role: "user" | "assistant";
  text: string;
  /** Answer not started yet — the agent is still retrieving. */
  pending?: boolean;
}

export default function Message({ role, text, pending }: Props) {
  const isUser = role === "user";

  // The agent retrieves and calls tools before emitting a single token, which on
  // a local model is tens of seconds of silence. An empty bubble there is
  // indistinguishable from a hung request, so say what's happening instead.
  const waiting = !isUser && !text && pending;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm leading-relaxed ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-white text-slate-800 ring-1 ring-slate-200"
        }`}
      >
        {waiting ? (
          <span className="flex items-center gap-2 text-slate-500">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600" />
            Searching your documents…
          </span>
        ) : (
          text || (isUser ? "" : "…")
        )}
      </div>
    </div>
  );
}
