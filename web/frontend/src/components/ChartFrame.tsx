import { useState } from "react";
import { ZoomIn, ZoomOut, Download } from "lucide-react";

const DEFAULT_HEIGHT = 500;
const SCALE_STEPS = [0.5, 0.67, 0.75, 0.85, 1.0, 1.25, 1.5];
const DEFAULT_IDX = 4; // 1.0

interface ChartFrameProps {
  src: string;
  title?: string;
  /** Unscaled (100%) frame height in px. Defaults to 500 (chat charts). */
  height?: number;
}

/**
 * Chart iframe with whole-image zoom and download controls.
 *
 * Plotly's built-in zoom only changes axis ranges — font sizes and labels stay
 * fixed. CSS transform: scale() zooms the entire rendered frame (title, labels,
 * bars) uniformly. The iframe width is counter-scaled so it always fills the
 * container, and the wrapper height tracks the visual size.
 *
 * Download fetches the PNG sibling (same filename, .png extension) which the
 * backend writes alongside every .html chart.
 */
export function ChartFrame({ src, title, height = DEFAULT_HEIGHT }: ChartFrameProps) {
  const [idx, setIdx] = useState(DEFAULT_IDX);
  const scale = SCALE_STEPS[idx];
  const baseHeight = height;
  const pngSrc = src.replace(/\.html$/, ".png");

  return (
    <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
      {/* Toolbar */}
      <div
        className="flex items-center justify-end gap-1 px-2 py-1"
        style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-sidebar)" }}
      >
        <button
          onClick={() => setIdx((i) => Math.max(0, i - 1))}
          disabled={idx === 0}
          title="Zoom out"
          className="p-1 rounded hover:bg-black/5 disabled:opacity-30 cursor-pointer disabled:cursor-default"
          style={{ color: "var(--text-secondary)" }}
        >
          <ZoomOut size={14} />
        </button>
        <span className="text-xs w-10 text-center" style={{ color: "var(--text-secondary)" }}>
          {Math.round(scale * 100)}%
        </span>
        <button
          onClick={() => setIdx((i) => Math.min(SCALE_STEPS.length - 1, i + 1))}
          disabled={idx === SCALE_STEPS.length - 1}
          title="Zoom in"
          className="p-1 rounded hover:bg-black/5 disabled:opacity-30 cursor-pointer disabled:cursor-default"
          style={{ color: "var(--text-secondary)" }}
        >
          <ZoomIn size={14} />
        </button>

        <div className="w-px h-4 mx-1" style={{ background: "var(--border)" }} />

        <a
          href={pngSrc}
          download
          title="Download PNG"
          className="p-1 rounded hover:bg-black/5 cursor-pointer"
          style={{ color: "var(--text-secondary)" }}
        >
          <Download size={14} />
        </a>
      </div>

      {/* Scaled iframe — width counter-scaled so chart always fills container */}
      <div style={{ height: baseHeight * scale, overflow: "hidden", background: "white" }}>
        <iframe
          src={src}
          title={title || "Chart"}
          className="border-0"
          style={{
            height: baseHeight,
            width: `${(100 / scale).toFixed(4)}%`,
            background: "white",
            transform: `scale(${scale})`,
            transformOrigin: "top left",
          }}
          sandbox="allow-scripts allow-same-origin allow-downloads"
        />
      </div>
    </div>
  );
}
