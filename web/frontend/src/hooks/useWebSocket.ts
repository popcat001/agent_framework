import { useCallback, useEffect, useRef, useState } from "react";
import { ChatWebSocket } from "../services/websocket";
import { api, setSessionExpiredHandler } from "../services/api";
import type { ChatMessage, TodoItem, ToolStatus, WSEvent } from "../types";

let messageIdCounter = 0;
function nextId() {
  return `msg-${++messageIdCounter}`;
}

interface UseWebSocketReturn {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  sessionExpired: boolean;
  sendMessage: (content: string, conversationId: string | null, agentId?: string | null) => void;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  lastConversationId: string | null;
  lastAgentId: string | null;
}

export function useWebSocket(): UseWebSocketReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [lastConversationId, setLastConversationId] = useState<string | null>(null);
  const [lastAgentId, setLastAgentId] = useState<string | null>(null);
  const wsRef = useRef<ChatWebSocket | null>(null);
  const streamingTextRef = useRef("");
  const toolsRef = useRef<ToolStatus[]>([]);

  // Use a ref for the latest setMessages so the WS callback always uses the current one
  const setMessagesRef = useRef(setMessages);
  setMessagesRef.current = setMessages;
  const setIsStreamingRef = useRef(setIsStreaming);
  setIsStreamingRef.current = setIsStreaming;
  const setErrorRef = useRef(setError);
  setErrorRef.current = setError;
  const setLastConvRef = useRef(setLastConversationId);
  setLastConvRef.current = setLastConversationId;
  const setLastAgentRef = useRef(setLastAgentId);
  setLastAgentRef.current = setLastAgentId;

  useEffect(() => {
    const handleEvent = (event: WSEvent) => {
      switch (event.type) {
        case "conversation_created":
          if (event.conversation_id) {
            setLastConvRef.current(event.conversation_id);
          }
          if (event.agent_id) {
            setLastAgentRef.current(event.agent_id);
          }
          break;

        case "text_delta":
          streamingTextRef.current += event.text || "";
          setMessagesRef.current((prev) => {
            const last = prev[prev.length - 1];
            if (last?.isStreaming) {
              return [
                ...prev.slice(0, -1),
                { ...last, text: streamingTextRef.current },
              ];
            }
            return prev;
          });
          break;

        case "tool_start": {
          toolsRef.current = [
            ...toolsRef.current,
            {
              name: event.name || "unknown",
              toolUseId: event.tool_use_id,
              status: "running",
              input: event.input,
            },
          ];
          // Extract todo items when the todo tool is called
          let todosUpdate: TodoItem[] | undefined;
          if (event.name === "todo" && event.input?.items) {
            todosUpdate = (event.input.items as TodoItem[]).map((item) => ({
              id: String(item.id),
              text: String(item.text),
              status: item.status || "pending",
            }));
          }
          setMessagesRef.current((prev) => {
            const last = prev[prev.length - 1];
            if (last?.isStreaming) {
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  tools: [...toolsRef.current],
                  ...(todosUpdate ? { todos: todosUpdate } : {}),
                },
              ];
            }
            return prev;
          });
          break;
        }

        case "tool_result": {
          // Match the result to its originating call by tool_use_id so
          // parallel calls to the same-named tool complete independently.
          // Fall back to the first still-running same-name tool only when the
          // event carries no id (legacy/replayed events).
          let matchedByName = false;
          toolsRef.current = toolsRef.current.map((t) => {
            const isMatch = event.tool_use_id
              ? t.toolUseId === event.tool_use_id
              : !matchedByName && t.name === event.name && t.status === "running";
            if (!isMatch) return t;
            if (!event.tool_use_id) matchedByName = true;
            return { ...t, status: "completed" as const, output: event.output, chart_url: event.chart_url };
          });
          setMessagesRef.current((prev) => {
            const last = prev[prev.length - 1];
            if (last?.isStreaming) {
              return [
                ...prev.slice(0, -1),
                { ...last, tools: [...toolsRef.current] },
              ];
            }
            return prev;
          });
          break;
        }

        case "assistant_persisted": {
          // Backend has committed the assistant message — attach the DB id
          // to the bubble it belongs to. The backend now sends this BEFORE
          // `done`, so the target is always the in-flight assistant message
          // (still streaming, or already finalized but missing a dbId from
          // a prior turn whose persist had not yet landed). Matching on
          // isStreaming || !dbId is defense in depth in case event ordering
          // ever regresses.
          const dbId = event.message_id;
          if (!dbId) break;
          setMessagesRef.current((prev) => {
            for (let i = prev.length - 1; i >= 0; i--) {
              const m = prev[i];
              if (m.role === "assistant" && (m.isStreaming || !m.dbId)) {
                const next = [...prev];
                next[i] = { ...m, dbId };
                return next;
              }
            }
            return prev;
          });
          break;
        }

        case "done": {
          // Capture final values before resetting refs, so the updater
          // uses the correct snapshot even if React batches the call.
          const finalText = streamingTextRef.current;
          const finalTools = [...toolsRef.current];
          setMessagesRef.current((prev) => {
            const last = prev[prev.length - 1];
            if (last?.isStreaming) {
              return [
                ...prev.slice(0, -1),
                { ...last, text: finalText, tools: finalTools, isStreaming: false },
              ];
            }
            return prev;
          });
          setIsStreamingRef.current(false);
          streamingTextRef.current = "";
          toolsRef.current = [];
          break;
        }

        case "error":
          setErrorRef.current(event.message || "Unknown error");
          setIsStreamingRef.current(false);
          break;
      }
    };

    const onExpired = () => {
      setSessionExpired(true);
      setIsStreamingRef.current(false);
    };
    // Share the same signal with the REST client so REST 401s/opaque
    // redirects surface the same modal instead of failing silently.
    setSessionExpiredHandler(onExpired);

    const ws = new ChatWebSocket(handleEvent, onExpired);
    ws.connect();
    wsRef.current = ws;

    // Re-check auth whenever the tab regains focus. Covers the long-idle
    // case where the cookie expired while the WS stayed open: api.getMe()
    // goes through ApiClient.request, which fires onExpired on opaqueredirect
    // / 401 / 403. SessionExpiredError is swallowed because the modal is
    // already the visible signal.
    const onFocus = () => {
      api.getMe().catch(() => {});
    };
    window.addEventListener("focus", onFocus);

    return () => {
      window.removeEventListener("focus", onFocus);
      ws.disconnect();
      setSessionExpiredHandler(null);
    };
  }, []);

  const sendMessage = useCallback(
    (content: string, conversationId: string | null, agentId?: string | null) => {
      if (!wsRef.current) return;

      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "user", text: content },
      ]);

      streamingTextRef.current = "";
      toolsRef.current = [];
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", text: "", isStreaming: true, tools: [] },
      ]);

      setIsStreaming(true);
      setError(null);

      wsRef.current.send({
        type: "user_message",
        conversation_id: conversationId,
        content,
        agent_id: agentId ?? null,
      });
    },
    []
  );

  return { messages, isStreaming, error, sessionExpired, sendMessage, setMessages, lastConversationId, lastAgentId };
}
