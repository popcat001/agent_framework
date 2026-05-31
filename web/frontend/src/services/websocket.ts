import type { WSEvent } from "../types";

type EventHandler = (event: WSEvent) => void;
type AuthFailureHandler = () => void;

export class ChatWebSocket {
  private ws: WebSocket | null = null;
  private onEvent: EventHandler;
  private onAuthFailure?: AuthFailureHandler;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private stopped = false;

  constructor(onEvent: EventHandler, onAuthFailure?: AuthFailureHandler) {
    this.onEvent = onEvent;
    this.onAuthFailure = onAuthFailure;
  }

  /**
   * Probe an authenticated REST endpoint to classify why the WS upgrade
   * failed. The browser surfaces a 401 on the upgrade as a generic 1006
   * close, so we can't tell auth failure from a network blip from the
   * close event alone (except for code 4001, which the backend sets
   * explicitly for unauthenticated WS — see framework/web/backend/auth.py).
   *
   * Returns:
   *   "valid"   — session is good; any WS failure was transient/network
   *   "expired" — session is gone; surface the refresh prompt
   *   "unknown" — couldn't determine (transient 5xx, fetch threw); treat
   *               as recoverable so we keep retrying
   */
  private async classifySession(): Promise<"valid" | "expired" | "unknown"> {
    let res: Response;
    try {
      res = await fetch("/api/auth/me", {
        credentials: "include",
        cache: "no-store",
        // Don't follow EasyAuth's 302 to Okta — a redirect is itself the
        // signal that the session is gone, and the cross-origin hop would
        // either CORS-throw or land as an opaque response.
        redirect: "manual",
      });
    } catch {
      // True network error (offline, DNS, etc.). Don't claim expiry — let
      // the existing reconnect loop handle it.
      return "unknown";
    }

    // Manual-redirect mode reports cross-origin redirects as opaqueredirect.
    // EasyAuth bouncing to Okta is the canonical "no session" path.
    if (res.type === "opaqueredirect") return "expired";
    if (res.status === 401 || res.status === 403) return "expired";
    if (res.ok) return "valid";
    // 5xx, 429, other 4xx — could be a backend hiccup unrelated to auth.
    return "unknown";
  }

  async connect() {
    if (this.stopped) return;

    // Pre-flight auth check on the first attempt: if the session is already
    // gone, surface the failure immediately rather than opening a WS that
    // will be refused with no clear signal. On "unknown", proceed and let
    // the WS itself fail (avoids blocking on a transient /api/auth/me error).
    if (this.reconnectAttempts === 0) {
      const status = await this.classifySession();
      if (status === "expired") {
        this.stopped = true;
        this.onAuthFailure?.();
        return;
      }
    }

    // In dev, connect directly to backend to avoid Vite proxy WS issues
    const wsHost = import.meta.env.VITE_WS_URL || `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
    const url = `${wsHost}/ws/chat`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      console.log("[WS] connected, url=" + this.ws?.url);
    };

    this.ws.onmessage = (event) => {
      try {
        const data: WSEvent = JSON.parse(event.data);
        console.log("[WS recv]", data.type, data.type === "text_delta" ? data.text?.substring(0, 50) : "");
        this.onEvent(data);
      } catch {
        console.error("Failed to parse WebSocket message:", event.data);
      }
    };

    this.ws.onclose = async (event) => {
      if (event.code === 1000 || this.stopped) return;

      // Backend sets close code 4001 specifically for unauthenticated WS
      // (framework/web/backend/auth.py). Trust this signal directly — it
      // works even when the WS host differs from the HTTP host (e.g. dev
      // mode with VITE_WS_URL) and avoids an unnecessary probe.
      if (event.code === 4001) {
        this.stopped = true;
        this.onAuthFailure?.();
        return;
      }

      // For any other abnormal close (1006 etc.), classify via the REST
      // probe. Only treat a clear "expired" verdict as session loss;
      // "valid" or "unknown" both fall through to the reconnect path.
      const status = await this.classifySession();
      if (status === "expired") {
        this.stopped = true;
        this.onAuthFailure?.();
        return;
      }

      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++;
        const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30000);
        setTimeout(() => this.connect(), delay);
      }
    };

    this.ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };
  }

  send(data: { type: string; conversation_id?: string | null; content?: string; agent_id?: string | null }) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.log("[WS send]", data.type, data.content?.substring(0, 50));
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn("[WS send] not connected, readyState=", this.ws?.readyState);
    }
  }

  disconnect() {
    console.log("[WS] disconnect called");
    this.stopped = true;
    this.ws?.close(1000);
    this.ws = null;
  }
}
