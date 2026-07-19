import { ArrowLeft, KeyRound, Mail, Trash2 } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { admin, type AdminUserDetail, type GraphSample } from "../../api";
import { LimitsForm } from "../../components/admin/LimitsForm";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardTitle,
  Modal,
  Skeleton,
} from "../../components/ui";

// The graph view pulls in d3-force; it's admin-only and below the fold, so it
// shouldn't sit in the main bundle.
const GraphView = lazy(() =>
  import("../../components/admin/GraphView").then((m) => ({ default: m.GraphView })),
);

export default function UserDetail() {
  const { userId = "" } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [graph, setGraph] = useState<GraphSample | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await admin.user(userId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this user.");
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    admin.graphSample(userId).then(setGraph).catch(() => setGraph({ nodes: [], edges: [] }));
  }, [userId]);

  async function act(fn: () => Promise<{ message?: string } | unknown>, done: string) {
    setError("");
    setNotice("");
    try {
      const result = (await fn()) as { message?: string };
      setNotice(result?.message ?? done);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That didn't work.");
    }
  }

  if (!detail) {
    return (
      <div className="space-y-3">
        {error && <Alert>{error}</Alert>}
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const { user, limits, overrides, graph: stats } = detail;
  const suspended = user.status === "suspended";

  return (
    <div className="space-y-4">
      <Link
        to="/admin/users"
        className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-body"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        All users
      </Link>

      {error && <Alert>{error}</Alert>}
      {notice && <Alert tone="positive">{notice}</Alert>}

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold text-strong">{user.email}</h1>
              <Badge tone={suspended ? "danger" : user.status === "active" ? "positive" : "caution"}>
                {user.status}
              </Badge>
              {user.role === "admin" && <Badge tone="accent">admin</Badge>}
            </div>
            <p className="mt-1 font-mono text-[12px] text-muted">{user.tenant_id}</p>
            <p className="mt-1 text-[12px] text-muted">
              Joined {formatDate(user.created_at)}
              {user.last_login_at ? ` · last seen ${formatDate(user.last_login_at)}` : ""}
              {user.email_verified ? "" : " · email unverified"}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() =>
                act(
                  () =>
                    admin.patchUser(user.id, { status: suspended ? "active" : "suspended" }),
                  suspended ? "User reactivated." : "User suspended.",
                )
              }
            >
              {suspended ? "Reactivate" : "Suspend"}
            </Button>
            <Button
              size="sm"
              onClick={() =>
                act(
                  () => admin.patchUser(user.id, { role: user.role === "admin" ? "user" : "admin" }),
                  "Role updated.",
                )
              }
            >
              {user.role === "admin" ? "Remove admin" : "Make admin"}
            </Button>
            <Button size="sm" onClick={() => act(() => admin.revokeKeys(user.id), "Keys revoked.")}>
              <KeyRound className="h-3.5 w-3.5" />
              Revoke keys
            </Button>
            {!user.email_verified && (
              <Button
                size="sm"
                onClick={() => act(() => admin.resendVerification(user.id), "Code sent.")}
              >
                <Mail className="h-3.5 w-3.5" />
                Resend code
              </Button>
            )}
            <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </Button>
          </div>
        </div>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Documents" value={user.files} />
        <Stat label="Storage" value={`${detail.storage_used_mb} MB`} />
        <Stat label="Conversations" value={user.threads} />
        <Stat label="Messages (30d)" value={user.messages_30d} />
        <Stat label="Chunks indexed" value={stats.chunks ?? 0} />
        <Stat label="Entities" value={stats.entities ?? 0} />
        <Stat label="Relations" value={stats.relations ?? 0} />
        <Stat label="Communities" value={stats.communities ?? 0} />
      </div>

      <Card>
        <CardTitle>Limits</CardTitle>
        <LimitsForm
          mode="override"
          values={overrides}
          inherited={limits}
          saving={saving}
          onSave={async (values) => {
            setSaving(true);
            await act(() => admin.setUserLimits(user.id, values), "Limits updated.");
            setSaving(false);
          }}
          onClear={() =>
            act(() => admin.clearUserLimits(user.id), "Overrides cleared.")
          }
        />
      </Card>

      <Card>
        <CardTitle>Knowledge graph</CardTitle>
        {graph === null ? (
          <Skeleton className="h-56 w-full" />
        ) : (
          <Suspense fallback={<Skeleton className="h-56 w-full" />}>
            <GraphView sample={graph} />
          </Suspense>
        )}
      </Card>

      <Modal
        open={confirmDelete}
        title={`Delete ${user.email}?`}
        onClose={() => setConfirmDelete(false)}
      >
        <p className="text-[13px] text-muted">
          This removes their account, conversations, documents, vectors and graph.
          It cannot be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button
            variant="danger"
            onClick={async () => {
              await admin.deleteUser(user.id);
              navigate("/admin/users", { replace: true });
            }}
          >
            Delete everything
          </Button>
        </div>
      </Modal>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <Card>
      <p className="text-[12px] text-muted">{label}</p>
      <p className="mt-1 text-xl font-semibold tracking-tight text-strong">
        {typeof value === "number" ? value.toLocaleString() : value}
      </p>
    </Card>
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
