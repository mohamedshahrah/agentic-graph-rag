interface Props {
  role: "user" | "assistant";
  text: string;
}

export default function Message({ role, text }: Props) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm leading-relaxed ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-white text-slate-800 ring-1 ring-slate-200"
        }`}
      >
        {text || (isUser ? "" : "…")}
      </div>
    </div>
  );
}
