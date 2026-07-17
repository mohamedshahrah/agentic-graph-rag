// Thin API client. Every request carries the current user in an X-User-Id
// header, so the backend routes it to that user's isolated namespace. The
// interesting part is streaming: /query returns Server-Sent Events, which we
// read from the fetch body and parse by hand (EventSource can't do POST).

export interface Source {
  chunk_id: string;
  source: string;
  snippet: string;
  score: number;
  retriever: string;
}

export interface StoredFile {
  file_id: string;
  name: string;
  source: string;
}

export interface FileList {
  files: StoredFile[];
  used: number;
  limit: number;
}

const API = "/api";
const USER_KEY = "graphrag_user";
const APIKEY_KEY = "graphrag_key";

let currentUser = localStorage.getItem(USER_KEY) || "default";
let currentKey = localStorage.getItem(APIKEY_KEY) || "";

export function getUser(): string {
  return currentUser;
}

export function setUser(user: string): void {
  currentUser = user || "default";
  localStorage.setItem(USER_KEY, currentUser);
}

export function getApiKey(): string {
  return currentKey;
}

export function setApiKey(key: string): void {
  currentKey = key || "";
  localStorage.setItem(APIKEY_KEY, currentKey);
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  // X-User-Id is used in dev (auth off); Authorization is used when auth is on.
  const h: Record<string, string> = { "X-User-Id": currentUser, ...extra };
  if (currentKey) h["Authorization"] = `Bearer ${currentKey}`;
  return h;
}

// Every non-streaming call goes through this. Without it an error response
// parses as success with all fields undefined — a rejected upload showed
// "queued" forever while polling /ingest/undefined for eternity.
async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// The agent can be silent for a minute while it retrieves, so we can't time out
// on "no tokens yet". The server pings every ~15s, so silence past this means the
// connection is actually dead. Without a bound, a dropped connection leaves
// `reader.read()` awaiting forever — the caller never settles and the UI wedges
// with its send button disabled, unrecoverable without a reload.
const IDLE_TIMEOUT_MS = 60_000;

export async function streamQuery(
  question: string,
  style: string,
  threadId: string,
  onToken: (t: string) => void,
  onSources: (s: Source[]) => void,
  onTool?: (name: string) => void,
): Promise<void> {
  const control = new AbortController();
  let idle: ReturnType<typeof setTimeout> | undefined;
  const resetIdle = () => {
    clearTimeout(idle);
    idle = setTimeout(() => control.abort(), IDLE_TIMEOUT_MS);
  };
  resetIdle();

  try {
    const res = await fetch(`${API}/query`, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ question, style, thread_id: threadId, stream: true }),
      signal: control.signal,
    });
    // A proxy error (502/504) still has a body, which would parse as zero events
    // and finish silently — no tokens, no error, no explanation.
    if (!res.ok) throw new Error(`Server returned ${res.status} ${res.statusText}`);
    if (!res.body) throw new Error("No response stream");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      resetIdle();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line, and the spec allows CRLF, LF
      // or CR. sse-starlette emits CRLF, so splitting on "\n\n" matches nothing
      // in "\r\n\r\n" (0D0A0D0A contains no 0A0A): every frame stays buffered,
      // no token is ever emitted, and the stream renders as silence.
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() ?? "";
      for (const raw of events) {
        const { event, data } = parseEvent(raw);
        if (event === "token") onToken(data);
        else if (event === "tool") onTool?.(data);
        else if (event === "sources") onSources(JSON.parse(data) as Source[]);
        else if (event === "error") throw new Error(data || "the server reported an error");
      }
    }
  } catch (err) {
    if (control.signal.aborted) {
      throw new Error("Connection lost — the server stopped responding. Try again.");
    }
    throw err;
  } finally {
    clearTimeout(idle);
  }
}

export function parseEvent(raw: string): { event: string; data: string } {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    // Only the leading space is padding; the rest of the line is the token, so
    // trimming here would eat the spaces between words.
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  return { event, data: dataLines.join("\n") };
}

export async function uploadFile(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API}/ingest/upload`, { method: "POST", headers: headers(), body: form });
  return jsonOrThrow(res);
}

export async function ingestStatus(jobId: string): Promise<{
  status: string;
  chunks?: number;
  entities?: number;
  detail?: string;
}> {
  const res = await fetch(`${API}/ingest/${jobId}`, { headers: headers() });
  return jsonOrThrow(res);
}

export async function listFiles(): Promise<FileList> {
  const res = await fetch(`${API}/ingest/files`, { headers: headers() });
  return jsonOrThrow(res);
}

export async function deleteFile(fileId: string): Promise<{ chunks_removed: number }> {
  const res = await fetch(`${API}/ingest/files/${fileId}`, {
    method: "DELETE",
    headers: headers(),
  });
  return jsonOrThrow(res);
}

export interface Ready {
  ready: boolean;
  neo4j: boolean;
  redis: boolean;
}

export async function getReady(): Promise<Ready> {
  const res = await fetch(`${API}/ready`, { headers: headers() });
  return jsonOrThrow(res);
}

export async function getHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${API}/health`, { headers: headers() });
  return jsonOrThrow(res);
}

export async function listUsers(): Promise<{ users: string[] }> {
  const res = await fetch(`${API}/users`, { headers: headers() });
  return jsonOrThrow(res);
}

export async function createUser(
  userId: string,
  adminKey?: string,
): Promise<{ user_id: string; api_key?: string }> {
  const extra: Record<string, string> = { "Content-Type": "application/json" };
  if (adminKey) extra["X-Admin-Key"] = adminKey;
  const res = await fetch(`${API}/users`, {
    method: "POST",
    headers: headers(extra),
    body: JSON.stringify({ user_id: userId }),
  });
  return jsonOrThrow(res);
}
