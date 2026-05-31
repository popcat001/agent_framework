import type { ProjectConfig } from "./projectTypes";

export const projectDefaults: ProjectConfig = {
  name: "Agent",
  tagline: "AI-powered conversational assistant",
  orgLogo: "",
  appLogo: "",
  pageTitle: "Agent — AI Assistant",
  favicon: "/favicon.svg",
  serviceName: "agent",
  disclaimer: "AI can make mistakes. Verify important information.",
  theme: {
    bgPrimary: "#f8f9fc",
    bgSidebar: "#f1f3f8",
    bgInput: "#ffffff",
    textPrimary: "#1a1a1a",
    textSecondary: "#6b6b6b",
    accent: "#4f46e5",
    accentHover: "#4338ca",
    border: "#e2e8f0",
  },
  sampleQuestions: [
    { icon: "MessageSquare", text: "What can you help me with?" },
    { icon: "Zap", text: "Show me what tools you have available" },
    { icon: "BarChart3", text: "Run a quick analysis on recent data" },
    { icon: "HelpCircle", text: "How do I get started?" },
  ],
};
