import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

interface FeedbackDialogProps {
  rating: "up" | "down";
  value: string;
  onChange: (v: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}

const COPY = {
  up: {
    title: "Give positive feedback",
    placeholder: "What was satisfying about this response?",
  },
  down: {
    title: "Give negative feedback",
    placeholder: "What was unsatisfying about this response?",
  },
} as const;

/**
 * Centered modal for attaching an optional comment to a thumbs-up/down
 * rating. Rendered through a portal so it floats above the scrolling
 * conversation regardless of ancestor overflow/stacking. The rating itself
 * is already persisted by the time this opens — submitting only adds the
 * comment, and cancelling leaves the bare rating intact.
 */
export function FeedbackDialog({ rating, value, onChange, onCancel, onSubmit }: FeedbackDialogProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const copy = COPY[rating];

  // Focus the textarea on open and close on Escape.
  useEffect(() => {
    textareaRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(40, 30, 20, 0.45)" }}
      onMouseDown={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={copy.title}
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
        style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold mb-4" style={{ color: "var(--text-primary)" }}>
          {copy.title}
        </h2>

        <label className="block text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
          Please provide details: <span className="opacity-70">(optional)</span>
        </label>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit();
          }}
          rows={3}
          placeholder={copy.placeholder}
          className="w-full text-sm p-3 rounded-xl resize-none outline-none transition-shadow focus:ring-2 focus:ring-[var(--accent)]"
          style={{
            background: "var(--bg-input)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          }}
        />

        <p className="text-xs italic mt-3" style={{ color: "var(--text-secondary)" }}>
          Your feedback is saved with this conversation to help improve responses.
        </p>

        <div className="flex justify-end gap-2 mt-5">
          <button
            onClick={onSubmit}
            className="px-4 py-2 text-sm font-medium rounded-lg cursor-pointer transition-opacity hover:opacity-90"
            style={{ background: "var(--accent)", color: "white" }}
          >
            Submit
          </button>
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium rounded-lg cursor-pointer transition-colors hover:bg-[var(--border)]"
            style={{ color: "var(--text-primary)", border: "1px solid var(--border)" }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
