"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FmpQuote } from "@/lib/use-quotes";
import type { EntryMarker } from "@/components/ticker-charts/types";

type SortKey = "symbol" | "price" | "change" | "dist";
type SortDir = "asc" | "desc";

interface TickerSidebarProps {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  getTickerMeta: (ticker: string) => { sector: string; industry: string; subSector: string };
  getStatus: (ticker: string) => string;
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  activePositionSymbols?: Set<string>;
  getSymbolNote?: (ticker: string) => string | null;
  onContextMenu?: (ticker: string, e: React.MouseEvent) => void;
  quotes: Record<string, FmpQuote | null>;
  streamingTickers?: Set<string>;
  getEntryMarker?: (ticker: string) => EntryMarker | null;
}

function SortArrow({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <span className="text-muted-foreground/40">↕</span>;
  return <span>{dir === "asc" ? "↑" : "↓"}</span>;
}

export function TickerSidebar({
  symbols,
  selectedTicker,
  onSelect,
  getTickerMeta,
  getStatus,
  dismissedSymbols,
  highlightedSymbols,
  activePositionSymbols,
  getSymbolNote,
  onContextMenu,
  quotes,
  streamingTickers,
  getEntryMarker,
}: TickerSidebarProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? "asc" : "desc");
    }
  }

  const sortedSymbols = useMemo(() => {
    return [...symbols].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "symbol") {
        cmp = a.localeCompare(b);
      } else if (sortKey === "price") {
        const pa = quotes[a]?.price ?? null;
        const pb = quotes[b]?.price ?? null;
        if (pa === null && pb === null) cmp = 0;
        else if (pa === null) cmp = 1;
        else if (pb === null) cmp = -1;
        else cmp = pa - pb;
      } else if (sortKey === "change") {
        const ca = quotes[a]?.changePercentage ?? null;
        const cb = quotes[b]?.changePercentage ?? null;
        if (ca === null && cb === null) cmp = 0;
        else if (ca === null) cmp = 1;
        else if (cb === null) cmp = -1;
        else cmp = ca - cb;
      } else if (sortKey === "dist") {
        const distOf = (sym: string) => {
          const q = quotes[sym];
          const entry = getEntryMarker?.(sym);
          if (!q || !entry || Math.abs(entry.price) < 1e-9) return null;
          const close = q.previousClose ?? q.price;
          return ((close - entry.price) / entry.price) * 100;
        };
        const da = distOf(a);
        const db = distOf(b);
        if (da === null && db === null) cmp = 0;
        else if (da === null) cmp = 1;
        else if (db === null) cmp = -1;
        else cmp = da - db;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [symbols, sortKey, sortDir, quotes, getEntryMarker]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const currentIdx = selectedTicker ? sortedSymbols.indexOf(selectedTicker) : -1;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const nextIdx = e.key === "ArrowDown"
          ? (currentIdx < sortedSymbols.length - 1 ? currentIdx + 1 : 0)
          : (currentIdx > 0 ? currentIdx - 1 : sortedSymbols.length - 1);
        if (sortedSymbols[nextIdx]) onSelect(sortedSymbols[nextIdx]);
      }
    },
    [sortedSymbols, selectedTicker, onSelect]
  );

  useEffect(() => {
    if (!selectedTicker || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-ticker="${selectedTicker}"]`);
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedTicker]);

  const headerBtn = "text-right cursor-pointer select-none hover:text-foreground transition-colors inline-flex items-center gap-0.5 justify-end";

  return (
    <div className="flex flex-col h-full bg-background" onKeyDown={handleKeyDown}>
      <div className="shrink-0 px-3 grid grid-cols-[1fr_auto_auto_auto] gap-x-2 items-center bg-muted/40 border-b border-border py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
        <button type="button" className={`text-left cursor-pointer select-none hover:text-foreground transition-colors inline-flex items-center gap-0.5`} onClick={() => toggleSort("symbol")}>
          Symbol <SortArrow active={sortKey === "symbol"} dir={sortDir} />
        </button>
        <button type="button" className={headerBtn} onClick={() => toggleSort("price")}>
          <SortArrow active={sortKey === "price"} dir={sortDir} /> Last
        </button>
        <button type="button" className={headerBtn} onClick={() => toggleSort("change")}>
          <SortArrow active={sortKey === "change"} dir={sortDir} /> Chg%
        </button>
        <button type="button" className={headerBtn} onClick={() => toggleSort("dist")} title="Distance to entry marker (% from current price)">
          <SortArrow active={sortKey === "dist"} dir={sortDir} /> Dist
        </button>
      </div>
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto divide-y divide-border">
        {sortedSymbols.length === 0 && (
          <p className="text-xs text-muted-foreground py-4 text-center">No tickers match.</p>
        )}
        {sortedSymbols.map(sym => {
          const q = quotes[sym];
          const entry = getEntryMarker?.(sym) ?? null;
          const isSelected = sym === selectedTicker;
          const isStreaming = streamingTickers?.has(sym) ?? false;
          const status = getStatus(sym);
          const isDismissed = dismissedSymbols.has(sym);
          const isHighlighted = highlightedSymbols.has(sym);
          const hasPosition = activePositionSymbols?.has(sym) ?? false;
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

          let distDisplay = "—";
          let distColor = "text-muted-foreground";
          if (q && entry && Math.abs(entry.price) > 1e-9) {
            const close = q.previousClose ?? q.price;
            const dist = ((close - entry.price) / entry.price) * 100;
            const sign = dist >= 0 ? "+" : "";
            distDisplay = `${sign}${dist.toFixed(1)}%`;
            distColor = dist >= 0
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-rose-500";
          }

          const meta = getTickerMeta(sym);

          return (
            <button
              key={sym}
              data-ticker={sym}
              type="button"
              onClick={() => onSelect(sym)}
              onContextMenu={(e) => onContextMenu?.(sym, e)}
              className={`group w-full text-left px-3 py-2 grid grid-cols-[1fr_auto_auto_auto] gap-x-2 items-center transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${
                isSelected
                  ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20"
                  : isHighlighted
                    ? "bg-amber-500/10 hover:bg-amber-500/15"
                    : "hover:bg-muted/30"
              }`}
              title={[sym, meta.sector, meta.industry, meta.subSector, note].filter(Boolean).join(" · ")}
            >
              <span className="truncate">
                <span className="inline-flex items-center gap-1.5">
                  {hasPosition && (
                    <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-emerald-400" title="Active position" />
                  )}
                  <span className="font-mono font-semibold text-sm">{sym}</span>
                  {isStreaming && (
                    <span className="inline-flex items-center gap-0.5" title="AI thinking…">
                      <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce [animation-delay:-0.3s]" />
                      <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce [animation-delay:-0.15s]" />
                      <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce" />
                    </span>
                  )}
                </span>
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
              <span className={`text-xs tabular-nums font-medium text-right ${distColor}`}>
                {distDisplay}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
