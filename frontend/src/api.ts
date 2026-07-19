// API client. Requests carry the session cookie (`credentials: "include"`), so
// identity is server-issued rather than a header the page picks.
//
// The interesting part is streaming: /query returns Server-Sent Events, which
// we read from the fetch body and parse by hand (EventSource can't do POST).
// That parser is load-bearing and deliberately unchanged — see the comments on
// frame splitting and the idle timeout.

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

export interface ModelOption {
  model: string;
  label: string;
  provider: string;
}

export interface Me {
  user_id: string;
  email: string;
  role: string;
  tenant_id: string;
  authenticated: boolean;
  models: ModelOption[];
  default_model: string;
}

export interface ThreadInfo {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface MessageInfo {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  model: string;
  created_at: string;
}

export interface LimitsInfo {
  limits: Record<string, number>;
  usage: Record<string, number>;
  files_used: number;
  storage_used_mb: number;
  threads_used: number;
}

export interface ApiKeyInfo {
  id: number;
  label: string;
  created_at: string;
  last_used_at: string | null;
}

const API = "/api";

/** A 429 carries the structured limit detail the quota banner renders. */
export interface LimitDetail {
  code: string;
  limit: string;
  used: number;
  max: number;
  retry_after: number;
  message: string;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  limit?: LimitDetail;

  constructor(message: string, status: number, code?: string, limit?: LimitDetail) {
    super(message);
    this.status = status;
    this.code = code;
    this.limit = limit;
  }
}

// Dev builds may still identify with a header when the server has auth off.
// Production never sends it: with auth on the server ignores it entirely.
const DEV_USER_KEY = "graphrag_dev_user";

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  if (import.meta.env.DEV) {
    const devUser = localStorage.getItem(DEV_USER_KEY);
    if (devUser) h["X-User-Id"] = devUser;
  }
  return h;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    headers: headers(init.headers as Record<string, string>),
  });
  return jsonOrThrow<T>(res);
}

function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

