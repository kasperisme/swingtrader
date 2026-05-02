"use client";

import React, { useState, useMemo, useEffect } from "react";
import { ChevronUp, ChevronDown, Loader2 } from "lucide-react";
import {
  screeningsGetTickerSentimentHeadRows,
  type ScreeningTickerSentimentHeadRow,
} from "@/app/actions/screenings";

type SentimentSort = {
  key: "symbol" | "s7d" | "s30d" | "s90d";
  dir: "asc" | "desc";
};

function computeTickerSentimentWindow(
  rows: ScreeningTickerSentimentHeadRow[],
  ticker: string,
  cutoffDate: string,
): number {
  const t = ticker.toUpperCase();
  let total = 0;
  for (const row of rows) {
    if (row.ticker.toUpperCase() !== t) continue;
    const day = row.article_ts.slice(0, 10);
    if (day < cutoffDate) continue;
    if (Number.isFinite(row.sentiment_score)) total += row.sentiment_score;
  }
  return total;
}

function SentimentScoreCell({
  value,
  maxAbs,
}: {
  value: number;
  maxAbs: number;
}) {
  const pct = maxAbs > 0 ? Math.abs(value) / maxAbs : 0;
  const pos = value >= 0;
  const negligible = Math.abs(value) < 0.01;
  return (
    <div className="flex items-center gap-2 min-w-[130px]">
      <div className="relative flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
        <div
          className={`absolute top-0 h-full rounded-full ${pos ? "bg-emerald-500 left-1/2" : "bg-rose-400 right-1/2"}`}
          style={{ width: `${pct * 50}%` }}
        />
      </div>
      <span
        className={`text-xs font-mono w-14 text-right tabular-nums ${negligible ? "text-muted-foreground" : pos ? "text-emerald-500" : "text-rose-400"}`}
      >
        {value >= 0 ? "+" : ""}
        {value.toFixed(2)}
      </span>
    </div>
  );
}

function SentimentTh({
  col,
  sort,
  onSort,
  children,
  right,
}: {
  col: SentimentSort["key"];
  sort: SentimentSort;
  onSort: (col: SentimentSort["key"]) => void;
  children: React.ReactNode;
  right?: boolean;
}) {
  return (
    <th
      className={`px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wide cursor-pointer select-none hover:text-foreground whitespace-nowrap ${right ? "text-right" : "text-left"}`}
      onClick={() => onSort(col)}
    >
      {children}
      {sort.key === col &&
        (sort.dir === "asc" ? (
          <ChevronUp className="w-3 h-3 inline ml-0.5" />
        ) : (
          <ChevronDown className="w-3 h-3 inline ml-0.5" />
        ))}
    </th>
  );
}

export function SentimentView({
  symbols,
  selectedTicker,
  onSelect,
  getTickerMeta,
  dismissedSymbols,
  highlightedSymbols,
  getStatus,
}: {
  symbols: string[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  getTickerMeta: (ticker: string) => {
    sector: string;
    industry: string;
    subSector: string;
  };
  dismissedSymbols: Set<string>;
  highlightedSymbols: Set<string>;
  getStatus: (ticker: string) => string;
}) {
  const [sentimentHeadRows, setSentimentHeadRows] = useState<
    ScreeningTickerSentimentHeadRow[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SentimentSort>({ key: "s7d", dir: "desc" });

  useEffect(() => {
    if (symbols.length === 0) {
      setSentimentHeadRows([]);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    screeningsGetTickerSentimentHeadRows(symbols)
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          setError("Failed to load ticker sentiment");
          setSentimentHeadRows([]);
          return;
        }
        setSentimentHeadRows(res.data);
      })
      .catch(() => {
        if (!cancelled) {
          setError("Failed to load ticker sentiment");
          setSentimentHeadRows([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbols]);

  const cutoffs = useMemo(() => {
    const now = new Date();
    function daysAgo(n: number) {
      const d = new Date(now);
      d.setDate(d.getDate() - n);
      return d.toISOString().slice(0, 10);
    }
    return { c7: daysAgo(7), c30: daysAgo(30), c90: daysAgo(90) };
  }, []);

  const rows = useMemo(() => {
    return symbols.map((symbol) => {
      const { sector, industry } = getTickerMeta(symbol);
      return {
        symbol,
        sector,
        industry,
        s7d: computeTickerSentimentWindow(
          sentimentHeadRows,
          symbol,
          cutoffs.c7,
        ),
        s30d: computeTickerSentimentWindow(
          sentimentHeadRows,
          symbol,
          cutoffs.c30,
        ),
        s90d: computeTickerSentimentWindow(
          sentimentHeadRows,
          symbol,
          cutoffs.c90,
        ),
      };
    });
  }, [symbols, sentimentHeadRows, cutoffs, getTickerMeta]);

  const maxAbs = useMemo(
    () =>
      Math.max(
        ...rows.flatMap((r) => [
          Math.abs(r.s7d),
          Math.abs(r.s30d),
          Math.abs(r.s90d),
        ]),
        0.01,
      ),
    [rows],
  );

  const sorted = useMemo(() => {
    const { key, dir } = sort;
    return [...rows].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (typeof av === "string" && typeof bv === "string") {
        return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return dir === "asc"
        ? (av as number) - (bv as number)
        : (bv as number) - (av as number);
    });
  }, [rows, sort]);

  function toggleSort(key: SentimentSort["key"]) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "symbol" ? "asc" : "desc" },
    );
  }

  if (symbols.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No stocks to show.
      </p>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading sentiment data…
      </div>
    );
  }
  if (error) return <p className="text-sm text-rose-500 py-4">{error}</p>;

  return (
    <div className="overflow-x-auto border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 border-b border-border">
          <tr>
            <SentimentTh col="symbol" sort={sort} onSort={toggleSort}>
              Symbol
            </SentimentTh>
            <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap">
              Sector
            </th>
            <SentimentTh col="s7d" sort={sort} onSort={toggleSort} right>
              7-day
            </SentimentTh>
            <SentimentTh col="s30d" sort={sort} onSort={toggleSort} right>
              30-day
            </SentimentTh>
            <SentimentTh col="s90d" sort={sort} onSort={toggleSort} right>
              90-day
            </SentimentTh>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sorted.map((row) => {
            const isSelected = selectedTicker === row.symbol;
            const isDismissed = dismissedSymbols.has(row.symbol);
            const isHighlighted = highlightedSymbols.has(row.symbol);
            const status = getStatus(row.symbol);
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
                key={row.symbol}
                onClick={() => onSelect(row.symbol)}
                className={`cursor-pointer transition-colors border-l-[3px] ${stripe || "border-l-transparent"} ${isDismissed ? "opacity-40" : ""} ${isHighlighted ? "bg-amber-500/10" : ""} ${isSelected ? "bg-foreground/10 ring-1 ring-inset ring-foreground/20" : "hover:bg-muted/30"}`}
              >
                <td className="px-3 py-2 font-mono font-semibold whitespace-nowrap">
                  {row.symbol}
                </td>
                <td
                  className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap max-w-[140px] truncate"
                  title={row.sector || undefined}
                >
                  {row.sector || "—"}
                </td>
                <td className="px-3 py-2">
                  <SentimentScoreCell value={row.s7d} maxAbs={maxAbs} />
                </td>
                <td className="px-3 py-2">
                  <SentimentScoreCell value={row.s30d} maxAbs={maxAbs} />
                </td>
                <td className="px-3 py-2">
                  <SentimentScoreCell value={row.s90d} maxAbs={maxAbs} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}