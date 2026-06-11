"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Eye, EyeOff, MoreHorizontal, StickyNote } from "lucide-react";
import type { FmpQuote } from "@/lib/use-quotes";
import type { EntryMarker } from "@/components/ticker-charts/types";

type SortKey = "symbol" | "price" | "change" | "dist";
type SortDir = "asc" | "desc";

interface TickerSidebarProps {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  getTickerMeta: (ticker: string) => {
    sector: string;
    industry: string;
    subSector: string;
  };
  getStatus: (ticker: string) => string;
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  activePositionSymbols?: Set<string>;
  getSymbolNote?: (ticker: string) => string | null;
  onContextMenu?: (ticker: string, e: React.MouseEvent) => void;
  onOpenActions?: (ticker: string, anchorEl: HTMLElement) => void;
  quotes: Record<string, FmpQuote | null>;
  streamingTickers?: Set<string>;
  getEntryMarker?: (ticker: string) => EntryMarker | null;
  hiddenDismissedCount?: number;
  showDismissed?: boolean;
  onToggleShowDismissed?: () => void;
  /** Fires whenever the visible sort order changes — lets the parent jump to
   * the next ticker in the user's actual visible order (e.g. after dismiss). */
  onSortedOrderChange?: (sortedSymbols: string[]) => void;
  /** Simplified two-column layout (Symbol + Chg%) for non-technical users.
   * Hides Last / Dist columns and locks sort to symbol. */
  isCaveman?: boolean;
  /** Optional search / add-ticker control pinned at the top of the sidebar, so
   * it stays reachable when the screening's top controls are collapsed (both
   * caveman and businessman mode). */
  searchSlot?: ReactNode;
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
  onOpenActions,
  quotes,
  streamingTickers,
  getEntryMarker,
  hiddenDismissedCount = 0,
  showDismissed = false,
  onToggleShowDismissed,
  onSortedOrderChange,
  isCaveman = false,
  searchSlot,
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

  useEffect(() => {
    if (sortedSymbols.length === 0) return;

    function isEditableTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      if (target.isContentEditable) return true;
      const tag = target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      return false;
    }

    function onKey(e: KeyboardEvent) {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      const currentIdx = selectedTicker
        ? sortedSymbols.indexOf(selectedTicker)
        : -1;
      const nextIdx =
        e.key === "ArrowDown"
          ? currentIdx < sortedSymbols.length - 1
            ? currentIdx + 1
            : 0
          : currentIdx > 0
            ? currentIdx - 1
            : sortedSymbols.length - 1;
      if (sortedSymbols[nextIdx]) onSelect(sortedSymbols[nextIdx]);
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sortedSymbols, selectedTicker, onSelect]);

  useEffect(() => {
    if (!selectedTicker || !listRef.current) return;
    const safe = CSS.escape(selectedTicker);
    const el = listRef.current.querySelector(`[data-ticker="${safe}"]`);
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedTicker]);

  useEffect(() => {
    onSortedOrderChange?.(sortedSymbols);
  }, [sortedSymbols, onSortedOrderChange]);

