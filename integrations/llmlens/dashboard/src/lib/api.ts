// API client. Dashboard reads are admin-gated (X-Admin-Key) and scoped by a
// project_id + time window (hours), all persisted in localStorage.

const API = "/api";

let adminKey = localStorage.getItem("llmlens_admin") || "";
let projectId = localStorage.getItem("llmlens_project") || "default";
let hours = Number(localStorage.getItem("llmlens_hours") || "24");

export function getAdminKey() { return adminKey; }
export function setAdminKey(v: string) { adminKey = v; localStorage.setItem("llmlens_admin", v); }
export function getProject() { return projectId; }
export function setProject(v: string) { projectId = v || "default"; localStorage.setItem("llmlens_project", projectId); }
export function getHours() { return hours; }
export function setHours(v: number) { hours = v; localStorage.setItem("llmlens_hours", String(v)); }

function headers(json = false): Record<string, string> {
  const h: Record<string, string> = {};
  if (adminKey) h["X-Admin-Key"] = adminKey;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

async function get(path: string, params: Record<string, string> = {}) {
  const url = new URL(API + path, location.origin);
  url.searchParams.set("project_id", projectId);
  url.searchParams.set("hours", String(hours));
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const res = await fetch(url.toString(), { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

async function send(method: string, path: string, body?: unknown) {
  const res = await fetch(API + path, {
    method,
    headers: headers(body !== undefined),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

const post = (path: string, body: unknown) => send("POST", path, body);

export const api = {
  overview: () => get("/metrics/overview"),
  timeseries: () => get("/metrics/timeseries"),
  costUsers: () => get("/metrics/cost/users"),
  costModels: () => get("/metrics/cost/models"),
  errors: () => get("/metrics/errors"),
  traces: (p: Record<string, string> = {}) => get("/traces", p),
  trace: (id: string) => get(`/traces/${id}`),
  alertRules: () => get("/alerts/rules"),
  alertEvents: () => get("/alerts/events"),
  createRule: (r: unknown) => post("/alerts/rules", r),
  createChannel: (c: unknown) => post("/alerts/channels", c),
  toggleRule: (id: number, enabled: boolean) => send("PATCH", `/alerts/rules/${id}`, { enabled }),
  deleteRule: (id: number) => send("DELETE", `/alerts/rules/${id}`),
};
