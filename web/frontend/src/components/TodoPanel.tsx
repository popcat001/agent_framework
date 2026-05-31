import { Check, Circle, Loader } from "lucide-react";
import type { TodoItem } from "../types";

interface TodoPanelProps {
  todos: TodoItem[];
}

export function TodoPanel({ todos }: TodoPanelProps) {
  const completed = todos.filter((t) => t.status === "completed").length;

  return (
    <div
      className="rounded-lg px-4 py-3 text-xs mb-3"
      style={{ background: "rgba(0,0,0,0.02)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium" style={{ color: "var(--text-primary)" }}>
          Progress
        </span>
        <span style={{ color: "var(--text-secondary)" }}>
          {completed}/{todos.length}
        </span>
      </div>

      {/* Progress bar */}
      <div
        className="h-1.5 rounded-full mb-3 overflow-hidden"
        style={{ background: "var(--border)" }}
      >
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${todos.length > 0 ? (completed / todos.length) * 100 : 0}%`,
            background: completed === todos.length ? "#16a34a" : "var(--accent)",
          }}
        />
      </div>

      {/* Items */}
      <div className="space-y-1.5">
        {todos.map((todo) => (
          <div key={todo.id} className="flex items-start gap-2">
            {todo.status === "completed" ? (
              <Check size={13} className="mt-0.5 shrink-0" style={{ color: "#16a34a" }} />
            ) : todo.status === "in_progress" ? (
              <Loader size={13} className="mt-0.5 shrink-0 animate-spin" style={{ color: "var(--accent)" }} />
            ) : (
              <Circle size={13} className="mt-0.5 shrink-0" style={{ color: "var(--border)" }} />
            )}
            <span
              style={{
                color: todo.status === "completed" ? "var(--text-secondary)" : "var(--text-primary)",
                textDecoration: todo.status === "completed" ? "line-through" : "none",
              }}
            >
              {todo.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
