import { useState } from "react";
import Layout from "./components/Layout";
import { getAdminKey, getHours, getProject, setAdminKey, setHours, setProject } from "./lib/api";
import Alerts from "./pages/Alerts";
import Cost from "./pages/Cost";
import Errors from "./pages/Errors";
import Overview from "./pages/Overview";
import Traces from "./pages/Traces";

export default function App() {
  const [view, setView] = useState("overview");
  const [refresh, setRefresh] = useState(0);
  const [project, setProjectState] = useState(getProject());
  const [hours, setHoursState] = useState(getHours());
  const [adminKey, setAdminKeyState] = useState(getAdminKey());

  const bump = () => setRefresh((r) => r + 1);

  return (
    <Layout
      view={view}
      onView={setView}
      project={project}
      hours={hours}
      adminKey={adminKey}
      onProject={(v) => { setProjectState(v); setProject(v); bump(); }}
      onHours={(v) => { setHoursState(v); setHours(v); bump(); }}
      onAdminKey={(v) => { setAdminKeyState(v); setAdminKey(v); bump(); }}
      onRefresh={bump}
    >
      {view === "overview" && <Overview refresh={refresh} />}
      {view === "traces" && <Traces refresh={refresh} />}
      {view === "cost" && <Cost refresh={refresh} />}
      {view === "errors" && <Errors refresh={refresh} />}
      {view === "alerts" && <Alerts refresh={refresh} />}
    </Layout>
  );
}
