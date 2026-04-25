"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, AlignJustify, X } from "lucide-react";
import type { FmpQuote } from "@/lib/use-quotes";

interface MobileTickerBarProps {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  quotes: Record<string, FmpQuote | null>;
  getStatus: (ticker: string) => string;
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
}

export function MobileTickerBar({
  symbols,
  selectedTicker,
  onSelect,
  quotes,
  getStatus,
  dismissedSymbols,
  highlightedSymbols,
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

  const statusStripe: Record<string, string> = {
    dismissed: "border-l-rose-400",
    watchlist: "border-l-amber-400",
    pipeline: "border-l-sky-400",
    active: "border-l-emerald-400",
  };

  return (
    <>
      {/* Sticky nav bar — mobile only */}
      <div className="sm:hidden flex items-center h-12 border-b border-border bg-background shrink-0 px-1 gap-0.5">
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
              <span className="font-mono font-bold text-sm leading-tight">{selectedTicker}</span>
              <span className="text-[11px] text-muted-foreground leading-tight">
                {currentIdx + 1} of {symbols.length}
                {q && (
                  <span className={`ml-1.5 ${chgColor}`}>
                    {q.changePercentage >= 0 ? "+" : ""}{q.changePercentage.toFixed(2)}%
                  </span>
                )}
              </span>
            </>
          ) : (
            <span className="text-sm text-muted-foreground">Tap to select ticker</span>
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
        style={{ maxHeight: "78dvh" }}
      >
        {/* Drag handle */}
        <div className="flex items-center justify-center pt-2.5 pb-1">
          <div className="w-10 h-1 rounded-full bg-border" />
        </div>

        <div className="flex items-center justify-between px-4 py-2 border-b border-border">
          <span className="text-sm font-semibold">
            Tickers <span className="text-muted-foreground font-normal">({symbols.length})</span>
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

        <div className="overflow-y-auto" style={{ maxHeight: "calc(78dvh - 5rem)" }}>
          {symbols.map((sym, idx) => {
            const sq = quotes[sym];
            const isSelected = sym === selectedTicker;
            const isDismissed = dismissedSymbols.has(sym);
            const isHighlighted = highlightedSymbols.has(sym);
            const status = getStatus(sym);
            const stripe = isDismissed || isHighlighted || isSelected
              ? (statusStripe[status] ?? "border-l-transparent")
              : "";
            const sqColor = sq
              ? sq.changePercentage >= 0
                ? "text-emerald-500"
                : "text-rose-500"
              : "";

            return (
              <button
                key={sym}
                type="button"
                onClick={() => {
                  onSelect(sym);
                  setSheetOpen(false);
                }}
                className={`w-full text-left flex items-center justify-between px-4 py-3 border-l-[3px] border-b border-border/50 transition-colors min-h-[48px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${
                  isSelected
                    ? "bg-foreground/10"
                    : isHighlighted
                      ? "bg-amber-500/10"
                      : "hover:bg-muted/30"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground w-6 tabular-nums text-right">{idx + 1}</span>
                  <span className="font-mono font-semibold text-sm">{sym}</span>
                </div>
                <div className="flex items-center gap-2 text-xs tabular-nums">
                  <span className="text-muted-foreground">
                    {sq ? `$${sq.price.toFixed(2)}` : "—"}
                  </span>
                  {sq && (
                    <span className={`font-medium ${sqColor}`}>
                      {sq.changePercentage >= 0 ? "+" : ""}{sq.changePercentage.toFixed(2)}%
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </>
  );
}
