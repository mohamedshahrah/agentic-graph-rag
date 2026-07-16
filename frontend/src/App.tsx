import { useState } from "react";
import { getUser } from "./api";
import Chat from "./components/Chat";
import Controls from "./components/Controls";
import StatusBar from "./components/StatusBar";
import Upload from "./components/Upload";
import UserBar from "./components/UserBar";

export default function App() {
  const [style, setStyle] = useState("detailed");
  const [user, setUser] = useState(getUser());

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-3 bg-slate-100 p-4">
      <header className="space-y-2">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">Agentic Graph RAG</h1>
            <p className="text-xs text-slate-500">
              Hybrid knowledge-graph + vector retrieval, answered by a tool-using agent.
            </p>
          </div>
          <Controls style={style} onStyle={setStyle} />
        </div>
        <div className="flex items-center justify-between">
          <StatusBar />
          <UserBar user={user} onChange={setUser} />
        </div>
      </header>

      {/* Remount Upload + Chat when the user switches, so state resets to the new namespace. */}
      <Upload key={`upload-${user}`} />

      <main className="flex-1 overflow-hidden rounded-2xl bg-slate-50 p-3 ring-1 ring-slate-200">
        <Chat key={`chat-${user}`} style={style} />
      </main>
    </div>
  );
}
