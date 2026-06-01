import { useCallback, useEffect, useRef, useState } from "react";

interface ResizableSidebarProps {
  /** localStorage key so each sidebar remembers its own width independently. */
  storageKey: string;
  children: React.ReactNode;
  /** Width bounds in px. */
  min?: number;
  max?: number;
  /** Initial width when nothing is stored; also the double-click reset target. */
  defaultWidth?: number;
}

/**
 * Wraps a sidebar in a fixed-width, horizontally resizable shell. Drag the
 * right-edge handle to resize; the width is clamped to [min, max], persisted to
 * localStorage under ``storageKey``, and double-clicking the handle resets it
 * to ``defaultWidth``.
 *
 * The wrapped child should fill the shell (``w-full h-full``) rather than set
 * its own fixed width — this component owns the width.
 */
export function ResizableSidebar({
  storageKey,
  children,
  min = 220,
  max = 520,
  defaultWidth = 288,
}: ResizableSidebarProps) {
  const clamp = useCallback((n: number) => Math.min(max, Math.max(min, n)), [min, max]);

  const [width, setWidth] = useState<number>(() => {
    const saved = parseInt(localStorage.getItem(storageKey) || "", 10);
    return Number.isFinite(saved) ? clamp(saved) : defaultWidth;
  });

  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  // Mirror width into a ref so the persist-on-mouseup handler reads the latest
  // value without re-subscribing the window listeners on every drag tick.
  const widthRef = useRef(width);

  const applyWidth = useCallback((n: number) => {
    const c = clamp(n);
    widthRef.current = c;
    setWidth(c);
  }, [clamp]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current || !ref.current) return;
      applyWidth(e.clientX - ref.current.getBoundingClientRect().left);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      localStorage.setItem(storageKey, String(Math.round(widthRef.current)));
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [applyWidth, storageKey]);

  const startDrag = () => {
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div ref={ref} style={{ width }} className="relative shrink-0 h-full">
      {children}
      {/* Drag handle straddling the right edge. Wider hit area than its visible
          1px line so it's easy to grab; highlights on hover/drag. */}
      <div
        onMouseDown={startDrag}
        onDoubleClick={() => applyWidth(defaultWidth)}
        title="Drag to resize · double-click to reset"
        className="absolute top-0 right-0 h-full w-2 cursor-col-resize z-10 group"
        style={{ transform: "translateX(50%)" }}
      >
        <div className="mx-auto h-full w-px bg-transparent group-hover:bg-[var(--accent)] transition-colors" />
      </div>
    </div>
  );
}
