import { useEffect, useState } from "react";
import {
  createUser,
  getApiKey,
  getUser,
  listUsers,
  setApiKey,
  setUser as apiSetUser,
} from "../api";

// Pick or create a user. Each user has a fully isolated knowledge base.
// The API-key field is only needed when the server has auth enabled; when a new
// user is created in that mode, its key is returned once and stored here.
export default function UserBar({ user, onChange }: { user: string; onChange: (u: string) => void }) {
  const [users, setUsers] = useState<string[]>([getUser()]);
  const [newName, setNewName] = useState("");
  const [apiKey, setKey] = useState(getApiKey());
  const [note, setNote] = useState("");

  useEffect(() => {
    listUsers()
      .then((r) => setUsers(r.users.length ? r.users : [getUser()]))
      .catch(() => {});
  }, []);

  function select(u: string) {
    apiSetUser(u);
    onChange(u);
  }

  function saveKey(k: string) {
    setKey(k);
    setApiKey(k);
  }

  async function add() {
    const name = newName.trim();
    if (!name) return;
    try {
      const r = await createUser(name, apiKey || undefined);
      setUsers((prev) => Array.from(new Set([...prev, r.user_id])));
      setNewName("");
      if (r.api_key) {
        saveKey(r.api_key);
        setNote("New API key saved — copy it now, it won't be shown again.");
      }
      select(r.user_id);
    } catch (err) {
      // A 403 here used to select a user literally named "undefined".
      setNote(`Could not create user: ${String((err as Error).message ?? err)}`);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-slate-500">User</span>
        <select
          value={user}
          onChange={(e) => select(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-2 py-1"
        >
          {users.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="new user"
          className="w-24 rounded-lg border border-slate-300 px-2 py-1"
        />
        <button
          onClick={add}
          className="rounded-lg bg-slate-100 px-2 py-1 ring-1 ring-slate-200 hover:bg-slate-200"
        >
          + add
        </button>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => saveKey(e.target.value)}
          placeholder="API key (if required)"
          className="w-32 rounded-lg border border-slate-300 px-2 py-1"
        />
      </div>
      {note && <span className="text-amber-600">{note}</span>}
    </div>
  );
}
