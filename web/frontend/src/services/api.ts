import type { AgentInfo, Conversation, ConversationDetail, User } from "../types";

// App-wide callback fired when any REST call detects an expired session.
// Set once at app startup (see useWebSocket); kept here so api.ts has no
// dependency on React or any specific component.
let sessionExpiredHandler: (() => void) | null = null;
export function setSessionExpiredHandler(fn: (() => void) | null) {
  sessionExpiredHandler = fn;
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

class ApiClient {
  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    let res: Response;
    try {
      res = await fetch(path, {
        ...options,
        credentials: "include",
        cache: "no-store",
        // Don't follow EasyAuth's 302 to Okta — a cross-origin redirect is
        // itself the signal that the session is gone. With redirect:"manual",
        // the browser reports it as type === "opaqueredirect".
        redirect: "manual",
        headers: { "Content-Type": "application/json", ...options.headers },
      });
    } catch (err) {
      // Network truly down — surface as-is, don't claim session expiry.
      throw err;
    }

    if (res.type === "opaqueredirect" || res.status === 401 || res.status === 403) {
      sessionExpiredHandler?.();
      throw new SessionExpiredError();
    }
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`API error ${res.status}: ${body}`);
    }
    // 204 No Content (e.g. DELETE) has an empty body — don't try to parse it.
    if (res.status === 204) return undefined as T;
    return res.json();
  }

  async getMe(): Promise<User> {
    return this.request("/api/auth/me");
  }

  async listAgents(): Promise<AgentInfo[]> {
    return this.request("/api/agents");
  }

  async listConversations(limit = 50, offset = 0): Promise<Conversation[]> {
    return this.request(`/api/conversations?limit=${limit}&offset=${offset}`);
  }

  async getConversation(id: string): Promise<ConversationDetail> {
    return this.request(`/api/conversations/${id}`);
  }

  async createConversation(): Promise<Conversation> {
    return this.request("/api/conversations", { method: "POST" });
  }

  async renameConversation(id: string, title: string): Promise<Conversation> {
    return this.request(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  }

  async deleteConversation(id: string): Promise<void> {
    await this.request(`/api/conversations/${id}`, { method: "DELETE" });
  }

  async setMessageFeedback(
    conversationId: string,
    messageId: string,
    rating: "up" | "down" | null,
    comment?: string | null,
  ): Promise<{ id: string; feedback: string | null; feedback_comment: string | null }> {
    return this.request(
      `/api/conversations/${conversationId}/messages/${messageId}/feedback`,
      {
        method: "PATCH",
        body: JSON.stringify({ rating, comment: comment ?? null }),
      },
    );
  }

  // ---- Admin (Manage access) ----
  async adminMe(): Promise<AdminMe> {
    return this.request("/api/admin/me");
  }

  async listAccessGrants(agentId?: string): Promise<AdminGrant[]> {
    const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    return this.request(`/api/admin/access${q}`);
  }

  async addAccessGrant(agent_id: string, email: string): Promise<AdminGrant> {
    return this.request("/api/admin/access", {
      method: "POST",
      body: JSON.stringify({ agent_id, email }),
    });
  }

  async removeAccessGrant(agent_id: string, email: string): Promise<void> {
    const params = new URLSearchParams({ agent_id, email });
    await this.request(`/api/admin/access?${params.toString()}`, { method: "DELETE" });
  }

  async searchAdminUsers(q: string, limit = 20): Promise<AdminUserHit[]> {
    const params = new URLSearchParams({ q, limit: String(limit) });
    return this.request(`/api/admin/users?${params.toString()}`);
  }

  async listAgentAdmins(agentId?: string): Promise<AdminAgentAdmin[]> {
    const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
    return this.request(`/api/admin/agent-admins${q}`);
  }

  async addAgentAdmin(agent_id: string, email: string): Promise<AdminAgentAdmin> {
    return this.request("/api/admin/agent-admins", {
      method: "POST",
      body: JSON.stringify({ agent_id, email }),
    });
  }

  async removeAgentAdmin(agent_id: string, email: string): Promise<void> {
    const params = new URLSearchParams({ agent_id, email });
    await this.request(`/api/admin/agent-admins?${params.toString()}`, { method: "DELETE" });
  }
}

export interface AdminMe {
  is_admin: boolean;
  is_super_admin: boolean;
  managed_agents: { id: string; name: string }[];
  super_admins: string[];
}
export interface AdminGrant { agent_id: string; email: string; created_at: string; }
export interface AdminAgentAdmin { agent_id: string; email: string; created_at: string; }
export interface AdminUserHit { email: string; display_name: string | null; }

export const api = new ApiClient();
