import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { admin, type AdminUser } from "../../api";
import { Alert, Badge, Button, Card, Input, Select, Skeleton } from "../../components/ui";

const STATUS_TONE = {
  active: "positive",
  pending: "caution",
  suspended: "danger",
} as const;

export default function Users() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const size = 25;

  useEffect(() => {
    // Debounced so typing a search doesn't fire a request per keystroke.
    const timer = setTimeout(async () => {
      try {
        const data = await admin.users({ query, status, page, size });
        setUsers(data.users);
        setTotal(data.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load users.");
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query, status, page]);

  const pages = Math.max(1, Math.ceil(total / size));

  return (
    <div className="space-y-4">
      {error && <Alert>{error}</Alert>}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <Input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search by email"
            className="pl-9"
          />
        </div>
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="w-auto"
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="pending">Pending</option>
          <option value="suspended">Suspended</option>
        </Select>
      </div>

      <Card padded={false} className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="border-b border-border bg-raised/50 text-[12px] text-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">User</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 text-right font-medium">Docs</th>
                <th className="px-4 py-2.5 text-right font-medium">Chats</th>
                <th className="px-4 py-2.5 text-right font-medium">Msgs (30d)</th>
                <th className="px-4 py-2.5 text-right font-medium">Tokens (30d)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users === null ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i}>
                    <td className="px-4 py-3" colSpan={6}>
                      <Skeleton className="h-4 w-full" />
                    </td>
                  </tr>
                ))
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-muted">
                    No users match.
                  </td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.id} className="transition-colors hover:bg-raised/40">
                    <td className="px-4 py-2.5">
                      <Link
                        to={`/admin/users/${user.id}`}
                        className="font-medium text-strong hover:text-accent"
                      >
                        {user.email}
                      </Link>
                      {user.role === "admin" && (
                        <span className="ml-2">
                          <Badge tone="accent">admin</Badge>
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={STATUS_TONE[user.status as keyof typeof STATUS_TONE]}>
                        {user.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12px] text-muted">
                      {user.files}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12px] text-muted">
                      {user.threads}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12px] text-muted">
                      {user.messages_30d.toLocaleString()}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-[12px] text-muted">
                      {user.tokens_30d.toLocaleString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {pages > 1 && (
        <div className="flex items-center justify-between text-[13px] text-muted">
          <span>
            Page {page} of {pages} · {total} users
          </span>
          <div className="flex gap-2">
            <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Button size="sm" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
