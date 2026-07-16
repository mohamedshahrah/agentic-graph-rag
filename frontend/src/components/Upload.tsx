import { useRef, useState, type DragEvent } from "react";
import { uploadFile, ingestStatus } from "../api";

interface Item {
  id: string;
  name: string;
  status: string; // uploading | queued | running | done | error
  chunks: number;
  entities: number;
  detail?: string;
}

export default function Upload() {
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function patch(id: string, changes: Partial<Item>) {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...changes } : it)));
  }

  function poll(jobId: string, id: string) {
    const timer = setInterval(async () => {
      try {
        const s = await ingestStatus(jobId);
        patch(id, {
          status: s.status,
          chunks: s.chunks ?? 0,
          entities: s.entities ?? 0,
          detail: s.detail,
        });
        if (s.status === "done" || s.status === "error") clearInterval(timer);
      } catch {
        clearInterval(timer);
        patch(id, { status: "error" });
      }
    }, 1500);
  }

  async function handleFiles(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) {
      const id = Math.random().toString(36).slice(2);
      setItems((prev) => [{ id, name: file.name, status: "uploading", chunks: 0, entities: 0 }, ...prev]);
      try {
        const { job_id } = await uploadFile(file);
        patch(id, { status: "queued" });
        poll(job_id, id);
      } catch {
        patch(id, { status: "error" });
      }
    }
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div className="space-y-2">
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`cursor-pointer rounded-xl border-2 border-dashed px-4 py-5 text-center text-sm transition ${
          dragging
            ? "border-blue-500 bg-blue-50 text-blue-700"
            : "border-slate-300 bg-white text-slate-500 hover:border-slate-400"
        }`}
      >
        <p className="font-medium">Drop documents here, or click to browse</p>
        <p className="text-xs text-slate-400">PDF · text · Markdown · images (OCR)</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tiff"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {items.length > 0 && (
        <ul className="space-y-1">
          {items.map((it) => (
            <li
              key={it.id}
              className="flex items-center justify-between rounded-lg bg-white px-3 py-1.5 text-xs ring-1 ring-slate-200"
            >
              <span className="truncate text-slate-700">{it.name}</span>
              <span className="ml-3 flex shrink-0 items-center gap-2">
                {it.status === "done" ? (
                  <span className="text-slate-500">
                    {it.chunks} chunks · {it.entities} entities
                  </span>
                ) : null}
                <StatusBadge status={it.status} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    uploading: "bg-slate-100 text-slate-600",
    queued: "bg-slate-100 text-slate-600",
    running: "bg-amber-100 text-amber-700",
    done: "bg-green-100 text-green-700",
    error: "bg-red-100 text-red-700",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 font-medium ${styles[status] ?? "bg-slate-100 text-slate-600"}`}>
      {status}
    </span>
  );
}
