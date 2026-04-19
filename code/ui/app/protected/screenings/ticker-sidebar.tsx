"use client";

import { useCallback, useEffect, useRef } from "react";
import type { FmpQuote } from "@/lib/use-quotes";

interface TickerSidebarProps {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string; subSector: string };
  getStatus: (ticker: string) => string;
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  getSymbolNote?: (ticker: string) => string | null;
  onContextMenu?: (ticker: string, e: React.MouseEvent) => void;
  quotes: Record<string, FmpQuote | null>;
}

export function TickerSidebar({
  symbols,
  selectedTicker,
  onSelect,
  getTickerMeta,
  getStatus,
  dismissedSymbols,
  highlightedSymbols,
  getSymbolNote,
  onContextMenu,
  quotes,
}: TickerSidebarProps) {
  const listRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const currentIdx = selectedTicker ? symbols.indexOf(selectedTicker) : -1;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const nextIdx = e.key === "ArrowDown"
          ? (currentIdx < symbols.length - 1 ? currentIdx + 1 : 0)
          : (currentIdx > 0 ? currentIdx - 1 : symbols.length - 1);
        if (symbols[nextIdx]) onSelect(symbols[nextIdx]);
      }
    },
    [symbols, selectedTicker, onSelect]
  );

  useEffect(() => {
    if (!selectedTicker || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-ticker="${selectedTicker}"]`);
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedTicker]);

  return (
    <div className="flex flex-col h-full bg-background" onKeyDown={handleKeyDown}>
      <div className="shrink-0 px-3 grid grid-cols-[1fr_auto_auto] gap-x-2 items-center bg-muted/40 border-b border-border py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
        <span>Symbol</span>
        <span className="text-right">Last</span>
        <span className="text-right">Chg%</span>
      </div>
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto divide-y divide-border">
        {symbols.length === 0 && (
          <p className="text-xs text-muted-foreground py-4 text-center">No tickers match.</p>
        )}
        {symbols.map(sym => {
          const q = quotes[sym];
          const isSelected = sym === selectedTicker;
          const status = getStatus(sym);
          const isDismissed = dismissedSymbols.has(sym);
          const isHighlighted = highlightedSymbols.has(sym);
          const note = getSymbolNote?.(sym);
          const statusStripe: Record<string, string> = {
            dismissed: "border-l-rose-400",
            watchlist: "border-l-amber-400",
            pipeline: "border-l-sky-400",
            active: "border-l-emerald-400",
          };
          const stripe = isDismissed || isHighlighted || isSelected
            ? statusStripe[status] ?? "border-l-transparent"
            : "";
          const chgColor = q
            ? q.changePercentage >= 0
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-rose-500"
            : "";
          const meta = getTickerMeta(sym);

          return (
            <button
              key={sym}
              data-ticker={sym}
              type="button"
              onClick={() => onSelect(sym)}
              onContextMenu={(e) => onContextMenu?.(sym, e)}
              className={`group w-full text-left px-3 py-2 grid grid-cols-[1fr_auto_auto] gap-x-2 items-center transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${
                isSelected
                  ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20"
                  : isHighlighted
                    ? "bg-amber-500/10 hover:bg-amber-500/15"
                    : "hover:bg-muted/30"
              }`}
              title={[sym, meta.sector, meta.industry, meta.subSector, note].filter(Boolean).join(" · ")}
            >
              <span className="truncate">
                <span className="font-mono font-semibold text-sm">{sym}</span>
                {meta.sector && (
                  <span className="text-[10px] text-muted-foreground ml-1.5 hidden xl:inline">{meta.sector}</span>
                )}
                {meta.subSector && (
                  <span className="block text-[10px] text-muted-foreground leading-tight truncate">{meta.subSector}</span>
                )}
              </span>
              <span className={`text-xs tabular-nums text-right ${isSelected ? "font-medium" : "text-muted-foreground"}`}>
                {q ? `$${q.price.toFixed(2)}` : "—"}
              </span>
              <span className={`text-xs tabular-nums font-medium text-right ${chgColor}`}>
                {q ? `${q.changePercentage >= 0 ? "+" : ""}${q.changePercentage.toFixed(2)}%` : "—"}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
