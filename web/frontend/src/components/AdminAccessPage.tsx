import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  Plus,
  Search,
  Shield,
  Trash2,
  Users,
} from "lucide-react";
import { resolveIcon } from "../config/iconRegistry";
import {
  api,
  type AdminAgentAdmin,
  type AdminGrant,
  type AdminMe,
  type AdminUserHit,
} from "../services/api";
import type { AgentInfo } from "../types";

function AgentIcon({ name, size = 16 }: { name: string | null; size?: number }) {
  const Icon = resolveIcon(name) ?? Bot;
  return <Icon size={size} />;
}

interface AdminAccessPageProps {
  onBack?: () => void;
}

export default function AdminAccessPage({ onBack }: AdminAccessPageProps) {
  const [me, setMe] = useState<AdminMe | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [grants, setGrants] = useState<AdminGrant[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterAgent, setFilterAgent] = useState<string | "all">("all");
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState<{ agentId: string | null; mode: "grant" | "promote" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // L2 agent admins — only loaded for L1 super admins (the endpoint denies others).
  const [agentAdmins, setAgentAdmins] = useState<AdminAgentAdmin[]>([]);

  // Initial load — admin info, agent catalogue, grants
  useEffect(() => {
    (async () => {
      try {
        const [adminMe, allAgents, grantRows] = await Promise.all([
          api.adminMe(),
          api.listAgents(),
          api.listAccessGrants(),
        ]);
        setMe(adminMe);
        setAgents(allAgents);
        setGrants(grantRows);
        // L2 admins don't see the "All agents" pill — default-select their
        // first managed agent so the page doesn't render the cross-agent view.
        if (!adminMe.is_super_admin && adminMe.managed_agents.length > 0) {
          setFilterAgent(adminMe.managed_agents[0].id);
        }
        if (adminMe.is_super_admin) {
          try {
            setAgentAdmins(await api.listAgentAdmins());
          } catch {
            // Non-fatal — keep the page usable even if this call fails.
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load admin data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Only agents the caller can manage — L1 sees them all, L2 sees their scope.
  const managedAgents = useMemo<AgentInfo[]>(() => {
    if (!me) return [];
    const managedIds = new Set(me.managed_agents.map((a) => a.id));
    return agents.filter((a) => managedIds.has(a.id));
  }, [me, agents]);

  const grantsByAgent = useMemo(() => {
    const map = new Map<string, AdminGrant[]>();
    for (const g of grants) {
      if (!map.has(g.agent_id)) map.set(g.agent_id, []);
      map.get(g.agent_id)!.push(g);
    }
    return map;
  }, [grants]);

  // Users whose email appears in *every* managed agent's grant list — i.e.
  // they have access to all agents. Used by the "All" tab.
  const usersWithFullAccess = useMemo<string[]>(() => {
    if (managedAgents.length === 0) return [];
    const emailSets = managedAgents.map(
      (a) => new Set((grantsByAgent.get(a.id) ?? []).map((g) => g.email))
    );
    const [first, ...rest] = emailSets;
    if (!first) return [];
    return [...first]
      .filter((email) => rest.every((s) => s.has(email)))
      .sort();
  }, [managedAgents, grantsByAgent]);

  const filteredGrantsForAgent = (agentId: string): AdminGrant[] => {
    const rows = grantsByAgent.get(agentId) ?? [];
    if (!search.trim()) return rows;
    const q = search.trim().toLowerCase();
    return rows.filter((r) => r.email.toLowerCase().includes(q));
  };

  const filteredFullAccessUsers = useMemo<string[]>(() => {
    if (!search.trim()) return usersWithFullAccess;
    const q = search.trim().toLowerCase();
    return usersWithFullAccess.filter((e) => e.toLowerCase().includes(q));
  }, [usersWithFullAccess, search]);

  const handleRemove = async (agentId: string, email: string) => {
    if (!confirm(`Revoke ${email}'s access to this agent?`)) return;
    try {
      await api.removeAccessGrant(agentId, email);
      setGrants((prev) =>
        prev.filter((g) => !(g.agent_id === agentId && g.email === email))
      );
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to revoke access");
    }
  };

  const handleGrantAdded = (g: AdminGrant) => {
    setGrants((prev) => {
      const dupe = prev.find(
        (p) => p.agent_id === g.agent_id && p.email === g.email
      );
      if (dupe) return prev;
      return [...prev, g];
    });
    setModalOpen(null);
  };

  const handleAgentAdminAdded = (a: AdminAgentAdmin) => {
    setAgentAdmins((prev) => {
      const dupe = prev.find(
        (p) => p.agent_id === a.agent_id && p.email === a.email
      );
      if (dupe) return prev;
      return [...prev, a];
    });
    setModalOpen(null);
  };

  const handleDemote = async (agentId: string, email: string) => {
    if (!confirm(`Revoke ${email}'s admin role on this agent? They keep any explicit access grant.`)) return;
    try {
      await api.removeAgentAdmin(agentId, email);
      setAgentAdmins((prev) =>
        prev.filter((a) => !(a.agent_id === agentId && a.email === email))
      );
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to demote admin");
    }
  };

  // ---- Render ----
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p style={{ color: "var(--text-secondary)" }}>Loading…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p style={{ color: "#DC2626" }}>{error}</p>
      </div>
    );
  }
  if (!me?.is_admin) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p style={{ color: "var(--text-secondary)" }}>
          You don't have permission to manage access.
        </p>
      </div>
    );
  }

  const visibleAgents =
    filterAgent === "all"
      ? managedAgents
      : managedAgents.filter((a) => a.id === filterAgent);

  return (
    <div className="flex-1 overflow-y-auto" style={{ padding: "32px 40px" }}>
      {/* Sticky header + toolbar — stays in view as the agent lists scroll. */}
      <div
        style={{
          position: "sticky",
          top: -32, // negative offset matches the container's top padding so
          // the header anchors flush to the top while scrolling.
          background: "var(--bg-primary)",
          paddingTop: 32,
          paddingBottom: 12,
          marginTop: -32,
          zIndex: 10,
        }}
      >
      <div className="flex items-start justify-between mb-6 gap-4">
        <div>
          <div
            className="flex items-center gap-2 mb-1"
            style={{ fontSize: 22, fontWeight: 700 }}
          >
            <Shield size={20} style={{ color: "var(--accent)" }} />
            Manage Access
          </div>
          <div style={{ fontSize: 13.5, color: "var(--text-secondary)" }}>
            {me.is_super_admin
              ? (() => {
                  const full =
                    usersWithFullAccess.length > 0
                      ? usersWithFullAccess.length
                      : (me.super_admins ?? []).length;
                  const fallback =
                    usersWithFullAccess.length === 0 && (me.super_admins ?? []).length > 0;
                  return `${grants.length} grants across ${managedAgents.length} agents · ${full} user${full === 1 ? "" : "s"} with full access${fallback ? " (env-managed)" : ""}`;
                })()
              : `Managing ${managedAgents.length} agent${managedAgents.length === 1 ? "" : "s"} · ${grants.length} grants`}
          </div>
        </div>

        {managedAgents.length > 0 && (
          <button
            onClick={() =>
              setModalOpen({
                // From the header: pre-fill the dropdown when the user is
                // filtered to a single agent (it's the obvious target);
                // otherwise leave it empty to match the "Select agent…"
                // mock and force an explicit choice.
                agentId: filterAgent !== "all" ? filterAgent : null,
                mode: "grant",
              })
            }
            className="flex items-center gap-2 cursor-pointer flex-shrink-0"
            style={{
              padding: "10px 18px",
              background: "var(--accent)",
              color: "white",
              border: "none",
              borderRadius: 8,
              fontSize: 13.5,
              fontWeight: 600,
              boxShadow: "0 1px 3px rgba(0,0,0,0.10)",
              transition: "opacity 150ms, transform 150ms",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = "0.9";
              e.currentTarget.style.transform = "translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "1";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            <Plus size={15} strokeWidth={2.5} />
            Add user
          </button>
        )}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg"
          style={{
            background: "var(--bg-input, white)",
            border: "1.5px solid var(--border)",
            minWidth: 240,
          }}
        >
          <Search size={14} style={{ color: "var(--text-secondary)" }} />
          <input
            type="text"
            placeholder="Search by email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-transparent outline-none flex-1"
            style={{ fontSize: 13 }}
          />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {me.is_super_admin && (
            <FilterPill
              active={filterAgent === "all"}
              label={`All agents (${
                usersWithFullAccess.length > 0
                  ? usersWithFullAccess.length
                  : (me.super_admins ?? []).length
              })`}
              onClick={() => setFilterAgent("all")}
            />
          )}
          {managedAgents.map((a) => (
            <FilterPill
              key={a.id}
              active={filterAgent === a.id}
              label={`${a.name} (${(grantsByAgent.get(a.id) ?? []).length})`}
              onClick={() => setFilterAgent(a.id)}
            />
          ))}
        </div>
      </div>
      </div>
      {/* /sticky */}

      {/* L1-only: Agent admins (L2). Promote/demote rows in web_agent_admins.
          Promoted users implicitly access the agent and can manage its
          per-user grants. Hidden from L2 admins entirely. */}
      {me.is_super_admin && (
        <AgentAdminsSection
          agents={managedAgents}
          admins={agentAdmins}
          filterAgent={filterAgent}
          searchQuery={search}
          onPromote={(agentId) =>
            setModalOpen({ agentId, mode: "promote" })
          }
          onDemote={handleDemote}
        />
      )}

      <div
        className="flex items-center gap-2 mb-2"
        style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}
      >
        <Users size={14} style={{ color: "var(--accent)" }} />
        Agent users
        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-secondary)" }}>
          — granted access to use the agent
        </span>
      </div>

      {/* "All agents" view: a single card listing users granted access to
          every managed agent. The Remove action revokes them from *all*
          agents in one go. When no DB user has full access, fall back to
          showing L1 super admins (they implicitly have full access via the
          ADMIN_EMAILS env var). */}
      {filterAgent === "all" ? (
        <FullAccessCard
          managedAgents={managedAgents}
          users={filteredFullAccessUsers}
          totalCount={usersWithFullAccess.length}
          superAdmins={
            usersWithFullAccess.length === 0
              ? (me.super_admins ?? []).filter(
                  (e) => !search.trim() || e.toLowerCase().includes(search.trim().toLowerCase()),
                )
              : []
          }
          searchActive={!!search.trim()}
          onRemove={async (email) => {
            if (!confirm(
              `Revoke ${email}'s access across all ${managedAgents.length} agents?`
            )) return;
            try {
              await Promise.all(
                managedAgents.map((a) => api.removeAccessGrant(a.id, email)),
              );
              setGrants((prev) => prev.filter((g) => g.email !== email));
            } catch (e) {
              alert(e instanceof Error ? e.message : "Failed to revoke access");
            }
          }}
        />
      ) : (
      <div
        className="grid gap-4"
        style={{
          gridTemplateColumns:
            visibleAgents.length === 1 ? "1fr" : "repeat(auto-fill, minmax(420px, 1fr))",
        }}
      >
        {visibleAgents.map((agent) => {
          const rows = filteredGrantsForAgent(agent.id);
          return (
            <div
              key={agent.id}
              className="flex flex-col rounded-2xl"
              style={{
                background: "var(--bg-input, white)",
                border: "1px solid var(--border)",
                boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
              }}
            >
              <div
                className="flex items-center justify-between px-5 py-3"
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className="flex items-center justify-center rounded-lg"
                    style={{
                      width: 32,
                      height: 32,
                      background: "color-mix(in oklch, var(--accent) 12%, transparent)",
                      color: "var(--accent)",
                    }}
                  >
                    <AgentIcon name={agent.icon} />
                  </span>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>{agent.name}</div>
                  <span
                    style={{
                      fontSize: 10.5,
                      fontWeight: 600,
                      padding: "2px 8px",
                      borderRadius: 99,
                      background: "color-mix(in oklch, var(--accent) 14%, transparent)",
                      color: "var(--accent)",
                      textTransform: "uppercase",
                      letterSpacing: 0.4,
                    }}
                  >
                    Users
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "2px 9px",
                      borderRadius: 99,
                      background: "rgba(0,0,0,0.06)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {(grantsByAgent.get(agent.id) ?? []).length}
                  </span>
                </div>
              </div>

              <div className="flex-1 py-2">
                {rows.length === 0 ? (
                  <div
                    style={{
                      padding: "20px",
                      fontSize: 13,
                      color: "var(--text-secondary)",
                      fontStyle: "italic",
                      textAlign: "center",
                    }}
                  >
                    {search.trim()
                      ? "No matches"
                      : "No grants yet — this agent is currently the default for new users (or unreachable if not configured)"}
                  </div>
                ) : (
                  rows.map((g) => (
                    <div
                      key={g.email}
                      className="flex items-center gap-3 px-5 py-2.5 group"
                      style={{ transition: "background 120ms" }}
                      onMouseEnter={(e) =>
                        ((e.currentTarget as HTMLDivElement).style.background = "#FAFAF8")
                      }
                      onMouseLeave={(e) =>
                        ((e.currentTarget as HTMLDivElement).style.background = "transparent")
                      }
                    >
                      <div
                        className="flex items-center justify-center rounded-full text-xs font-bold text-white flex-shrink-0"
                        style={{
                          width: 30,
                          height: 30,
                          background: emailToColor(g.email),
                        }}
                      >
                        {g.email[0]?.toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div
                          className="truncate"
                          style={{ fontSize: 13, fontWeight: 500 }}
                        >
                          {g.email}
                        </div>
                        <div
                          style={{ fontSize: 11.5, color: "var(--text-secondary)" }}
                        >
                          granted {new Date(g.created_at).toLocaleDateString()}
                        </div>
                      </div>
                      <button
                        onClick={() => handleRemove(g.agent_id, g.email)}
                        className="flex items-center gap-1 rounded-md cursor-pointer"
                        style={{
                          height: 30,
                          padding: "0 12px",
                          background: "#FEF2F2",
                          border: "1px solid #FECACA",
                          color: "#F87171",
                          fontSize: 12,
                          fontWeight: 600,
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "#DC2626";
                          e.currentTarget.style.color = "white";
                          e.currentTarget.style.borderColor = "#DC2626";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "#FEF2F2";
                          e.currentTarget.style.color = "#F87171";
                          e.currentTarget.style.borderColor = "#FECACA";
                        }}
                      >
                        <Trash2 size={12} />
                        Remove
                      </button>
                    </div>
                  ))
                )}
              </div>

              <div
                className="px-5 py-3"
                style={{ borderTop: "1px solid var(--border)" }}
              >
                <button
                  onClick={() => setModalOpen({ agentId: agent.id, mode: "grant" })}
                  className="flex items-center justify-center gap-2 w-full py-2 rounded-lg cursor-pointer"
                  style={{
                    border: "1.5px dashed var(--border)",
                    color: "var(--text-secondary)",
                    fontSize: 13,
                    fontWeight: 500,
                    transition: "all 0.15s",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "var(--accent)";
                    e.currentTarget.style.color = "var(--accent)";
                    e.currentTarget.style.background =
                      "color-mix(in oklch, var(--accent) 5%, transparent)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "var(--border)";
                    e.currentTarget.style.color = "var(--text-secondary)";
                    e.currentTarget.style.background = "transparent";
                  }}
                >
                  <Plus size={14} />
                  Add user
                </button>
              </div>
            </div>
          );
        })}
      </div>
      )}

      {modalOpen && (
        <AddUserModal
          initialAgentId={modalOpen.agentId}
          managedAgents={managedAgents}
          mode={modalOpen.mode}
          existingGrants={grants}
          existingAdmins={agentAdmins}
          onClose={() => setModalOpen(null)}
          onGrantAdded={handleGrantAdded}
          onAdminAdded={handleAgentAdminAdded}
        />
      )}

      {onBack && (
        <div className="mt-8">
          <button
            onClick={onBack}
            style={{
              fontSize: 13,
              color: "var(--text-secondary)",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            ← Back to chat
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AgentAdminsSection({
  agents,
  admins,
  filterAgent,
  searchQuery,
  onPromote,
  onDemote,
}: {
  agents: AgentInfo[];
  admins: AdminAgentAdmin[];
  filterAgent: string | "all";
  searchQuery: string;
  onPromote: (agentId: string) => void;
  onDemote: (agentId: string, email: string) => void;
}) {
  const q = searchQuery.trim().toLowerCase();
  const visibleAgents =
    filterAgent === "all" ? agents : agents.filter((a) => a.id === filterAgent);

  const adminsByAgent = new Map<string, AdminAgentAdmin[]>();
  for (const a of admins) {
    if (q && !a.email.toLowerCase().includes(q)) continue;
    if (!adminsByAgent.has(a.agent_id)) adminsByAgent.set(a.agent_id, []);
    adminsByAgent.get(a.agent_id)!.push(a);
  }

  return (
    <div style={{ marginBottom: 28 }}>
      <div
        className="flex items-center gap-2 mb-2"
        style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}
      >
        <Shield size={14} style={{ color: "var(--accent)" }} />
        Agent admins
        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-secondary)" }}>
          — manage user access for their agent
        </span>
      </div>
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: "repeat(auto-fill, minmax(440px, 1fr))" }}
      >
        {visibleAgents.map((agent) => {
          const rows = adminsByAgent.get(agent.id) ?? [];
          return (
            <div
              key={agent.id}
              className="flex flex-col rounded-2xl"
              style={{
                background: "var(--bg-input, white)",
                border: "1px solid var(--border)",
                boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
              }}
            >
              <div
                className="flex items-center justify-between px-5 py-3"
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className="flex items-center justify-center rounded-lg"
                    style={{
                      width: 32,
                      height: 32,
                      background: "color-mix(in oklch, var(--accent) 12%, transparent)",
                      color: "var(--accent)",
                    }}
                  >
                    <AgentIcon name={agent.icon} />
                  </span>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>{agent.name}</div>
                  <span
                    style={{
                      fontSize: 10.5,
                      fontWeight: 600,
                      padding: "2px 8px",
                      borderRadius: 99,
                      background: "color-mix(in oklch, var(--accent) 14%, transparent)",
                      color: "var(--accent)",
                      textTransform: "uppercase",
                      letterSpacing: 0.4,
                    }}
                  >
                    Admins
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "2px 9px",
                      borderRadius: 99,
                      background: "rgba(0,0,0,0.06)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {rows.length}
                  </span>
                </div>
                <button
                  onClick={() => onPromote(agent.id)}
                  className="flex items-center gap-1 rounded-md cursor-pointer"
                  style={{
                    height: 26,
                    padding: "0 10px",
                    border: "1.5px solid var(--border)",
                    background: "transparent",
                    color: "var(--text-secondary)",
                    fontSize: 11.5,
                    fontWeight: 600,
                  }}
                >
                  <Plus size={11} strokeWidth={2.5} />
                  Promote
                </button>
              </div>

              <div className="flex-1 py-1">
                {rows.length === 0 ? (
                  <div
                    style={{
                      padding: "12px",
                      fontSize: 12.5,
                      color: "var(--text-secondary)",
                      fontStyle: "italic",
                      textAlign: "center",
                    }}
                  >
                    {q ? "No matches" : "No agent admins yet"}
                  </div>
                ) : (
                  rows.map((r) => (
                    <div
                      key={r.email}
                      className="flex items-center gap-2.5 px-4 py-2"
                    >
                      <div
                        className="flex items-center justify-center rounded-full text-xs font-bold text-white flex-shrink-0"
                        style={{
                          width: 26,
                          height: 26,
                          background: emailToColor(r.email),
                        }}
                      >
                        {r.email[0]?.toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="truncate" style={{ fontSize: 12.5, fontWeight: 500 }}>
                          {r.email}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                          admin · {new Date(r.created_at).toLocaleDateString()}
                        </div>
                      </div>
                      <button
                        onClick={() => onDemote(r.agent_id, r.email)}
                        className="flex items-center gap-1 rounded-md cursor-pointer"
                        style={{
                          height: 26,
                          padding: "0 10px",
                          background: "#FEF2F2",
                          border: "1px solid #FECACA",
                          color: "#F87171",
                          fontSize: 11.5,
                          fontWeight: 600,
                        }}
                      >
                        <Trash2 size={11} />
                        Demote
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FullAccessCard({
  managedAgents,
  users,
  totalCount,
  superAdmins,
  searchActive,
  onRemove,
}: {
  managedAgents: AgentInfo[];
  users: string[];
  totalCount: number;
  superAdmins: string[];
  searchActive: boolean;
  onRemove: (email: string) => void;
}) {
  const showSuperFallback = users.length === 0 && superAdmins.length > 0;
  return (
    <div
      className="flex flex-col rounded-2xl"
      style={{
        background: "var(--bg-input, white)",
        border: "1px solid var(--border)",
        boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
      }}
    >
      <div
        className="flex items-center justify-between px-5 py-3"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-2.5">
          <span
            className="flex items-center justify-center rounded-lg"
            style={{
              width: 32,
              height: 32,
              background: "color-mix(in oklch, var(--accent) 12%, transparent)",
              color: "var(--accent)",
            }}
          >
            <Shield size={16} />
          </span>
          <div style={{ fontSize: 14, fontWeight: 700 }}>
            Users with access to all agents
          </div>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: "2px 9px",
              borderRadius: 99,
              background: "rgba(0,0,0,0.06)",
              color: "var(--text-secondary)",
            }}
          >
            {showSuperFallback ? superAdmins.length : totalCount}
          </span>
          {showSuperFallback && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: 99,
                background: "color-mix(in oklch, var(--accent) 18%, transparent)",
                color: "var(--accent)",
                textTransform: "uppercase",
                letterSpacing: 0.3,
              }}
              title="No DB users have full access yet. Showing L1 super admins from ADMIN_EMAILS."
            >
              Fallback
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          {managedAgents.map((a) => a.name).join(" · ")}
        </div>
      </div>

      <div className="flex-1 py-2">
        {users.length === 0 && !showSuperFallback ? (
          <div
            style={{
              padding: "20px",
              fontSize: 13,
              color: "var(--text-secondary)",
              fontStyle: "italic",
              textAlign: "center",
            }}
          >
            {searchActive
              ? "No matches"
              : "No users yet have access to every agent — grant the same email across all agents to see them here."}
          </div>
        ) : showSuperFallback ? (
          superAdmins.map((email) => (
            <div
              key={email}
              className="flex items-center gap-3 px-5 py-2.5"
            >
              <div
                className="flex items-center justify-center rounded-full text-xs font-bold text-white flex-shrink-0"
                style={{ width: 30, height: 30, background: emailToColor(email) }}
              >
                {email[0]?.toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="truncate" style={{ fontSize: 13, fontWeight: 500 }}>
                  {email}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
                  L1 super admin · implicit access to every agent
                </div>
              </div>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  padding: "3px 9px",
                  borderRadius: 99,
                  background: "color-mix(in oklch, var(--accent) 18%, transparent)",
                  color: "var(--accent)",
                  textTransform: "uppercase",
                  letterSpacing: 0.3,
                }}
                title="Managed by the ADMIN_EMAILS env var; edit the deployment config to change."
              >
                Env-managed
              </span>
            </div>
          ))
        ) : (
          users.map((email) => (
            <div
              key={email}
              className="flex items-center gap-3 px-5 py-2.5"
              style={{ transition: "background 120ms" }}
              onMouseEnter={(e) =>
                ((e.currentTarget as HTMLDivElement).style.background = "#FAFAF8")
              }
              onMouseLeave={(e) =>
                ((e.currentTarget as HTMLDivElement).style.background = "transparent")
              }
            >
              <div
                className="flex items-center justify-center rounded-full text-xs font-bold text-white flex-shrink-0"
                style={{
                  width: 30,
                  height: 30,
                  background: emailToColor(email),
                }}
              >
                {email[0]?.toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="truncate" style={{ fontSize: 13, fontWeight: 500 }}>
                  {email}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
                  full access · {managedAgents.length} agent
                  {managedAgents.length === 1 ? "" : "s"}
                </div>
              </div>
              <button
                onClick={() => onRemove(email)}
                className="flex items-center gap-1 rounded-md cursor-pointer"
                style={{
                  height: 30,
                  padding: "0 12px",
                  background: "#FEF2F2",
                  border: "1px solid #FECACA",
                  color: "#F87171",
                  fontSize: 12,
                  fontWeight: 600,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "#DC2626";
                  e.currentTarget.style.color = "white";
                  e.currentTarget.style.borderColor = "#DC2626";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "#FEF2F2";
                  e.currentTarget.style.color = "#F87171";
                  e.currentTarget.style.borderColor = "#FECACA";
                }}
              >
                <Trash2 size={12} />
                Revoke all
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function FilterPill({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="rounded-full cursor-pointer transition-colors"
      style={{
        padding: "5px 13px",
        fontSize: 12,
        fontWeight: 500,
        border: "1.5px solid var(--border)",
        background: active ? "var(--accent)" : "transparent",
        color: active ? "white" : "var(--text-secondary)",
        borderColor: active ? "var(--accent)" : "var(--border)",
      }}
    >
      {label}
    </button>
  );
}

function AddUserModal({
  initialAgentId,
  managedAgents,
  mode,
  existingGrants,
  existingAdmins,
  onClose,
  onGrantAdded,
  onAdminAdded,
}: {
  initialAgentId: string | null;
  managedAgents: AgentInfo[];
  mode: "grant" | "promote";
  existingGrants: AdminGrant[];
  existingAdmins: AdminAgentAdmin[];
  onClose: () => void;
  onGrantAdded: (g: AdminGrant) => void;
  onAdminAdded: (a: AdminAgentAdmin) => void;
}) {
  // Mock defaults to no pre-selection so the operator must make an explicit
  // choice. Honored when launched from the header button on the "All" view;
  // per-card buttons still pre-fill so the dropdown opens with their agent.
  const [agentId, setAgentId] = useState<string>(initialAgentId ?? "");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<AdminUserHit[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    // No dropdown until the user starts typing — empty query was returning
    // every web_user, which felt like an unsolicited popup.
    const q = query.trim();
    if (!q) {
      setHits([]);
      return;
    }
    const handle = setTimeout(() => {
      api
        .searchAdminUsers(q, 8)
        .then(setHits)
        .catch(() => setHits([]));
    }, 200);
    return () => clearTimeout(handle);
  }, [query]);

  const emailToSubmit = (selectedEmail || query).trim();
  const isValidEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailToSubmit);

  // Inline duplicate check against the current grant/admin list for the
  // selected agent. Backend ON CONFLICT DO NOTHING swallows re-adds silently,
  // so without this the operator gets no feedback that the user was already
  // there. Compare case-insensitively since emails are stored lower-cased.
  const emailLower = emailToSubmit.toLowerCase();
  const alreadyExists =
    !!agentId && !!emailLower &&
    (mode === "promote"
      ? existingAdmins.some(
          (a) => a.agent_id === agentId && a.email.toLowerCase() === emailLower,
        )
      : existingGrants.some(
          (g) => g.agent_id === agentId && g.email.toLowerCase() === emailLower,
        ));

  const dupErr = alreadyExists
    ? mode === "promote"
      ? "This user is already an admin for this agent."
      : "This user already has access to this agent."
    : null;

  const canSubmit = isValidEmail && !!agentId && !submitting && !alreadyExists;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setErr(null);
    try {
      if (mode === "promote") {
        const a = await api.addAgentAdmin(agentId, emailToSubmit);
        onAdminAdded(a);
      } else {
        const g = await api.addAccessGrant(agentId, emailToSubmit);
        onGrantAdded(g);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to add");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 flex items-center justify-center"
      style={{ background: "rgba(28,26,24,0.38)", zIndex: 200 }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--bg-input, white)",
          borderRadius: 14,
          padding: "26px 28px",
          width: 420,
          boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 3 }}>
          {mode === "promote" ? "Promote to agent admin" : "Add a user"}
        </h2>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 20 }}>
          {mode === "promote"
            ? "Agent admins can manage user access for their agent. They keep access even without an explicit grant."
            : "They'll see their assigned agent on their next login."}
        </div>

        <div style={{ marginBottom: 14 }}>
          <label
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--text-primary)",
              display: "block",
              marginBottom: 5,
            }}
          >
            Name or email
          </label>
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedEmail(null);
            }}
            onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
            onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
            placeholder="Search by name or Adobe email…"
            style={{
              width: "100%",
              padding: "10px 13px",
              border: "1.5px solid var(--border)",
              borderRadius: 6,
              fontSize: 13.5,
              outline: "none",
              transition: "border-color 120ms",
            }}
          />
          {hits.length > 0 && !selectedEmail && (
            <div
              style={{
                marginTop: 6,
                maxHeight: 180,
                overflowY: "auto",
                border: "1px solid var(--border)",
                borderRadius: 6,
              }}
            >
              {hits.map((u) => (
                <div
                  key={u.email}
                  onClick={() => {
                    setSelectedEmail(u.email);
                    setQuery(u.email);
                    setHits([]);
                  }}
                  className="cursor-pointer"
                  style={{
                    padding: "8px 12px",
                    fontSize: 13,
                    borderBottom: "1px solid var(--border)",
                  }}
                  onMouseEnter={(e) =>
                    ((e.currentTarget as HTMLDivElement).style.background = "var(--bg-primary)")
                  }
                  onMouseLeave={(e) =>
                    ((e.currentTarget as HTMLDivElement).style.background = "transparent")
                  }
                >
                  <div style={{ fontWeight: 600 }}>{u.display_name ?? u.email}</div>
                  {u.display_name && (
                    <div style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>{u.email}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ marginBottom: 14 }}>
          <label
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "var(--text-primary)",
              display: "block",
              marginBottom: 5,
            }}
          >
            Agent
          </label>
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
            onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
            style={{
              width: "100%",
              padding: "10px 36px 10px 13px",
              border: "1.5px solid var(--border)",
              borderRadius: 6,
              fontSize: 13.5,
              outline: "none",
              color: agentId ? "var(--text-primary)" : "var(--text-secondary)",
              transition: "border-color 120ms",
              // Strip the native chevron — the mockup uses a clean caret rendered
              // as an SVG background instead of the platform-specific arrows.
              WebkitAppearance: "none",
              MozAppearance: "none",
              appearance: "none",
              background:
                "var(--bg-input, white) url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23A8A29C' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>\") no-repeat right 13px center",
            }}
          >
            <option value="">Select agent…</option>
            {managedAgents.map((a) => (
              <option key={a.id} value={a.id} style={{ color: "var(--text-primary)" }}>
                {a.name}
              </option>
            ))}
          </select>
        </div>

        {(err || dupErr) && (
          <div
            style={{
              fontSize: 12.5,
              color: "#DC2626",
              padding: "6px 10px",
              background: "#FEF2F2",
              border: "1px solid #FECACA",
              borderRadius: 6,
              marginBottom: 12,
            }}
          >
            {err || dupErr}
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 20 }}>
          <button
            onClick={onClose}
            style={{
              padding: "9px 18px",
              border: "1.5px solid var(--border)",
              borderRadius: 6,
              background: "transparent",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              color: "var(--text-primary)",
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{
              padding: "9px 20px",
              border: "none",
              borderRadius: 6,
              color: "white",
              fontSize: 13,
              fontWeight: 600,
              // Match mockup: keep the button full-color regardless of state
              // (no opacity fade). The cursor signals validity instead.
              cursor: canSubmit ? "pointer" : "not-allowed",
              background: "var(--accent)",
            }}
          >
            {submitting ? "Adding…" : mode === "promote" ? "Promote" : "Grant access"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- helpers ----

function emailToColor(email: string): string {
  const palette = ["#D4714A", "#5B5EDB", "#2563EB", "#16A34A", "#9333EA", "#DB2777"];
  let hash = 0;
  for (let i = 0; i < email.length; i++) hash = (hash * 31 + email.charCodeAt(i)) | 0;
  return palette[Math.abs(hash) % palette.length];
}
