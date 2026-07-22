import { useEffect, useState } from "react";
import { BarList } from "../components/Chart";
import { Card } from "../components/Stat";
import { api } from "../lib/api";
import { cost } from "../lib/format";

export default function Cost({ refresh }: { refresh: number }) {
  const [users, setUsers] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);

  useEffect(() => {
    api.costUsers().then((d) => setUsers(d.users || [])).catch(() => {});
    api.costModels().then((d) => setModels(d.models || [])).catch(() => {});
  }, [refresh]);

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Card title="Cost by user">
        <BarList
          items={users.map((u) => ({ label: u.user_id, value: Number(u.cost_usd) }))}
          format={cost}
        />
      </Card>
      <Card title="Cost by model">
        <BarList
          items={models.map((m) => ({ label: m.model || "(unknown)", value: Number(m.cost_usd) }))}
          format={cost}
        />
      </Card>
    </div>
  );
}
