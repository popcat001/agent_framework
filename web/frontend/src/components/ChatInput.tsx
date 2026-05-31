import { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";
import { project } from "../config/project";

interface ChatInputProps {
  onSend: (content: string) => void;
  isStreaming: boolean;
}

export function ChatInput({ onSend, isStreaming }: ChatInputProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, [input]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="px-6 pb-6 pt-2">
      <div className="max-w-4xl mx-auto">
        <div
          className="flex items-center gap-3 px-4 py-3 rounded-2xl"
          style={{
            background: "var(--bg-input)",
            border: "1px solid var(--border)",
            boxShadow: "0 2px 12px rgba(0,0,0,0.04)",
          }}
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="How can I help you today?"
            rows={1}
            className="flex-1 bg-transparent resize-none outline-none text-sm leading-relaxed placeholder:text-[var(--text-secondary)]"
            style={{ maxHeight: 200 }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className="shrink-0 p-2 rounded-xl transition-all cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
            style={{
              background: input.trim() && !isStreaming ? "var(--accent)" : "var(--border)",
              color: "white",
            }}
          >
            <ArrowUp size={16} />
          </button>
        </div>
        <p className="text-center text-xs mt-2" style={{ color: "var(--text-secondary)" }}>
          {project.disclaimer}
        </p>
      </div>
    </div>
  );
}
