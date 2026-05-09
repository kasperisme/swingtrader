"use client";

import { useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  AlignJustify,
  X,
  MoreHorizontal,
  StickyNote,
  Eye,
  EyeOff,
  RotateCcw,
  Trash2,
} from "lucide-react";
import type { FmpQuote } from "@/lib/use-quotes";

interface MobileTickerBarProps {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  quotes: Record<string, FmpQuote | null>;
  getStatus: (ticker: string) => string;
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  getNote?: (ticker: string) => string | null;
  onOpenActions?: (ticker: string, anchorEl: HTMLElement) => void;
  onEditNote?: (ticker: string) => void;
  onDismiss?: (ticker: string) => void;
  onRestore?: (ticker: string) => void;
  hiddenDismissedCount?: number;
  showDismissed?: boolean;
  onToggleShowDismissed?: () => void;
}

export function MobileTickerBar({
  symbols,
  selectedTicker,
  onSelect,
  quotes,
  getStatus,
  dismissedSymbols,
  highlightedSymbols,
  getNote,
  onOpenActions,
  onEditNote,
  onDismiss,
  onRestore,
  hiddenDismissedCount = 0,
  showDismissed = false,
  onToggleShowDismissed,
}: MobileTickerBarProps) {
  const [sheetOpen, setSheetOpen] = useState(false);

  const currentIdx = selectedTicker ? symbols.indexOf(selectedTicker) : -1;
  const canPrev = currentIdx > 0;
  const canNext = currentIdx < symbols.length - 1 && currentIdx >= 0;

  function goPrev() {
    if (canPrev && symbols[currentIdx - 1]) onSelect(symbols[currentIdx - 1]!);
  }

  function goNext() {
    if (canNext && symbols[currentIdx + 1]) onSelect(symbols[currentIdx + 1]!);
  }

  const q = selectedTicker ? quotes[selectedTicker] : null;
  const chgColor = q
    ? q.changePercentage >= 0
      ? "text-emerald-500"
      : "text-rose-500"
    : "";
  const selectedNote = selectedTicker ? getNote?.(selectedTicker) ?? null : null;
  const selectedDismissed = selectedTicker
    ? dismissedSymbols.has(selectedTicker)
    : false;

  const statusStripe: Record<string, string> = {
    dismissed: "border-l-rose-400",
    watchlist: "border-l-amber-400",
    pipeline: "border-l-sky-400",
    active: "border-l-emerald-400",
  };

  return (
    <>
      {/* Sticky nav bar — mobile only, pinned at the bottom of the screenings layout */}
      <div className="sm:hidden flex flex-col border-t border-border bg-background shrink-0">
        <div className="flex items-center h-12 px-1 gap-0.5">
          <button
            type="button"
            disabled={!canPrev}
            onClick={goPrev}
            className="flex items-center justify-center w-11 h-11 rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
            aria-label="Previous ticker"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>

          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            className="flex-1 min-w-0 flex flex-col items-center justify-center h-11 cursor-pointer"
            aria-label="Open ticker list"
          >
            {selectedTicker ? (
              <>
                <span
                  className={`font-mono font-bold text-sm leading-tight ${selectedDismissed ? "line-through text-muted-foreground" : ""}`}
                >
                  {selectedTicker}
                </span>
                <span className="text-[11px] text-muted-foreground leading-tight">
                  {currentIdx + 1} of {symbols.length}
                  {q && (
                    <span className={`ml-1.5 ${chgColor}`}>
                      {q.changePercentage >= 0 ? "+" : ""}
                      {q.changePercentage.toFixed(2)}%
                    </span>
                  )}
                </span>
              </>
            ) : (
              <span className="text-sm text-muted-foreground">
                Tap to select ticker
              </span>
            )}
          </button>

          <button
            type="button"
            disabled={!canNext}
            onClick={goNext}
            className="flex items-center justify-center w-11 h-11 rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
            aria-label="Next ticker"
          >
            <ChevronRight className="w-5 h-5" />
          </button>

          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            className="flex items-center justify-center w-11 h-11 rounded-md text-muted-foreground hover:text-foreground transition-colors"
            aria-label="All tickers"
          >
            <AlignJustify className="w-4 h-4" />
          </button>
        </div>

        {/* Selected-ticker action strip: note + dismiss / restore */}
        {selectedTicker && (
          <button
            type="button"
            onClick={() => onEditNote?.(selectedTicker)}
            className="group flex items-center gap-2 px-3 py-1.5 border-t border-border/60 text-left active:bg-muted/40 transition-colors"
          >
            <StickyNote
              className={`w-3.5 h-3.5 shrink-0 ${selectedNote ? "text-amber-500" : "text-muted-foreground/50"}`}
            />
            <span
              className={`flex-1 min-w-0 truncate text-[12px] leading-tight ${selectedNote ? "text-foreground/90 italic" : "text-muted-foreground"}`}
            >
              {selectedNote ?? "Add a note"}
            </span>
            {selectedDismissed ? (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  onRestore?.(selectedTicker);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    onRestore?.(selectedTicker);
                  }
                }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-mono uppercase tracking-[0.1em] text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/10 transition-colors"
                aria-label={`Restore ${selectedTicker}`}
              >
                <RotateCcw className="w-3 h-3" />
                Restore
              </span>
            ) : (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  onDismiss?.(selectedTicker);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    onDismiss?.(selectedTicker);
                  }
                }}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-mono uppercase tracking-[0.1em] text-rose-500 hover:bg-rose-500/10 transition-colors"
                aria-label={`Dismiss ${selectedTicker}`}
              >
                <Trash2 className="w-3 h-3" />
                Dismiss
              </span>
            )}
          </button>
        )}
      </div>

      {/* Backdrop */}
      {sheetOpen && (
        <div
          className="sm:hidden fixed inset-0 z-40 bg-black/50"
          onClick={() => setSheetOpen(false)}
        />
      )}

      {/* Bottom sheet */}
      <div
        className={`sm:hidden fixed inset-x-0 bottom-0 z-50 bg-background border-t border-border rounded-t-2xl shadow-2xl transition-transform duration-300 ease-out ${
          sheetOpen ? "translate-y-0" : "translate-y-full"
        }`}
        style={{ maxHeight: "82dvh" }}
      >
        {/* Drag handle */}
        <div className="flex items-center justify-center pt-2.5 pb-1">
          <div className="w-10 h-1 rounded-full bg-border" />
        </div>

        <div className="flex items-center justify-between px-4 py-2 border-b border-border">
          <span className="text-sm font-semibold">
            Tickers{" "}
            <span className="text-muted-foreground font-normal">
              ({symbols.length})
            </span>
          </span>
          <button
            type="button"
            onClick={() => setSheetOpen(false)}
            className="flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Hidden-dismissed toggle banner */}
        {hiddenDismissedCount > 0 && onToggleShowDismissed && (
          <button
            type="button"
            onClick={onToggleShowDismissed}
            className="w-full flex items-center justify-between gap-2 px-4 py-2 border-b border-border bg-muted/30 hover:bg-muted/50 transition-colors"
          >
            <span className="flex items-center gap-2 text-[12px] text-muted-foreground">
              {showDismissed ? (
                <EyeOff className="w-3.5 h-3.5" />
              ) : (
                <Eye className="w-3.5 h-3.5" />
              )}
              <span>
                {showDismissed
                  ? `Hiding ${hiddenDismissedCount} dismissed`
                  : `${hiddenDismissedCount} dismissed hidden`}
              </span>
            </span>
            <span className="text-[11px] font-mono uppercase tracking-[0.1em] text-foreground/80">
              {showDismissed ? "Hide" : "Show"}
            </span>
          </button>
        )}

        <div
          className="overflow-y-auto"
          style={{
            maxHeight: `calc(82dvh - ${hiddenDismissedCount > 0 ? "9rem" : "5rem"})`,
          }}
        >
          {symbols.length === 0 && (
            <p className="text-xs text-muted-foreground py-8 text-center">
              No tickers in this list.
            </p>
          )}
          {symbols.map((sym, idx) => {
            const sq = quotes[sym];
            const isSelected = sym === selectedTicker;
            const isDismissed = dismissedSymbols.has(sym);
            const isHighlighted = highlightedSymbols.has(sym);
            const status = getStatus(sym);
            const stripe =
              isDismissed || isHighlighted || isSelected
                ? statusStripe[status] ?? "border-l-transparent"
                : "";
            const sqColor = sq
              ? sq.changePercentage >= 0
                ? "text-emerald-500"
                : "text-rose-500"
              : "";
            const note = getNote?.(sym) ?? null;

            return (
              <div
                key={sym}
                className={`w-full border-l-[3px] border-b border-border/50 transition-colors ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-50" : ""} ${
                  isSelected
                    ? "bg-foreground/10"
                    : isHighlighted
                      ? "bg-amber-500/10"
                      : "active:bg-muted/40"
                }`}
              >
                <div className="flex items-center gap-1 px-2 py-1">
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(sym);
                      setSheetOpen(false);
                    }}
                    className="flex min-w-0 flex-1 flex-col gap-0.5 px-2 py-2 text-left"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="text-[11px] text-muted-foreground w-5 tabular-nums text-right shrink-0">
                          {idx + 1}
                        </span>
                        <span
                          className={`font-mono font-semibold text-sm truncate ${isDismissed ? "line-through" : ""}`}
                        >
                          {sym}
                        </span>
                        {note && (
                          <StickyNote
                            className="w-3 h-3 shrink-0 text-amber-500"
                            aria-label="Has note"
                          />
                        )}
                      </div>
                      <div className="flex items-center gap-2 text-xs tabular-nums shrink-0">
                        <span className="text-muted-foreground">
                          {sq ? `$${sq.price.toFixed(2)}` : "—"}
                        </span>
                        {sq && (
                          <span className={`font-medium ${sqColor}`}>
                            {sq.changePercentage >= 0 ? "+" : ""}
                            {sq.changePercentage.toFixed(2)}%
                          </span>
                        )}
                      </div>
                    </div>
                    {note && (
                      <div className="pl-7 pr-1 text-[11px] italic leading-snug text-muted-foreground line-clamp-2">
                        {note}
                      </div>
                    )}
                  </button>
                  <button
                    type="button"
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors active:bg-muted active:text-foreground"
                    title={`Actions for ${sym}`}
                    aria-label={`Actions for ${sym}`}
                    onClick={(e) => onOpenActions?.(sym, e.currentTarget)}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
