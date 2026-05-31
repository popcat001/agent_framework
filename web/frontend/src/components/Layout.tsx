import { useEffect, useRef, useState } from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import { api } from "../services/api";
import { Sidebar } from "./Sidebar";
import { TabBar, extraPages } from "./TabBar";
import { WelcomeScreen } from "./WelcomeScreen";
import { ChatView } from "./ChatView";
import { ChatInput } from "./ChatInput";
import AdminAccessPage from "./AdminAccessPage";
import type { AgentInfo, ChatMessage, Conversation } from "../types";

export function Layout() {
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState("chat");
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const { messages, isStreaming, error, sessionExpired, sendMessage, setMessages, lastConversationId, lastAgentId } =
    useWebSocket();

  // Load agent registry once.
  useEffect(() => {
    api
      .listAgents()
      .then((list) => {
        setAgents(list);
        const def = list.find((a) => a.default) ?? list[0];
        if (def) setSelectedAgentId((cur) => cur ?? def.id);
      })
      .catch(console.error);
  }, []);

  // The conversation drives which agent the user is targeting. While there's
  // no active conversation (welcome screen / new chat), the user picks via
  // the AGENTS section. After a conversation is opened, that conversation's
  // agent_id wins so the sidebar selection follows the thread.
  const defaultAgentId = agents.find((a) => a.default)?.id ?? agents[0]?.id ?? null;
  const effectiveAgentId = activeConversation
    ? activeConversation.agent_id ?? defaultAgentId
    : selectedAgentId;

  const handleSend = (content: string) => {
    sendMessage(content, activeConversation?.id || null, effectiveAgentId);
  };

  const handleSelectConversation = async (conv: Conversation) => {
    if (conv.id === activeConversation?.id) return;
    if (isStreaming) return;
    setActiveConversation(conv);
    if (conv.agent_id) setSelectedAgentId(conv.agent_id);
    setMessages([]);
    try {
      const detail = await api.getConversation(conv.id);
      const loaded: ChatMessage[] = detail.messages.map((m) => ({
        id: m.id,
        role: m.role,
        text: m.content?.text || "",
        tools: m.content?.charts?.map((c: { name: string; chart_url: string }) => ({
          name: c.name,
          status: "completed" as const,
          chart_url: c.chart_url,
        })),
        dbId: m.id,
        feedback: (m.feedback as "up" | "down" | null | undefined) ?? null,
      }));
      setMessages(loaded);
    } catch (err) {
      console.error("Failed to load conversation:", err);
    }
  };

  const handleNewChat = () => {
    if (isStreaming) return;
    setActiveConversation(null);
    setMessages([]);
  };

  const handleSelectAgent = (agentId: string) => {
    if (isStreaming) return;
    setSelectedAgentId(agentId);
    // Switching agent always starts a fresh chat — agents are fixed at
    // creation, so we can't repurpose the active conversation.
    if (activeConversation) {
      setActiveConversation(null);
      setMessages([]);
    }
  };

  const handleSampleQuestion = (question: string) => {
    handleSend(question);
  };

  // Per-message FIFO so rapid toggles (up → down → up) can't reorder on the
  // wire. Each click awaits the previous PATCH for the same message before
  // firing, so the server sees clicks in submission order regardless of
  // network jitter.
  const feedbackQueue = useRef<Map<string, Promise<unknown>>>(new Map());

  const handleFeedback = (dbId: string, rating: "up" | "down" | null) => {
    const convId = activeConversation?.id ?? lastConversationId;
    if (!convId) return;

    // Capture the prior rating for *this message only* so rollback on
    // failure can't resurrect a stale conversation. Functional update +
    // targeted map means it's a no-op if the user has since navigated.
    let prevFeedback: "up" | "down" | null = null;
    setMessages((prev) => {
      const target = prev.find((m) => m.dbId === dbId);
      if (target) prevFeedback = target.feedback ?? null;
      return prev.map((m) =>
        m.dbId === dbId ? { ...m, feedback: rating } : m,
      );
    });

    const prevInFlight = feedbackQueue.current.get(dbId) ?? Promise.resolve();
    const next = prevInFlight
      .catch(() => {}) // a failed earlier PATCH must not block later ones
      .then(() => api.setMessageFeedback(convId, dbId, rating));
    feedbackQueue.current.set(dbId, next);
    next.catch((err) => {
      console.error("Failed to save feedback:", err);
      // Skip rollback if the user has already queued a newer click for this
      // message — that click's optimistic state is what they want, and
      // reverting would clobber it.
      if (feedbackQueue.current.get(dbId) !== next) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.dbId === dbId ? { ...m, feedback: prevFeedback } : m,
        ),
      );
    });
  };

  // Update conversations list when a new conversation is created via WebSocket
  useEffect(() => {
    if (lastConversationId && !activeConversation) {
      const existing = conversations.find((c) => c.id === lastConversationId);
      if (!existing) {
        const newConv: Conversation = {
          id: lastConversationId,
          title: messages.find((m) => m.role === "user")?.text.slice(0, 100) || "New conversation",
          agent_id: lastAgentId ?? selectedAgentId ?? null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        setConversations((prev) => [newConv, ...prev]);
        setActiveConversation(newConv);
      }
    }
  }, [lastConversationId]);

  const hasMessages = messages.length > 0;
  const isChatTab = activeTab === "chat";
  const showSidebar = (isChatTab || activeTab === "admin") && sidebarOpen;

  // A page that renders its own sidebar (e.g. Reports) gets the shared TabBar
  // and the sidebarOpen flag so it can build chat-identical chrome itself —
  // its sidebar reaches the top with the TabBar only over the content.
  const activePage = extraPages.find((p) => p.id === activeTab);
  const pageOwnsSidebar = !!activePage?.ownsSidebar;
  const tabBar = (
    <TabBar
      activeTab={activeTab}
      onTabChange={setActiveTab}
      sidebarOpen={sidebarOpen}
      onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
    />
  );

  return (
    <div className="flex h-screen" style={{ background: "var(--bg-primary)" }}>
      {sessionExpired && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0, 0, 0, 0.5)" }}
        >
          <div
            className="max-w-sm w-full mx-4 p-6 rounded-lg shadow-lg"
            style={{ background: "var(--bg-secondary, white)", color: "var(--text-primary, #111)" }}
          >
            <h2 className="text-lg font-semibold mb-2">Session expired</h2>
            <p className="text-sm mb-4" style={{ color: "var(--text-secondary, #555)" }}>
              Your sign-in session has ended. Refresh the page to sign back in.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="w-full py-2 px-4 rounded font-medium"
              style={{ background: "var(--accent, #e1330a)", color: "white" }}
            >
              Refresh
            </button>
          </div>
        </div>
      )}
      {showSidebar && (
        <Sidebar
          conversations={conversations}
          activeConversation={activeConversation}
          onSelectConversation={(c) => {
            setActiveTab("chat");
            handleSelectConversation(c);
          }}
          onNewChat={() => {
            setActiveTab("chat");
            handleNewChat();
          }}
          setConversations={setConversations}
          agents={agents}
          selectedAgentId={effectiveAgentId}
          onSelectAgent={(id) => {
            setActiveTab("chat");
            handleSelectAgent(id);
          }}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
      )}

      {pageOwnsSidebar && activePage ? (
        // The page owns its full chrome: it renders its own sidebar (reaching
        // the top) plus the shared TabBar above its content.
        (() => {
          const PageComponent = activePage.component;
          return <PageComponent tabBar={tabBar} sidebarOpen={sidebarOpen} />;
        })()
      ) : (
        <div className="flex flex-col flex-1 min-w-0">
          {tabBar}

          <div className="flex-1 flex flex-col min-h-0">
            {activeTab === "chat" ? (
              <>
                {hasMessages ? (
                  <ChatView messages={messages} isStreaming={isStreaming} error={error} onFeedback={handleFeedback} />
                ) : (
                  <WelcomeScreen
                    onSelectQuestion={handleSampleQuestion}
                    agent={agents.find((a) => a.id === effectiveAgentId) ?? null}
                  />
                )}
                <ChatInput onSend={handleSend} isStreaming={isStreaming} />
              </>
            ) : activeTab === "admin" ? (
              <AdminAccessPage onBack={() => setActiveTab("chat")} />
            ) : activePage ? (
              (() => {
                const PageComponent = activePage.component;
                return <PageComponent />;
              })()
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <p style={{ color: "var(--text-secondary)" }}>Page not found</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
