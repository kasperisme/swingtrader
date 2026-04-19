"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy, MessageSquare, RotateCcw, Trash2 } from "lucide-react";

export type NoteStatus = "active" | "dismissed" | "watchlist" | "pipeline";

interface TickerContextMenuProps {
  ticker: string;
  x: number;
  y: number;
  onClose: () => void;
  isDismissed: boolean;
  onDismiss: () => void;
  onRestore: () => void;
  status: NoteStatus;
  onSetStatus: (s: NoteStatus) => void;
  hasComment: boolean;
  onEditComment: () => void;
  onCopyOhlcv: (() => void) | null;
}

const STATUS_OPTS: { value: NoteStatus; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "watchlist", label: "Watchlist" },
  { value: "pipeline", label: "Pipeline" },
  { value: "dismissed", label: "Dismissed" },
];

export function TickerContextMenu({
  ticker,
  x,
  y,
  onClose,
  isDismissed,
  onDismiss,
  onRestore,
  status,
  onSetStatus,
  hasComment,
  onEditComment,
  onCopyOhlcv,
}: TickerContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Clamp to viewport after first render
  useEffect(() => {
    if (!ref.current) return;
    const { width, height } = ref.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    setPos({
      left: x + width > vw ? Math.max(0, vw - width - 8) : x,
      top: y + height > vh ? Math.max(0, vh - height - 8) : y,
    });
  }, [x, y]);

  useEffect(() => {
    const down = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [onClose]);

  function act(fn: () => void) {
    fn();
    onClose();
  }

  return (
    <div
      ref={ref}
      style={{ position: "fixed", left: pos.left, top: pos.top }}
      className="z-[9999] min-w-[172px] rounded-lg border border-border bg-popover text-popover-foreground shadow-xl ring-1 ring-black/5 dark:ring-white/10 py-1 select-none"
    >
      <div className="px-3 py-1.5 text-xs font-semibold font-mono text-muted-foreground border-b border-border mb-1">
        {ticker}
      </div>

      <button
        type="button"
        onClick={() => act(isDismissed ? onRestore : onDismiss)}
        className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-sm transition-colors hover:bg-muted/80 ${
          isDismissed
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-rose-500"
        }`}
      >
        {isDismissed
          ? <RotateCcw className="w-3.5 h-3.5 shrink-0" />
          : <Trash2 className="w-3.5 h-3.5 shrink-0" />}
        {isDismissed ? "Restore" : "Dismiss"}
      </button>

      <div className="border-t border-border mt-1 pt-1">
        {STATUS_OPTS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            onClick={() => act(() => onSetStatus(value))}
            className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-sm transition-colors hover:bg-muted/80"
          >
            {label}
            {status === value && (
              <Check className="w-3.5 h-3.5 text-foreground shrink-0" />
            )}
          </button>
        ))}
      </div>

      <div className="border-t border-border mt-1 pt-1">
        <button
          type="button"
          onClick={() => act(onEditComment)}
          className="w-full flex items-center gap-2.5 px-3 py-1.5 text-sm transition-colors hover:bg-muted/80"
        >
          <MessageSquare className="w-3.5 h-3.5 shrink-0" />
          {hasComment ? "Edit note" : "Add note"}
        </button>

        {onCopyOhlcv && (
          <button
            type="button"
            onClick={() => act(onCopyOhlcv)}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-sm transition-colors hover:bg-muted/80"
          >
            <Copy className="w-3.5 h-3.5 shrink-0" />
            Copy OHLCV
          </button>
        )}
      </div>
    </div>
  );
}