  const headerBtn =
    "text-right cursor-pointer select-none hover:text-foreground transition-colors inline-flex items-center gap-0.5 justify-end";

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      {searchSlot && (
        <div className="shrink-0 border-b border-border bg-background p-2">
          {searchSlot}
        </div>
      )}
      {hiddenDismissedCount > 0 && onToggleShowDismissed && (
        <button
          type="button"
          onClick={onToggleShowDismissed}
          className="shrink-0 flex items-center justify-between gap-2 px-2 py-1.5 border-b border-border bg-muted/30 hover:bg-muted/50 transition-colors text-left"
          title={
            showDismissed
              ? "Hide dismissed tickers from this list"
              : "Show dismissed tickers in this list"
          }
        >
          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            {showDismissed ? (
              <EyeOff className="w-3 h-3" />
            ) : (
              <Eye className="w-3 h-3" />
            )}
            <span>
              {showDismissed
                ? `Hiding ${hiddenDismissedCount} dismissed`
                : `${hiddenDismissedCount} dismissed hidden`}
            </span>
          </span>
          <span className="text-[10px] font-mono uppercase tracking-[0.1em] text-foreground/80">
            {showDismissed ? "Hide" : "Show"}
          </span>
        </button>
      )}
      {isCaveman ? (
        <div className="shrink-0 px-2 grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_1.25rem] gap-x-1.5 items-center bg-muted/40 border-b border-border py-2 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
          <span className="text-left">Stock</span>
          <span className="text-right">Today</span>
          <span className="w-6" aria-hidden />
        </div>
      ) : (
        <div className="shrink-0 px-2 grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_1.25rem] gap-x-1.5 items-center bg-muted/30 border-b border-border py-2 text-[10px] font-mono uppercase tracking-[0.12em] text-muted-foreground/80">
          <button
            type="button"
            className={`text-left cursor-pointer select-none hover:text-foreground transition-colors inline-flex items-center gap-0.5`}
            onClick={() => toggleSort("symbol")}
          >
            Symbol <SortArrow active={sortKey === "symbol"} dir={sortDir} />
          </button>
          <button
            type="button"
            className={headerBtn}
            onClick={() => toggleSort("price")}
          >
            <SortArrow active={sortKey === "price"} dir={sortDir} /> Last
          </button>
          <button
            type="button"
            className={headerBtn}
            onClick={() => toggleSort("change")}
          >
            <SortArrow active={sortKey === "change"} dir={sortDir} /> Chg%
          </button>
          <button
            type="button"
            className={headerBtn}
            onClick={() => toggleSort("dist")}
            title="Distance to entry marker (% from current price)"
          >
            <SortArrow active={sortKey === "dist"} dir={sortDir} /> Dist
          </button>
          <span className="w-6" aria-hidden />
        </div>
      )}
      <div
        ref={listRef}
        className="max-h-full min-h-0 flex-1 overflow-y-auto divide-y divide-border"
      >
        {sortedSymbols.length === 0 && (
          <p className="text-xs text-muted-foreground py-4 text-center">
            No tickers match.
          </p>
        )}
        {sortedSymbols.map((sym) => {
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
            dismissed: "#fb7185",
            watchlist: "#fbbf24",
            pipeline: "#38bdf8",
            active: "#34d399",
          };
          const stripe = statusStripe[status] ?? "transparent";
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
            distColor =
              dist >= 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-rose-500";
          }

          const meta = getTickerMeta(sym);


          return (
            <div
              key={sym}
              data-ticker={sym}
              onClick={() => onSelect(sym)}
              onContextMenu={(e) => onContextMenu?.(sym, e)}
              style={{ borderLeftColor: stripe }}
              className={`group w-full border-l-[3px] border-l-transparent ${isDismissed ? "opacity-40" : ""} ${
                isSelected
                  ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20"
                  : isHighlighted
                    ? "bg-amber-500/10 hover:bg-amber-500/15"
                    : "hover:bg-muted/30"
              }`}
              title={[sym, meta.sector, meta.industry, meta.subSector, note]
                .filter(Boolean)
                .join(" · ")}
            >
              <div
                className={`grid items-start gap-x-1.5 px-2 py-2 ${
                  isCaveman
                    ? "grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_1.25rem]"
                    : "grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_1.25rem]"
                }`}
              >
                <div className="min-w-0 text-left">
                  <span className="flex min-w-0 items-center gap-1.5">
                    {hasPosition && (
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400"
                        title="Active position"
                      />
                    )}
                    <span
                      className={`min-w-0 truncate font-mono text-sm font-semibold ${isDismissed ? "line-through" : ""}`}
                    >
                      {sym}
                    </span>
                    {note && (
                      <StickyNote
                        className="w-3 h-3 shrink-0 text-amber-500"
                        aria-label="Has note"
                      />
                    )}
                    {isStreaming && (
                      <span
                        className="inline-flex shrink-0 items-center gap-0.5"
                        title="AI thinking…"
                      >
                        <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce [animation-delay:-0.3s]" />
                        <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce [animation-delay:-0.15s]" />
                        <span className="w-1 h-1 rounded-full bg-amber-400 animate-bounce" />
                      </span>
                    )}
                  </span>
                  {meta.sector && (
                    <span className="block min-w-0 truncate text-[10px] leading-tight text-muted-foreground">
                      {meta.sector}
                    </span>
                  )}
                  {!isCaveman && meta.subSector && (
                    <span className="block min-w-0 truncate text-[10px] leading-tight text-muted-foreground">
                      {meta.subSector}
                    </span>
                  )}
                </div>
                {!isCaveman && (
                  <span
                    className={`self-start truncate pt-0.5 text-xs tabular-nums text-right ${isSelected ? "font-medium" : "text-muted-foreground"}`}
                  >
                    {q ? `$${q.price.toFixed(2)}` : "—"}
                  </span>
                )}
                <span
                  className={`self-start truncate pt-0.5 text-xs tabular-nums font-medium text-right ${chgColor}`}
                >
                  {q
                    ? `${q.changePercentage >= 0 ? "+" : ""}${q.changePercentage.toFixed(2)}%`
                    : "—"}
                </span>
                {!isCaveman && (
                  <span
                    className={`self-start truncate pt-0.5 text-xs tabular-nums font-medium text-right ${distColor}`}
                  >
                    {distDisplay}
                  </span>
                )}
                <button
                  type="button"
                  className="h-6 w-6 shrink-0 self-start rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title={`Actions for ${sym}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenActions?.(sym, e.currentTarget);
                  }}
                >
                  <MoreHorizontal className="mx-auto h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