// Every non-streaming call goes through this. Without it an error response
// parses as success with all fields undefined — a rejected upload showed
// "queued" forever while polling /ingest/undefined for eternity.
async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    let code: string | undefined;
    let limit: LimitDetail | undefined;
    try {
      const body = await res.json();
      const d = body?.detail;
      if (typeof d === "string") {
        detail = d;
      } else if (d && typeof d === "object") {
        detail = d.message ?? JSON.stringify(d);
        code = d.code;
        if (d.code === "limit_exceeded") limit = d as LimitDetail;
      }
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(detail, res.status, code, limit);
  }
  if (res.status === 204) return undefined as T;
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
  model?: string,
  signal?: AbortSignal,
): Promise<void> {
  const control = new AbortController();
  signal?.addEventListener("abort", () => control.abort());
  let idle: ReturnType<typeof setTimeout> | undefined;
  const resetIdle = () => {
    clearTimeout(idle);
    idle = setTimeout(() => control.abort(), IDLE_TIMEOUT_MS);
  };
  resetIdle();

  try {
    const res = await fetch(`${API}/query`, {
      method: "POST",
      credentials: "include",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        question,
        style,
        thread_id: threadId,
        stream: true,
        ...(model ? { model } : {}),
      }),
      signal: control.signal,
    });
    // A proxy error (502/504) still has a body, which would parse as zero events
    // and finish silently — no tokens, no error, no explanation.
    if (!res.ok) await jsonOrThrow(res);
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
    if (control.signal.aborted && !signal?.aborted) {
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

// -- auth ---------------------------------------------------------------------

export const auth = {
  me: () => request<Me>("/auth/me"),
  signup: (email: string, password: string) =>
    request<{ ok: boolean; message: string }>("/auth/signup", json({ email, password })),
  verify: (email: string, code: string) => request<Me>("/auth/verify", json({ email, code })),
  resend: (email: string) =>
    request<{ ok: boolean; message: string }>("/auth/resend", json({ email })),
  login: (email: string, password: string) =>
    request<Me>("/auth/login", json({ email, password })),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  limits: () => request<LimitsInfo>("/auth/limits"),
  listKeys: () => request<{ keys: ApiKeyInfo[] }>("/auth/keys"),
  createKey: (label: string) =>
    request<{ id: number; api_key: string }>("/auth/keys", json({ label })),
  revokeKey: (id: number) => request<{ ok: boolean }>(`/auth/keys/${id}`, { method: "DELETE" }),
};

// -- conversations ------------------------------------------------------------

export const threads = {
  list: () => request<{ threads: ThreadInfo[] }>("/threads"),
  create: (title = "New chat") => request<ThreadInfo>("/threads", json({ title })),
  rename: (id: string, title: string) =>
    request<ThreadInfo>(`/threads/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  remove: (id: string) => request<{ ok: boolean }>(`/threads/${id}`, { method: "DELETE" }),
  messages: (id: string) =>
    request<{ thread: ThreadInfo; messages: MessageInfo[] }>(`/threads/${id}/messages`),
};

// -- documents ----------------------------------------------------------------

export async function uploadFile(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return request<{ job_id: string }>("/ingest/upload", { method: "POST", body: form });
}

export const ingestStatus = (jobId: string) =>
  request<{ status: string; chunks?: number; entities?: number; detail?: string }>(
    `/ingest/${jobId}`,
  );

export const listFiles = () => request<FileList>("/ingest/files");

export const deleteFile = (fileId: string) =>
  request<{ chunks_removed: number }>(`/ingest/files/${fileId}`, { method: "DELETE" });

// -- health -------------------------------------------------------------------

export interface Ready {
  ready: boolean;
  neo4j: boolean;
  redis: boolean;
}

export const getReady = () => request<Ready>("/ready");
export const getHealth = () => request<{ status: string; version: string }>("/health");

// -- admin --------------------------------------------------------------------

export interface AdminUser {
  id: string;
  email: string;
  role: string;
  status: string;
  tenant_id: string;
  created_at: string;
  last_login_at: string | null;
  email_verified: boolean;
  files: number;
  threads: number;
  messages_30d: number;
  tokens_30d: number;
}

export interface AdminUserDetail {
  user: AdminUser;
  limits: Record<string, number>;
  overrides: Record<string, number | null>;
  usage: Record<string, number>;
  storage_used_mb: number;
  graph: Record<string, number>;
  files: StoredFile[];
}

export interface UsageSeries {
  points: { bucket: string; messages: number; tokens: number; uploads: number }[];
  totals: Record<string, number>;
}

export interface SystemStatus {
  version: string;
  neo4j: boolean;
  redis: boolean;
  database: boolean;
  users: number;
  active_users: number;
  threads: number;
  files: number;
  vector_provider: string;
  memory_backend: string;
  default_model: string;
}

export interface GraphSample {
  nodes: { key: string; name: string; type: string; degree: number }[];
  edges: { source: string; target: string; type: string }[];
}

function put(body: unknown): RequestInit {
  return {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const admin = {
  users: (params: { query?: string; status?: string; page?: number; size?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.query) q.set("query", params.query);
    if (params.status) q.set("status", params.status);
    q.set("page", String(params.page ?? 1));
    q.set("size", String(params.size ?? 25));
    return request<{ users: AdminUser[]; total: number; page: number; size: number }>(
      `/admin/users?${q}`,
    );
  },
  user: (id: string) => request<AdminUserDetail>(`/admin/users/${id}`),
  patchUser: (id: string, body: { status?: string; role?: string }) =>
    request<AdminUser>(`/admin/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteUser: (id: string, keepAccount = false) =>
    request<{ tenant_id: string; errors: string[] }>(
      `/admin/users/${id}?keep_account=${keepAccount}`,
      { method: "DELETE" },
    ),
  revokeKeys: (id: string) =>
    request<{ ok: boolean; message: string }>(`/admin/users/${id}/revoke-keys`, {
      method: "POST",
    }),
  resendVerification: (id: string) =>
    request<{ ok: boolean; message: string }>(`/admin/users/${id}/resend-verification`, {
      method: "POST",
    }),
  globalLimits: () => request<Record<string, number>>("/admin/limits"),
  setGlobalLimits: (body: Record<string, number>) =>
    request<Record<string, number>>("/admin/limits", put(body)),
  setUserLimits: (id: string, body: Record<string, number | null>) =>
    request<Record<string, number>>(`/admin/users/${id}/limits`, put(body)),
  clearUserLimits: (id: string) =>
    request<{ ok: boolean }>(`/admin/users/${id}/limits`, { method: "DELETE" }),
  bulkLimits: (body: { set?: Record<string, number>; clear?: boolean }) =>
    request<{ ok: boolean; message: string }>("/admin/limits/bulk", json(body)),
  usage: (days = 30, userId?: string) =>
    request<UsageSeries>(`/admin/usage?days=${days}${userId ? `&user_id=${userId}` : ""}`),
  graph: (id: string) => request<Record<string, number>>(`/admin/users/${id}/graph`),
  graphSample: (id: string, limit = 80) =>
    request<GraphSample>(`/admin/users/${id}/graph/sample?limit=${limit}`),
  system: () => request<SystemStatus>("/admin/system"),
  models: () => request<{ available: ModelOption[]; enabled: string[] }>("/admin/models"),
  setModels: (enabled: string[]) =>
    request<{ available: ModelOption[]; enabled: string[] }>("/admin/models", put({ enabled })),
  audit: (limit = 100) =>
    request<
      {
        id: number;
        action: string;
        actor: string | null;
        target: string | null;
        detail: Record<string, unknown>;
        created_at: string;
      }[]
    >(`/admin/audit?limit=${limit}`),
};
