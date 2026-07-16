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

export async function streamQuery(
  question: string,
  style: string,
  threadId: string,
  onToken: (t: string) => void,
  onSources: (s: Source[]) => void,
): Promise<void> {
  const res = await fetch(`${API}/query`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question, style, thread_id: threadId, stream: true }),
  });
  if (!res.body) throw new Error("No response stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const raw of events) {
      const { event, data } = parseEvent(raw);
      if (event === "token") onToken(data);
      else if (event === "sources") onSources(JSON.parse(data) as Source[]);
      else if (event === "error") throw new Error(data);
    }
  }
}

function parseEvent(raw: string): { event: string; data: string } {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  return { event, data: dataLines.join("\n") };
}

export async function uploadFile(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API}/ingest/upload`, { method: "POST", headers: headers(), body: form });
  return res.json();
}

export async function ingestStatus(jobId: string) {
  const res = await fetch(`${API}/ingest/${jobId}`, { headers: headers() });
  return res.json();
}

export interface Ready {
  ready: boolean;
  neo4j: boolean;
  redis: boolean;
}

export async function getReady(): Promise<Ready> {
  const res = await fetch(`${API}/ready`, { headers: headers() });
  return res.json();
}

export async function getHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${API}/health`, { headers: headers() });
  return res.json();
}

export async function listUsers(): Promise<{ users: string[] }> {
  const res = await fetch(`${API}/users`, { headers: headers() });
  return res.json();
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
  return res.json();
}
