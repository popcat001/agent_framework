export interface User {
  id: string;
  email: string;
  display_name: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  agent_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  icon: string | null;
  default: boolean;
  sample_questions: { icon: string; text: string }[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: MessageContent;
  created_at: string;
  feedback?: "up" | "down" | null;
  feedback_comment?: string | null;
}

export interface MessageContent {
  text?: string;
  blocks?: ContentBlock[];
  charts?: { name: string; chart_url: string }[];
}

export interface ContentBlock {
  type: "text" | "tool_use" | "unknown";
  text?: string;
  name?: string;
  input?: Record<string, unknown>;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

// WebSocket events
export type WSEventType =
  | "text_delta"
  | "tool_start"
  | "tool_result"
  | "tool_use_start"
  | "conversation_created"
  | "assistant_persisted"
  | "done"
  | "error";

export interface WSEvent {
  type: WSEventType;
  text?: string;
  name?: string;
  tool_use_id?: string;
  input?: Record<string, unknown>;
  output?: string;
  chart_url?: string;
  message?: string;
  message_id?: string;
  conversation_id?: string;
  agent_id?: string;
  title?: string;
}

export interface ToolStatus {
  name: string;
  // Anthropic tool_use block id. Used to match a tool_result to the exact
  // running call — required so parallel calls to the same-named tool resolve
  // independently instead of completing the first match by name.
  toolUseId?: string;
  status: "running" | "completed";
  input?: Record<string, unknown>;
  output?: string;
  chart_url?: string;
}

export interface TodoItem {
  id: string;
  text: string;
  status: "pending" | "in_progress" | "completed";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  tools?: ToolStatus[];
  todos?: TodoItem[];
  isStreaming?: boolean;
  // DB UUID of the persisted assistant row. Absent until the backend emits
  // `assistant_persisted` (just after the assistant message commits).
  // Required for feedback PATCH calls.
  dbId?: string;
  feedback?: "up" | "down" | null;
  feedbackComment?: string | null;
}
