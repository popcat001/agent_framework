import { useRef, useCallback, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download, Copy, Check, ThumbsUp, ThumbsDown } from "lucide-react";
import { ToolIndicator } from "./ToolIndicator";
import { ChartFrame } from "./ChartFrame";
import { project } from "../config/project";
import { TodoPanel } from "./TodoPanel";
import type { ChatMessage } from "../types";

interface MessageBubbleProps {
  message: ChatMessage;
  onFeedback?: (dbId: string, rating: "up" | "down" | null) => void;
}

// Extract tmp/*.html references from text and convert to /files/ URLs
function extractChartUrls(text: string): string[] {
  const matches = text.match(/tmp\/[\w._-]+\.html/g);
  if (!matches) return [];
  return [...new Set(matches)].map((m) => `/files/${m.replace("tmp/", "")}`);
}

export function MessageBubble({ message, onFeedback }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const feedback = message.feedback ?? null;

  const handleCopy = useCallback(() => {
    if (!message.text) return;
    navigator.clipboard.writeText(message.text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [message.text]);

  const toggleFeedback = (rating: "up" | "down") => {
    if (!message.dbId || !onFeedback) return;
    onFeedback(message.dbId, feedback === rating ? null : rating);
  };

  const toolCharts = message.tools?.filter((t) => t.chart_url).map((t) => t.chart_url!) || [];
  const textCharts = !isUser && message.text ? extractChartUrls(message.text) : [];
  // Combine, dedup
  const allCharts = [...new Set([...toolCharts, ...textCharts])];
  const hasChart = allCharts.length > 0;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`${isUser ? "max-w-[85%] ml-12" : "max-w-[95%] mr-4"} ${hasChart ? "w-full" : ""}`}
        style={{ minWidth: 0 }}
      >
        {/* Role label */}
        <p
          className="text-xs font-medium mb-1 px-1"
          style={{ color: "var(--text-secondary)" }}
        >
          {isUser ? "You" : project.name}
        </p>

        {/* Message content */}
        <div
          className="px-4 py-3 rounded-2xl text-sm leading-relaxed"
          style={{
            background: isUser ? "var(--accent)" : "var(--bg-input)",
            color: isUser ? "white" : "var(--text-primary)",
            border: isUser ? "none" : "1px solid var(--border)",
          }}
        >
          {/* Todo progress panel */}
          {!isUser && message.todos && message.todos.length > 0 && (
            <TodoPanel todos={message.todos} />
          )}

          {/* Tool indicators (shown before text, excluding todo) */}
          {!isUser && message.tools && message.tools.filter((t) => t.name !== "todo").length > 0 && (
            <div className="mb-3 space-y-2">
              {message.tools.filter((t) => t.name !== "todo").map((tool, i) => (
                <ToolIndicator key={`${tool.name}-${i}`} tool={tool} />
              ))}
            </div>
          )}

          {/* Text content */}
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.text}</p>
          ) : (
            <div className={message.isStreaming && !message.text ? "" : "prose prose-sm max-w-none"}>
              {message.text ? (
                <div className={message.isStreaming ? "streaming-cursor" : ""}>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      // Style tables for finance data with CSV download
                      table: ({ children }) => {
                        const tableRef = useRef<HTMLTableElement>(null);
                        const handleDownload = useCallback(() => {
                          const table = tableRef.current;
                          if (!table) return;
                          const rows = Array.from(table.querySelectorAll("tr"));
                          const csv = rows.map((row) =>
                            Array.from(row.querySelectorAll("th, td"))
                              .map((cell) => `"${cell.textContent?.replace(/"/g, '""') || ""}"`)
                              .join(",")
                          ).join("\n");
                          const blob = new Blob([csv], { type: "text/csv" });
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = "table.csv";
                          a.click();
                          URL.revokeObjectURL(url);
                        }, []);
                        return (
                          <div className="overflow-x-auto my-2 group/table relative">
                            <button
                              onClick={handleDownload}
                              className="absolute top-1 right-1 p-1.5 rounded-md opacity-0 group-hover/table:opacity-100 transition-opacity cursor-pointer"
                              style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
                              title="Download as CSV"
                            >
                              <Download size={13} style={{ color: "var(--text-secondary)" }} />
                            </button>
                            <table ref={tableRef} className="min-w-full text-xs border-collapse">{children}</table>
                          </div>
                        );
                      },
                      th: ({ children }) => (
                        <th
                          className="px-3 py-1.5 text-left font-medium border-b"
                          style={{ borderColor: "var(--border)" }}
                        >
                          {children}
                        </th>
                      ),
                      td: ({ children }) => (
                        <td
                          className="px-3 py-1.5 border-b"
                          style={{ borderColor: "var(--border)" }}
                        >
                          {children}
                        </td>
                      ),
                      // Style code blocks
                      code: ({ className, children, ...props }) => {
                        const isInline = !className;
                        return isInline ? (
                          <code
                            className="px-1.5 py-0.5 rounded text-xs"
                            style={{ background: "rgba(0,0,0,0.05)" }}
                            {...props}
                          >
                            {children}
                          </code>
                        ) : (
                          <code
                            className={`block p-3 rounded-lg text-xs overflow-x-auto ${className || ""}`}
                            style={{ background: "rgba(0,0,0,0.03)" }}
                            {...props}
                          >
                            {children}
                          </code>
                        );
                      },
                      // Make links open in new tab
                      a: ({ href, children }) => (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: "var(--accent)" }}
                          className="underline"
                        >
                          {children}
                        </a>
                      ),
                    }}
                  >
                    {message.text}
                  </ReactMarkdown>
                </div>
              ) : message.isStreaming ? (
                <div className="flex items-center gap-2">
                  <div className="flex gap-1">
                    <span
                      className="w-1.5 h-1.5 rounded-full animate-bounce"
                      style={{ background: "var(--accent)", animationDelay: "0ms" }}
                    />
                    <span
                      className="w-1.5 h-1.5 rounded-full animate-bounce"
                      style={{ background: "var(--accent)", animationDelay: "150ms" }}
                    />
                    <span
                      className="w-1.5 h-1.5 rounded-full animate-bounce"
                      style={{ background: "var(--accent)", animationDelay: "300ms" }}
                    />
                  </div>
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    Thinking...
                  </span>
                </div>
              ) : null}
            </div>
          )}

          {/* Inline charts detected from text (e.g. bash-generated charts) */}
          {!isUser && textCharts.length > 0 && textCharts.filter((url) => !toolCharts.includes(url)).map((url) => (
            <div key={url} className="mt-3">
              <ChartFrame src={url} />
            </div>
          ))}
        </div>

        {/* Assistant action row: copy + feedback. Hidden until the backend
            has emitted assistant_persisted (message.dbId set) so feedback
            clicks always have a real DB row to patch. */}
        {!isUser && !message.isStreaming && message.text && message.dbId && (
          <div className="flex items-center gap-1 mt-1.5 px-1">
            <button
              onClick={handleCopy}
              className="p-1.5 rounded-md transition-colors hover:bg-[var(--border)] cursor-pointer"
              title={copied ? "Copied" : "Copy"}
              style={{ color: "var(--text-secondary)" }}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
            <button
              onClick={() => toggleFeedback("up")}
              className="p-1.5 rounded-md transition-colors hover:bg-[var(--border)] cursor-pointer"
              title="Good response"
              style={{ color: feedback === "up" ? "var(--accent)" : "var(--text-secondary)" }}
            >
              <ThumbsUp size={14} fill={feedback === "up" ? "currentColor" : "none"} />
            </button>
            <button
              onClick={() => toggleFeedback("down")}
              className="p-1.5 rounded-md transition-colors hover:bg-[var(--border)] cursor-pointer"
              title="Bad response"
              style={{ color: feedback === "down" ? "var(--accent)" : "var(--text-secondary)" }}
            >
              <ThumbsDown size={14} fill={feedback === "down" ? "currentColor" : "none"} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
