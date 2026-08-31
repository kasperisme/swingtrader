"use client";

import React, { useState, useMemo } from "react";
import { Loader2 } from "lucide-react";
import { useQuotes, type FmpQuote } from "@/lib/use-quotes";
import type { NoteStatus } from "./screenings-types";

type QuoteSortKey =
  | "symbol"
  | "price"
  | "changePercentage"
  | "volume"
  | "marketCap"
  | "dayLow"
  | "dayHigh"
  | "yearLow"
  | "yearHigh"
  | "priceAvg50"
  | "priceAvg200";

export function QuotesView({
  symbols,
  quotes,
  loading,
  selectedTicker,
  onSelect,
  onOpenWorkflowEditor,
  dismissedSymbols,
  highlightedSymbols,
  getStatus,
}: {
  symbols: string[];
  quotes: Record<string, FmpQuote | null>;
  loading: boolean;
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  onOpenWorkflowEditor: (ticker: string) => void;
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  getStatus: (ticker: string) => string;
}) {
  const [error] = useState<string | null>(null);
  const QUOTE_SORT_KEYS: QuoteSortKey[] = [
    "symbol",
    "price",
    "changePercentage",
    "volume",
    "marketCap",
    "dayLow",
    "dayHigh",
    "yearLow",
    "yearHigh",
    "priceAvg50",
    "priceAvg200",
  ];
  const [sortKey, setSortKeyRaw] = useState<QuoteSortKey>(() => {
    try {
      const v = localStorage.getItem("quotes-sort-key") as QuoteSortKey;
      if (QUOTE_SORT_KEYS.includes(v)) return v;
    } catch {
      /* ignore */
    }
    return "symbol";
  });
  const [sortDir, setSortDirRaw] = useState<"asc" | "desc">(() => {
    try {
      const v = localStorage.getItem("quotes-sort-dir");
      if (v === "asc" || v === "desc") return v;
    } catch {
      /* ignore */
    }
    return "asc";
  });

  function setSortKey(k: QuoteSortKey) {
    setSortKeyRaw(k);
    try {
      localStorage.setItem("quotes-sort-key", k);
    } catch {
      /* ignore */
    }
  }
  function setSortDir(d: "asc" | "desc") {
    setSortDirRaw(d);
    try {
      localStorage.setItem("quotes-sort-dir", d);
    } catch {
      /* ignore */
    }
  }

  if (symbols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No stocks to show.
      </p>
    );
  }

  function fmtCap(v: number | null): string {
    if (v == null) return "—";
    if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
    if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
    return `$${v.toLocaleString()}`;
  }

  function fmtVol(v: number | null): string {
    if (v == null) return "—";
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
    return String(v);
  }

  function toggleSort(key: QuoteSortKey) {
    if (sortKey === key) {
      const next = sortDir === "asc" ? "desc" : "asc";
      setSortDir(next);
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? "asc" : "desc");
    }
  }

  const sortedSymbols = useMemo(() => {
    return [...symbols].sort((a, b) => {
      const qa = quotes[a];
      const qb = quotes[b];
      if (sortKey === "symbol") {
        return sortDir === "asc" ? a.localeCompare(b) : b.localeCompare(a);
      }
      const va = qa?.[sortKey] ?? -Infinity;
      const vb = qb?.[sortKey] ?? -Infinity;
      return sortDir === "asc"
        ? Number(va) - Number(vb)
        : Number(vb) - Number(va);
    });
  }, [symbols, quotes, sortKey, sortDir]);

  function ColHd({
    label,
    col,
    center,
  }: {
    label: string;
    col: QuoteSortKey;
    center?: boolean;
  }) {
    const active = sortKey === col;
    return (
      <th
        onClick={() => toggleSort(col)}
        className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground ${center ? "text-center" : "text-left"} ${active ? "text-foreground" : ""}`}
      >
        {label}
        {active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
      </th>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading quotes…
        </div>
      )}
      {error && <p className="text-sm text-rose-500">{error}</p>}
      <div className="overflow-x-auto border border-border">
        <table className="min-w-max w-full text-sm">
          <thead className="bg-muted/40 border-b border-border">
            <tr>
              <th
                onClick={() => toggleSort("symbol")}
                className={`sticky left-0 z-10 bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-foreground text-left ${sortKey === "symbol" ? "text-foreground" : ""}`}
              >
                Symbol
                {sortKey === "symbol" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
              </th>
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">
                Name
              </th>
              <ColHd label="Price" col="price" />
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">
                Change
              </th>
              <ColHd label="Change %" col="changePercentage" />
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">
                Open
              </th>
              <th className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap text-left">
                Prev Close
              </th>
              <ColHd label="Day Low" col="dayLow" />
              <ColHd label="Day High" col="dayHigh" />
              <ColHd label="52w Low" col="yearLow" />
              <ColHd label="52w High" col="yearHigh" />
              <ColHd label="Avg50" col="priceAvg50" />
              <ColHd label="Avg200" col="priceAvg200" />
              <ColHd label="Volume" col="volume" />
              <ColHd label="Mkt Cap" col="marketCap" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sortedSymbols.map((sym) => {
              const q = quotes[sym];
              const isLoading = loading && q === undefined;
              const chgColor = q
                ? q.changePercentage >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-rose-500"
                : "";
              const isSelected = sym === selectedTicker;
              const isDismissed = dismissedSymbols.has(sym);
              const isHighlighted = highlightedSymbols.has(sym);
              const status = getStatus(sym);
              const statusStripe: Record<string, string> = {
                dismissed: "border-l-rose-400",
                watchlist: "border-l-amber-400",
                pipeline: "border-l-sky-400",
                active: "border-l-emerald-400",
              };
              const stripe =
                isDismissed || isHighlighted || isSelected
                  ? (statusStripe[status] ?? "border-l-transparent")
                  : "";
              return (
                <tr
                  key={sym}
                  onClick={() => onSelect(sym)}
                  onDoubleClick={() => onOpenWorkflowEditor(sym)}
                  className={`cursor-pointer transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${isHighlighted ? "bg-amber-500/10" : ""} ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
                >
                  <td
                    className={`sticky left-0 z-10 px-3 py-2 font-mono font-semibold whitespace-nowrap ${isSelected ? "bg-foreground/10" : isHighlighted ? "bg-amber-500/10" : "bg-background"}`}
                  >
                    {sym}
                  </td>
                  <td
                    className="px-3 py-2 text-xs text-muted-foreground max-w-[160px] truncate whitespace-nowrap"
                    title={q?.name}
                  >
                    {isLoading ? "…" : (q?.name ?? "—")}
                  </td>
                  <td className="px-3 py-2 tabular-nums font-medium">
                    {q ? `$${q.price.toFixed(2)}` : isLoading ? "…" : "—"}
                  </td>
                  <td className={`px-3 py-2 tabular-nums ${chgColor}`}>
                    {q ? (q.change >= 0 ? "+" : "") + q.change.toFixed(2) : "—"}
                  </td>
                  <td
                    className={`px-3 py-2 tabular-nums font-medium ${chgColor}`}
                  >
                    {q
                      ? (q.changePercentage >= 0 ? "+" : "") +
                        q.changePercentage.toFixed(2) +
                        "%"
                      : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {q ? `$${q.open.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {q ? `$${q.previousClose.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {q ? `$${q.dayLow.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {q ? `$${q.dayHigh.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">
                    {q ? `$${q.yearLow.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">
                    {q ? `$${q.yearHigh.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">
                    {q ? `$${q.priceAvg50.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-muted-foreground">
                    {q ? `$${q.priceAvg200.toFixed(2)}` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {q ? fmtVol(q.volume) : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {q ? fmtCap(q.marketCap) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}