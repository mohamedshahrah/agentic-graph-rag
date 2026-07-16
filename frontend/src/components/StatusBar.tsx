import { useEffect, useState } from "react";
import { getHealth, getReady, type Ready } from "../api";

// Polls the API so the whole stack's health is visible in the browser.
export default function StatusBar() {
  const [ready, setReady] = useState<Ready | null>(null);
  const [version, setVersion] = useState("");
  const [apiUp, setApiUp] = useState(false);

  useEffect(() => {
    getHealth()
      .then((h) => {
        setVersion(h.version);
        setApiUp(true);
      })
      .catch(() => setApiUp(false));

    const tick = () =>
      getReady()
        .then((r) => {
          setReady(r);
          setApiUp(true);
        })
        .catch(() => {
          setApiUp(false);
          setReady(null);
        });

    tick();
    const t = setInterval(tick, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex items-center gap-3 text-xs">
      <Dot ok={apiUp} label="API" />
      <Dot ok={!!ready?.neo4j} label="Neo4j" />
      <Dot ok={!!ready?.redis} label="Redis" />
      {version && <span className="text-slate-400">v{version}</span>}
    </div>
  );
}

function Dot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-green-500" : "bg-red-400"}`} />
      <span className="text-slate-500">{label}</span>
    </span>
  );
}
