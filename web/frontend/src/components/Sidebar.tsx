import { useEffect, useState } from "react";
import { SquarePen, Search, Bot, Shield } from "lucide-react";
import { resolveIcon } from "../config/iconRegistry";
import { useAuth } from "../contexts/AuthContext";
import { useAdmin } from "../hooks/useAdmin";
import { api } from "../services/api";
import { project } from "../config/project";
import { ConversationList } from "./ConversationList";
import { ResizableSidebar } from "./ResizableSidebar";
import type { AgentInfo, Conversation } from "../types";

/** Resolve a Lucide icon by its string name (from agent.yaml `icon` field).
 *  Falls back to <Bot> when the name is missing or not a registered icon. */
function AgentIcon({ name, size = 14 }: { name: string | null; size?: number }) {
  const Icon = resolveIcon(name) ?? Bot;
  return <Icon size={size} />;
}

interface SidebarProps {
  conversations: Conversation[];
  activeConversation: Conversation | null;
  onSelectConversation: (conv: Conversation) => void;
  onNewChat: () => void;
  setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>;
  agents: AgentInfo[];
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string) => void;
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export function Sidebar({
  conversations,
  activeConversation,
  onSelectConversation,
  onNewChat,
  setConversations,
  agents,
  selectedAgentId,
  onSelectAgent,
  activeTab,
  onTabChange,
}: SidebarProps) {
  const { user } = useAuth();
  const { me: adminMe } = useAdmin();
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    api
      .listConversations()
      .then(setConversations)
      .catch(console.error);
  }, [setConversations]);

  // Filter conversations by selected agent (treat NULL agent_id as the
  // default agent — old conversations created before agents existed).
  const defaultAgentId = agents.find((a) => a.default)?.id ?? agents[0]?.id ?? null;
  const agentScopedConversations = selectedAgentId
    ? conversations.filter((c) => (c.agent_id ?? defaultAgentId) === selectedAgentId)
    : conversations;

  const filteredConversations = searchQuery
    ? agentScopedConversations.filter((c) =>
        c.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : agentScopedConversations;

  const handleDelete = async (id: string) => {
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeConversation?.id === id) {
        onNewChat();
      }
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    }
  };

  return (
    <ResizableSidebar storageKey="sidebar-width:chat">
    <div
      className="w-full flex flex-col h-full border-r"
      style={{ background: "var(--bg-sidebar)", borderColor: "var(--border)" }}
    >
      {/* Xi Logo - top left */}
      <div className="px-4 pt-4">
        <img src={project.orgLogo} alt="Org Logo" className="h-12 w-auto" />
      </div>

      {/* Logo — fixed-height crop box hides the transparent padding baked
          into the PNG without shrinking the owl/wordmark itself. */}
      <div
        className="flex justify-center overflow-hidden"
        style={{ height: 44 }}
      >
        <img
          src={project.appLogo}
          alt={project.name}
          className="h-16 w-auto"
          style={{ marginTop: -10 }}
        />
      </div>

      {/* Header */}
      <div className="p-4">
        <button
          onClick={onNewChat}
          className="group flex items-center gap-2.5 w-full pl-3 pr-3 py-2.5 rounded-xl text-sm font-medium cursor-pointer
                     transition-all duration-150
                     bg-white hover:-translate-y-px
                     focus-visible:outline-none focus-visible:ring-2"
          style={{
            color: "var(--text-primary)",
            border: "1px solid var(--border)",
            boxShadow: "0 1px 2px rgba(224, 122, 58, 0.04), 0 1px 1px rgba(0,0,0,0.02)",
            // @ts-expect-error CSS custom property
            "--tw-ring-color": "color-mix(in oklch, var(--accent) 30%, transparent)",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow =
              "0 4px 12px rgba(224, 122, 58, 0.10), 0 1px 2px rgba(0,0,0,0.03)";
            e.currentTarget.style.borderColor =
              "color-mix(in oklch, var(--accent) 35%, var(--border))";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow =
              "0 1px 2px rgba(224, 122, 58, 0.04), 0 1px 1px rgba(0,0,0,0.02)";
            e.currentTarget.style.borderColor = "var(--border)";
          }}
        >
          <span
            className="flex items-center justify-center w-6 h-6 rounded-md transition-colors"
            style={{
              background:
                "color-mix(in oklch, var(--accent) 12%, transparent)",
              color: "var(--accent)",
            }}
          >
            <SquarePen size={13} strokeWidth={2.25} />
          </span>
          <span className="flex-1 text-left">New chat</span>
        </button>
      </div>

      {/* Agents */}
      {agents.length > 0 && (
        <div className="px-4 pt-3 pb-3">
          <div
            className="text-[13px] font-bold tracking-wider uppercase mb-2"
            style={{ color: "var(--text-primary)" }}
          >
            Agents
          </div>
          <div className="flex flex-col gap-1">
            {agents.map((a) => {
              const active = a.id === selectedAgentId;
              return (
                <button
                  key={a.id}
                  onClick={() => onSelectAgent(a.id)}
                  title={a.description}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors cursor-pointer"
                  style={{
                    background: active
                      ? "color-mix(in oklch, var(--accent) 12%, transparent)"
                      : "transparent",
                    color: active ? "var(--accent)" : "var(--text-primary)",
                    border: "1px solid transparent",
                  }}
                  onMouseEnter={(e) => {
                    if (!active)
                      e.currentTarget.style.background =
                        "color-mix(in oklch, var(--accent) 6%, transparent)";
                  }}
                  onMouseLeave={(e) => {
                    if (!active) e.currentTarget.style.background = "transparent";
                  }}
                >
                  <AgentIcon name={a.icon} />
                  <span className="flex-1 truncate font-medium">{a.name}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* History label — divider above visually separates it from the AGENTS
          section. Divider is inset so it doesn't run to the sidebar edges. */}
      <div className="mx-4 mt-2" style={{ borderTop: "1px solid var(--border)" }} />
      <div
        className="pt-3 px-4 pb-2 text-[13px] font-bold tracking-wider uppercase"
        style={{ color: "var(--text-primary)" }}
      >
        History
      </div>

      {/* Search — scopes the conversation list, so it lives inside HISTORY. */}
      <div className="px-4 pb-3">
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg"
          style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
        >
          <Search size={14} style={{ color: "var(--text-secondary)" }} />
          <input
            type="text"
            placeholder="Search conversations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-transparent flex-1 text-sm outline-none placeholder:text-[var(--text-secondary)]"
          />
        </div>
      </div>

      {/* Conversations list */}
      <div className="flex-1 overflow-y-auto px-2">
        <ConversationList
          conversations={filteredConversations}
          activeId={activeConversation?.id || null}
          onSelect={onSelectConversation}
          onDelete={handleDelete}
          agents={agents}
          // Hide the badge when the list is already scoped to one agent —
          // every row would carry the same label.
          showAgentBadge={!selectedAgentId && agents.length > 1}
        />
      </div>

      {/* Manage access — admin-only. Divider inset to match History. */}
      {adminMe?.is_admin && (
        <>
          <div className="mx-4 mt-2" style={{ borderTop: "1px solid var(--border)" }} />
        <div className="px-2 pt-2 pb-2">
          <button
            onClick={() => onTabChange("admin")}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left w-full cursor-pointer transition-colors"
            style={{
              // Match the mockup: always tinted accent-light background so
              // the admin entry visibly stands apart from regular nav rows.
              background:
                activeTab === "admin"
                  ? "color-mix(in oklch, var(--accent) 18%, transparent)"
                  : "color-mix(in oklch, var(--accent) 9%, transparent)",
              color: "var(--accent)",
              fontWeight: 500,
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background =
                "color-mix(in oklch, var(--accent) 14%, transparent)")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.background =
                activeTab === "admin"
                  ? "color-mix(in oklch, var(--accent) 18%, transparent)"
                  : "color-mix(in oklch, var(--accent) 9%, transparent)")
            }
            title={
              adminMe.is_super_admin
                ? "Manage Access for all agents"
                : `Manage Access for ${adminMe.managed_agents.map((a) => a.name).join(", ")}`
            }
          >
            <Shield size={14} />
            <span className="flex-1 truncate">Manage Access</span>
          </button>
        </div>
        </>
      )}

      {/* User profile — admins get an ADMIN/SUPER pill next to the name. */}
      <div className="mx-4" style={{ borderTop: "1px solid var(--border)" }} />
      <div
        className="p-4 flex items-center gap-3"
      >
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium text-white flex-shrink-0"
          style={{ background: "var(--accent)" }}
        >
          {user?.display_name?.[0] || user?.email?.[0] || "?"}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate flex items-center gap-1.5">
            <span className="truncate">{user?.display_name || "User"}</span>
            {adminMe?.is_admin && (
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  padding: "2px 7px",
                  borderRadius: 99,
                  background: "color-mix(in oklch, var(--accent) 18%, transparent)",
                  color: "var(--accent)",
                  textTransform: "uppercase",
                  letterSpacing: 0.3,
                  flexShrink: 0,
                }}
              >
                {adminMe.is_super_admin ? "Super" : "Admin"}
              </span>
            )}
          </p>
          <p className="text-xs truncate" style={{ color: "var(--text-secondary)" }}>
            {user?.email}
          </p>
        </div>
      </div>
    </div>
    </ResizableSidebar>
  );
}
