import { Wrench, Check, Loader } from "lucide-react";
import { ChartFrame } from "./ChartFrame";
import type { ToolStatus } from "../types";

interface ToolIndicatorProps {
  tool: ToolStatus;
}

export function ToolIndicator({ tool }: ToolIndicatorProps) {
  const isRunning = tool.status === "running";

  return (
    <div>
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs"
        style={{
          background: "rgba(0,0,0,0.03)",
          border: "1px solid var(--border)",
        }}
      >
        {isRunning ? (
          <Loader size={13} className="animate-spin" style={{ color: "var(--accent)" }} />
        ) : (
          <Check size={13} style={{ color: "#16a34a" }} />
        )}

        <Wrench size={12} style={{ color: "var(--text-secondary)" }} />

        <span className="font-mono break-all" style={{ color: "var(--text-secondary)" }}>
          {tool.name}({tool.input ? Object.entries(tool.input).map(([k, v]) => `${k}=${v}`).join(", ").slice(0, 240) : ""})
        </span>

        {isRunning && (
          <span style={{ color: "var(--text-secondary)" }}>...</span>
        )}
      </div>

      {tool.chart_url && !isRunning && (
        <div className="mt-2">
          <ChartFrame src={tool.chart_url} title={`Chart: ${tool.name}`} />
        </div>
      )}
    </div>
  );
}
