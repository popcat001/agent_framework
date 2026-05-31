import { Trash2 } from "lucide-react";
import type { AgentInfo, Conversation } from "../types";

interface ConversationListProps {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (conv: Conversation) => void;
  onDelete: (id: string) => void;
  agents?: AgentInfo[];
  /** When false, don't render the per-row agent badge (e.g. when the sidebar
   *  is already filtered to one agent and the badge would be redundant). */
  showAgentBadge?: boolean;
}

function groupByDate(conversations: Conversation[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: { label: string; items: Conversation[] }[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "This week", items: [] },
    { label: "Older", items: [] },
  ];

  for (const conv of conversations) {
    const d = new Date(conv.updated_at);
    if (d >= today) groups[0].items.push(conv);
    else if (d >= yesterday) groups[1].items.push(conv);
    else if (d >= weekAgo) groups[2].items.push(conv);
    else groups[3].items.push(conv);
  }

  return groups.filter((g) => g.items.length > 0);
}

export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onDelete,
  agents,
  showAgentBadge = true,
}: ConversationListProps) {
  const groups = groupByDate(conversations);
  const agentById = new Map((agents ?? []).map((a) => [a.id, a]));
  const defaultAgentId =
    agents?.find((a) => a.default)?.id ?? agents?.[0]?.id ?? null;

  if (conversations.length === 0) {
    return (
      <div className="px-4 py-8 text-center">
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          No conversations yet
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-2">
      {groups.map((group) => (
        <div key={group.label}>
          <p
            className="px-3 py-1 text-[10px] font-medium uppercase tracking-wide"
            style={{ color: "var(--text-secondary)" }}
          >
            {group.label}
          </p>
          {group.items.map((conv) => {
            const aid = conv.agent_id ?? defaultAgentId;
            const agent = aid ? agentById.get(aid) : undefined;
            return (
              <div
                key={conv.id}
                className="group flex items-center rounded-lg mx-1 cursor-pointer transition-colors"
                style={{
                  background: activeId === conv.id ? "var(--bg-primary)" : "transparent",
                }}
                onClick={() => onSelect(conv)}
                onMouseOver={(e) => {
                  if (activeId !== conv.id)
                    e.currentTarget.style.background = "rgba(0,0,0,0.03)";
                }}
                onMouseOut={(e) => {
                  if (activeId !== conv.id) e.currentTarget.style.background = "transparent";
                }}
              >
                <div className="flex-1 min-w-0 px-3 py-1.5">
                  <div className="truncate text-[13px] leading-snug">{conv.title}</div>
                  {showAgentBadge && agent && (
                    <div
                      className="mt-0.5 inline-block px-1.5 py-0.5 rounded text-[10px] font-medium leading-none"
                      style={{
                        background:
                          "color-mix(in oklch, var(--accent) 10%, transparent)",
                        color: "var(--accent)",
                      }}
                      title={agent.description}
                    >
                      {agent.name}
                    </div>
                  )}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(conv.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1.5 mr-1 rounded transition-opacity cursor-pointer hover:bg-black/5"
                  style={{ color: "var(--text-secondary)" }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
