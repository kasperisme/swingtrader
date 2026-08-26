"use client";

import { useEffect, useRef, useState } from "react";
import { Bell, Check, Copy, MessageSquare, RotateCcw, Trash2 } from "lucide-react";

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
  onSetupAgentAlarm?: () => void;
}

const STAGE_OPTS: { value: Exclude<NoteStatus, "dismissed">; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "watchlist", label: "Watchlist" },
  { value: "pipeline", label: "Pipeline" },
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
  onSetupAgentAlarm,
}: TickerContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

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
    const down = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("keydown", key);
    };
  }, [onClose]);

  function act(fn: () => void) {
    fn();
    onClose();
  }

  const stageStatus: Exclude<NoteStatus, "dismissed"> =
    status === "dismissed" ? "active" : status;

  return (
    <div
      ref={ref}
      style={{ position: "fixed", left: pos.left, top: pos.top }}
      className="z-[9999] min-w-[200px] rounded-lg border border-border bg-popover text-popover-foreground shadow-xl ring-1 ring-black/5 dark:ring-white/10 py-1 select-none"
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border mb-1">
        <span className="text-xs font-semibold font-mono text-muted-foreground">
          {ticker}
        </span>
        {isDismissed && (
          <span className="text-[9px] font-mono uppercase tracking-[0.12em] text-rose-500">
            Dismissed
          </span>
        )}
      </div>

      <div className="px-3 pt-1 pb-0.5 text-[9px] font-mono uppercase tracking-[0.14em] text-muted-foreground/70">
        Stage
      </div>
      {STAGE_OPTS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          onClick={() => act(() => onSetStatus(value))}
          disabled={isDismissed}
          className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-sm transition-colors hover:bg-muted/80 disabled:opacity-40 disabled:hover:bg-transparent"
        >
          {label}
          {stageStatus === value && !isDismissed && (
            <Check className="w-3.5 h-3.5 text-foreground shrink-0" />
          )}
        </button>
      ))}

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

        {onSetupAgentAlarm && (
          <button
            type="button"
            onClick={() => act(onSetupAgentAlarm)}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-sm text-amber-500 transition-colors hover:bg-amber-500/10"
          >
            <Bell className="w-3.5 h-3.5 shrink-0" />
            Setup agent alarm
          </button>
        )}
      </div>

      <div className="border-t border-border mt-1 pt-1">
        <button
          type="button"
          onClick={() => act(isDismissed ? onRestore : onDismiss)}
          className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-sm transition-colors ${
            isDismissed
              ? "text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10"
              : "text-rose-500 hover:bg-rose-500/10"
          }`}
        >
          {isDismissed ? (
            <RotateCcw className="w-3.5 h-3.5 shrink-0" />
          ) : (
            <Trash2 className="w-3.5 h-3.5 shrink-0" />
          )}
          {isDismissed ? "Restore ticker" : "Dismiss ticker"}
        </button>
      </div>
    </div>
  );
}
