import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import {
  deleteFile,
  ingestStatus,
  listFiles,
  uploadFile,
  type StoredFile,
} from "../api";

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
  const [stored, setStored] = useState<StoredFile[]>([]);
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshFiles = useCallback(() => {
    listFiles()
      .then((r) => {
        setStored(r.files);
        setQuota({ used: r.used, limit: r.limit });
      })
      .catch(() => {}); // no Redis -> no file tracking; hide the panel
  }, []);

  useEffect(refreshFiles, [refreshFiles]);

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
        if (s.status === "done" || s.status === "error") {
          clearInterval(timer);
          refreshFiles();
        }
      } catch (err) {
        // A thrown error (404 after a server restart, network gone) must stop
        // the poll — before this, a failed upload polled a dead job id forever.
        clearInterval(timer);
        patch(id, { status: "error", detail: String((err as Error).message ?? err) });
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
      } catch (err) {
        // Surface the server's reason (413 size cap, 429 file limit) instead of
        // a bare red badge.
        patch(id, { status: "error", detail: String((err as Error).message ?? err) });
      }
    }
  }

  async function removeStored(file: StoredFile) {
    try {
      await deleteFile(file.file_id);
      refreshFiles();
    } catch (err) {
      alert(`Delete failed: ${String((err as Error).message ?? err)}`);
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
        <p className="text-xs text-slate-400">
          PDF · Word · text · Markdown · HTML · CSV · images (OCR)
          {quota ? ` — ${quota.used}/${quota.limit} slots used` : ""}
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.md,.markdown,.rst,.docx,.html,.htm,.csv,.tsv,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tiff"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {items.length > 0 && (
        <ul className="space-y-1">
          {items.map((it) => (
            <li
              key={it.id}
              className="rounded-lg bg-white px-3 py-1.5 text-xs ring-1 ring-slate-200"
            >
              <div className="flex items-center justify-between">
                <span className="truncate text-slate-700">{it.name}</span>
                <span className="ml-3 flex shrink-0 items-center gap-2">
                  {it.status === "done" ? (
                    <span className="text-slate-500">
                      {it.chunks} chunks · {it.entities} entities
                    </span>
                  ) : null}
                  <StatusBadge status={it.status} />
                </span>
              </div>
              {it.status === "error" && it.detail ? (
                <p className="mt-1 text-red-600">{it.detail}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {stored.length > 0 && (
        <details className="rounded-lg bg-white px-3 py-1.5 text-xs ring-1 ring-slate-200">
          <summary className="cursor-pointer text-slate-600">
            Stored files ({stored.length})
          </summary>
          <ul className="mt-1 space-y-1">
            {stored.map((f) => (
              <li key={f.file_id} className="flex items-center justify-between">
                <span className="truncate text-slate-700">{f.name}</span>
                <button
                  onClick={() => removeStored(f)}
                  className="ml-3 shrink-0 rounded px-1.5 py-0.5 text-red-600 hover:bg-red-50"
                  title="Delete this file and everything it added to the knowledge base"
                >
                  delete
                </button>
              </li>
            ))}
          </ul>
        </details>
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
