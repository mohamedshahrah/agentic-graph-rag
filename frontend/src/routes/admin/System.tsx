import clsx from "clsx";
import { useEffect, useState } from "react";

import { admin, type ModelOption, type SystemStatus } from "../../api";
import { Alert, Badge, Button, Card, CardTitle, Skeleton } from "../../components/ui";

export default function System() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [models, setModels] = useState<{ available: ModelOption[]; enabled: string[] } | null>(
    null,
  );
  const [audit, setAudit] = useState<Awaited<ReturnType<typeof admin.audit>> | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [s, m, a] = await Promise.all([admin.system(), admin.models(), admin.audit(25)]);
        setStatus(s);
        setModels(m);
        setAudit(a);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load system status.");
      }
    })();
  }, []);

  async function toggleModel(id: string) {
    if (!models) return;
    const next = models.enabled.includes(id)
      ? models.enabled.filter((m) => m !== id)
      : [...models.enabled, id];
    if (next.length === 0) {
      setError("At least one model must stay enabled.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      setModels(await admin.setModels(next));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update models.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert>{error}</Alert>}

      <Card>
        <CardTitle>Services</CardTitle>
        {!status ? (
          <Skeleton className="h-20 w-full" />
        ) : (
          <div className="grid gap-4 sm:grid-cols-3">
            <Service name="Postgres" up={status.database} />
            <Service name="Neo4j" up={status.neo4j} />
            <Service name="Redis" up={status.redis} />
          </div>
        )}
      </Card>

      <Card>
        <CardTitle>Configuration</CardTitle>
        {!status ? (
          <Skeleton className="h-20 w-full" />
        ) : (
          <dl className="grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-2">
            <Row label="Version" value={status.version} />
            <Row label="Default model" value={status.default_model} />
            <Row label="Vector store" value={status.vector_provider} />
            <Row label="Agent memory" value={status.memory_backend} />
          </dl>
        )}
      </Card>

      <Card>
        <CardTitle>Available models</CardTitle>
        <p className="mb-4 text-[13px] text-muted">
          Which models users can choose in chat. Disabling one hides it from the
          picker; requests naming it fall back to the default.
        </p>
        {!models ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <ul className="space-y-1.5">
            {models.available.map((m) => {
              const on = models.enabled.includes(m.model);
              return (
                <li
                  key={m.model}
                  className="flex items-center gap-3 rounded-md px-2.5 py-2 ring-1 ring-border"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-medium text-strong">{m.label}</p>
                    <p className="font-mono text-[11px] text-muted">
                      {m.provider} · {m.model}
                    </p>
                  </div>
                  <Button size="sm" onClick={() => toggleModel(m.model)} disabled={saving}>
                    {on ? "Enabled" : "Disabled"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card>
        <CardTitle>Recent admin actions</CardTitle>
        {!audit ? (
          <Skeleton className="h-24 w-full" />
        ) : audit.length === 0 ? (
          <p className="py-8 text-center text-[13px] text-muted">Nothing yet.</p>
        ) : (
          <ul className="divide-y divide-border text-[13px]">
            {audit.map((entry) => (
              <li key={entry.id} className="flex items-baseline gap-3 py-2">
                <code className="shrink-0 font-mono text-[12px] text-accent">
                  {entry.action}
                </code>
                <span className="min-w-0 flex-1 truncate text-muted">
                  {JSON.stringify(entry.detail)}
                </span>
                <span className="shrink-0 text-[11px] text-muted">
                  {new Date(entry.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Service({ name, up }: { name: string; up: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span
        className={clsx("h-2 w-2 rounded-full", up ? "bg-positive" : "bg-danger")}
        aria-hidden
      />
      <span className="text-[13px] text-body">{name}</span>
      <Badge tone={up ? "positive" : "danger"}>{up ? "up" : "down"}</Badge>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-border py-1.5 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="font-mono text-[12px] text-strong">{value || "—"}</dd>
    </div>
  );
}
