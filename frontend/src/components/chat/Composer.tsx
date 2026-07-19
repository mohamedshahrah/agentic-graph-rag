import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent } from "react";

import type { ModelOption } from "../../api";
import { Button, Select } from "../ui";

const STYLES = [
  { value: "detailed", label: "Detailed" },
  { value: "concise", label: "Concise" },
  { value: "technical", label: "Technical" },
  { value: "eli5", label: "Simple" },
];

const MAX_HEIGHT = 200;

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  style,
  onStyleChange,
  model,
  onModelChange,
  models,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  style: string;
  onStyleChange: (v: string) => void;
  model: string;
  onModelChange: (v: string) => void;
  models: ModelOption[];
  disabled?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, up to a point, then scroll — a fixed single line hides
  // what you typed, and unbounded growth eats the transcript.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter breaks the line.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!busy && value.trim()) onSend();
    }
  }

  return (
    <div className="border-t border-border bg-surface px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-xl bg-canvas ring-1 ring-border transition-shadow focus-within:ring-2 focus-within:ring-accent">
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            disabled={disabled}
            placeholder="Ask about your documents…"
            className="w-full resize-none bg-transparent px-3.5 py-3 text-[15px] text-strong placeholder:text-muted focus:outline-none disabled:opacity-60"
          />

          <div className="flex items-center gap-2 px-2.5 pb-2.5">
            <Select
              value={style}
              onChange={(e) => onStyleChange(e.target.value)}
              aria-label="Answer style"
              className="h-7 w-auto text-[12px]"
            >
              {STYLES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>

            {models.length > 1 && (
              <Select
                value={model}
                onChange={(e) => onModelChange(e.target.value)}
                aria-label="Model"
                className="h-7 w-auto text-[12px]"
              >
                {models.map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.label}
                  </option>
                ))}
              </Select>
            )}

            <div className="ml-auto">
              {busy ? (
                <Button size="sm" onClick={onStop} aria-label="Stop generating">
                  <Square className="h-3 w-3 fill-current" />
                  Stop
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={onSend}
                  disabled={!value.trim() || disabled}
                  aria-label="Send"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          </div>
        </div>

        <p className="mt-1.5 text-center text-[11px] text-muted">
          Answers are grounded in your uploaded documents.
        </p>
      </div>
    </div>
  );
}
