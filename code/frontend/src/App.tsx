import { useEffect, useState } from "react";
import { Sidebar } from "./components/layout/Sidebar";
import { AppLayout } from "./components/layout/AppLayout";
import { useSession } from "./hooks/useSession";
import { useExtraction } from "./hooks/useExtraction";
import { useGraph } from "./hooks/useGraph";
import { HomePage} from "./pages/HomePage";
import { ChatPage} from "./pages/ChatPage";
import { ExtractionPage} from "./pages/ExtractionPage";
import { GraphPage} from "./pages/GraphPage";


import type { AppView } from "./types";

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [view, setView] = useState<AppView>("home");

  const session = useSession();
  const extraction = useExtraction(sessionId);
  const graph = useGraph(sessionId);

  // After session creation, switch to chat automatically
  const handleCreateSession = async (domain: string) => {
    const id = await session.createSession(domain);
    if (id) {
      setSessionId(id);
      setView("chat");
    }
  };

  // After freezing, offer to go to extraction
  const handleFreeze = async () => {
    if (!sessionId) return;
    const schema = await session.freezeSchema(sessionId);
    if (schema) setView("extraction");
  };

  const frozen = session.schema?.frozen ?? false;
  const extractionDone = extraction.status.status === "done";

  // Load graph when switching to graph view
  useEffect(() => {
    if (view === "graph" && sessionId) {
      graph.loadGraph();
      graph.loadUtilization();
    }
  }, [view, sessionId]);

  return (
    <AppLayout
      sidebar={
        <Sidebar
          sessionId={sessionId}
          currentView={view}
          onNavigate={setView}
          frozen={frozen}
          extractionDone={extractionDone}
          schema={session.schema}
        />
      }
    >
      {view === "home" && (
        <HomePage
          onSessionCreated={setSessionId}
          loading={session.loading}
          error={session.error}
          onCreate={handleCreateSession}
        />
      )}

      {view === "chat" && sessionId && (
        <ChatPage
          sessionId={sessionId}
          schema={session.schema}
          turns={session.turns}
          deltaHistory={session.deltaHistory}
          loading={session.loading}
          frozen={frozen}
          converged={false}
          error={session.error}
          onSend={(msg) => session.sendMessage(sessionId, msg)}
          onFreeze={handleFreeze}
        />
      )}

      {view === "extraction" && sessionId && (
        <ExtractionPage
          schema={session.schema}
          extractionStatus={extraction.status}
          extractionError={extraction.error}
          onStartExtraction={extraction.startExtraction}
        />
      )}

      {view === "graph" && sessionId && (
        <GraphPage
          nodes={graph.nodes}
          edges={graph.edges}
          utilization={graph.utilization}
          loading={graph.loading}
          onLoad={graph.loadGraph}
          onLoadUtilization={graph.loadUtilization}
        />
      )}
    </AppLayout>
  );
}