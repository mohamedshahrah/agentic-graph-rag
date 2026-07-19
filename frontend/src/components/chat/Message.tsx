import clsx from "clsx";
import { Sparkles } from "lucide-react";

import type { Source } from "../../api";
import { Spinner } from "../ui";
import { Markdown } from "./Markdown";
import { Sources } from "./Sources";

export interface Turn {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  activity?: string;
  error?: string;
}

// The agent's tool names are implementation detail; these are what the user
// sees while it retrieves, so the pause before the first token is explained
// rather than silent.
const TOOL_LABELS: Record<string, string> = {
  hybrid_search: "Searching your documents",
  vector_search: "Finding related passages",
  graph_neighbors: "Following graph connections",
  expand_subgraph: "Exploring the knowledge graph",
  get_entity: "Looking up an entity",
  fulltext_search: "Searching for exact terms",
  compare: "Gathering evidence to compare",
  global_search: "Reviewing the whole collection",
};

export function Message({ turn }: { turn: Turn }) {
  const isUser = turn.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-xl rounded-br-sm bg-accent px-3.5 py-2.5 text-[15px] leading-relaxed text-accent-text">
          <p className="whitespace-pre-wrap">{turn.content}</p>
        </div>
      </div>
    );
  }

  const waiting = !turn.content && !turn.error;

  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-raised text-muted">
        <Sparkles className="h-3.5 w-3.5" />
      </span>

      <div className="min-w-0 flex-1">
        {waiting && (
          <div className="flex items-center gap-2 text-[13px] text-muted">
            <Spinner className="h-3 w-3" />
            <span>
              {turn.activity
                ? (TOOL_LABELS[turn.activity] ?? "Working")
                : "Thinking"}
              …
            </span>
          </div>
        )}

        {turn.content && <Markdown>{turn.content}</Markdown>}

        {turn.error && (
          <p
            className={clsx(
              "rounded-md bg-danger/10 px-3 py-2 text-[13px] text-danger",
              turn.content && "mt-3",
            )}
          >
            {turn.error}
          </p>
        )}

        {turn.sources && <Sources sources={turn.sources} />}
      </div>
    </div>
  );
}
