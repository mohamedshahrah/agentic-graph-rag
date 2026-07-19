import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { auth, type ApiKeyInfo, type LimitsInfo } from "../api";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardTitle,
  EmptyState,
  Input,
  Meter,
  Modal,
  Skeleton,
} from "../components/ui";
import { useAuth } from "../lib/auth";

export default function Account() {
  const { me } = useAuth();
  const [info, setInfo] = useState<LimitsInfo | null>(null);
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [newKey, setNewKey] = useState("");
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    try {
      const [limits, keyList] = await Promise.all([auth.limits(), auth.listKeys()]);
      setInfo(limits);
      setKeys(keyList.keys);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load your account.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function createKey() {
    setCreating(true);
    try {
      const created = await auth.createKey(label);
      setNewKey(created.api_key);
      setLabel("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the key.");
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: number) {
    await auth.revokeKey(id);
    await load();
  }

  const limits = info?.limits ?? {};
  const usage = info?.usage ?? {};

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-8">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-strong">Account</h1>
          <p className="mt-1 text-[13px] text-muted">{me?.email}</p>
        </div>

        {error && <Alert>{error}</Alert>}

        <Card>
          <CardTitle
            action={
              me?.role === "admin" ? <Badge tone="accent">admin</Badge> : undefined
            }
          >
            Usage
          </CardTitle>
          {!info ? (
            <div className="space-y-4">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2">
              <Meter
                label="Messages today"
                used={usage.messages_today ?? 0}
                max={limits.messages_per_day ?? 0}
              />
              <Meter
                label="Tokens today"
                used={usage.tokens_today ?? 0}
                max={limits.tokens_per_day ?? 0}
              />
              <Meter
                label="Documents"
                used={info.files_used}
                max={limits.max_files ?? 0}
              />
              <Meter
                label="Storage"
                used={Math.round(info.storage_used_mb)}
                max={limits.max_storage_mb ?? 0}
                unit=" MB"
              />
              <Meter
                label="Conversations"
                used={info.threads_used}
                max={limits.max_threads ?? 0}
              />
              <Meter
                label="Tokens this month"
                used={usage.tokens_this_month ?? 0}
                max={limits.tokens_per_month ?? 0}
              />
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>API keys</CardTitle>
          <p className="mb-4 text-[13px] text-muted">
            For scripts and integrations. A key carries your identity and your
            limits — treat it like a password.
          </p>

          <div className="mb-4 flex gap-2">
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="What is this key for?"
              maxLength={64}
            />
            <Button variant="secondary" onClick={createKey} loading={creating}>
              <Plus className="h-3.5 w-3.5" />
              Create
            </Button>
          </div>

          {keys.length === 0 ? (
            <EmptyState
              icon={<KeyRound className="h-5 w-5" />}
              title="No API keys"
              description="Create one to use the API outside this app."
            />
          ) : (
            <ul className="divide-y divide-border">
              {keys.map((key) => (
                <li key={key.id} className="flex items-center gap-3 py-2.5">
                  <KeyRound className="h-3.5 w-3.5 shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] text-body">
                      {key.label || "Untitled key"}
                    </p>
                    <p className="text-[11px] text-muted">
                      Created {formatDate(key.created_at)}
                      {key.last_used_at
                        ? ` · last used ${formatDate(key.last_used_at)}`
                        : " · never used"}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => revoke(key.id)}
                    aria-label="Revoke key"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Modal open={Boolean(newKey)} title="Copy your API key" onClose={() => setNewKey("")}>
        <p className="mb-3 text-[13px] text-muted">
          This is the only time it will be shown. Only its hash is stored, so a
          lost key is replaced, never recovered.
        </p>
        <div className="flex gap-2">
          <Input readOnly value={newKey} className="font-mono text-[12px]" />
          <Button
            variant="secondary"
            onClick={() => navigator.clipboard?.writeText(newKey)}
            aria-label="Copy"
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" onClick={() => setNewKey("")}>
            Done
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function formatDate(value: string): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
