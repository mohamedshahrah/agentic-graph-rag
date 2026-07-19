import clsx from "clsx";
import { MessageSquarePlus, Trash2 } from "lucide-react";

import type { ThreadInfo } from "../../api";
import { Button, Skeleton } from "../ui";

export function ThreadSidebar({
  threads,
  activeId,
  loading,
  onSelect,
  onCreate,
  onDelete,
}: {
  threads: ThreadInfo[];
  activeId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface">
      <div className="p-2.5">
        <Button variant="secondary" onClick={onCreate} className="w-full justify-start">
          <MessageSquarePlus className="h-3.5 w-3.5" />
          New chat
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-2.5">
        {loading ? (
          <div className="space-y-1.5">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : threads.length === 0 ? (
          <p className="px-2 py-6 text-center text-[12px] text-muted">
            No conversations yet.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {threads.map((thread) => (
              <li key={thread.id} className="group relative">
                <button
                  onClick={() => onSelect(thread.id)}
                  className={clsx(
                    "w-full truncate rounded-md py-1.5 pl-2.5 pr-8 text-left text-[13px] transition-colors",
                    thread.id === activeId
                      ? "bg-raised font-medium text-strong"
                      : "text-body hover:bg-raised/60",
                  )}
                  title={thread.title}
                >
                  {thread.title}
                </button>
                <button
                  onClick={() => onDelete(thread.id)}
                  aria-label={`Delete ${thread.title}`}
                  // Hidden until hover/focus so the list stays calm, but
                  // reachable by keyboard.
                  className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-muted opacity-0 transition-opacity hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
