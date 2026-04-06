"use client";

import { useState, useMemo } from "react";
import { CLUSTERS, DIMENSION_MAP, type Cluster } from "./dimensions";
import { ChevronDown, ChevronRight, Search, TrendingUp, TrendingDown, Minus } from "lucide-react";

export interface TickerRow {
  ticker: string;
  vector_date: string;
  dimensions: Record<string, number | null>;
  raw: Record<string, number | null>;
  metadata: {
    name: string;
    sector: string;
    industry: string;
    market_cap: number | null;
  };
  fetched_at: string;
}

function formatMarketCap(v: number | null): string {
  if (v == null) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(0)}`;
}

function ScoreBar({ score, higherIs }: { score: number | null; higherIs: "better" | "worse" }) {
  if (score == null) {
    return (
      <div className="flex items-center gap-2 min-w-0">
        <div className="flex-1 h-1.5 bg-muted rounded-full" />
        <span className="text-xs text-muted-foreground w-7 text-right shrink-0">—</span>
      </div>
    );
  }

  const pct = Math.round(score * 100);
  let barColor: string;
  if (higherIs === "better") {
    if (score >= 0.66) barColor = "bg-emerald-500";
    else if (score >= 0.33) barColor = "bg-amber-400";
    else barColor = "bg-rose-500";
  } else {
    if (score >= 0.66) barColor = "bg-rose-500";
    else if (score >= 0.33) barColor = "bg-amber-400";
    else barColor = "bg-emerald-500";
  }

  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground w-7 text-right shrink-0">
        {(score).toFixed(2)}
      </span>
    </div>
  );
}

function ClusterSummaryScore({
  cluster,
  dimensions,
}: {
  cluster: Cluster;
  dimensions: Record<string, number | null>;
}) {
  const scores = cluster.dimensions
    .map((d) => dimensions[d.key])
    .filter((v): v is number => v != null);
  if (scores.length === 0) return <span className="text-muted-foreground text-xs">—</span>;
  const avg = scores.reduce((a, b) => a + b, 0) / scores.length;

  // For "worse" clusters, invert for display color
  const allWorse = cluster.dimensions.every((d) => d.higher_is === "worse");
  const effective = allWorse ? 1 - avg : avg;

  const color =
    effective >= 0.66
      ? "text-emerald-500"
      : effective >= 0.33
        ? "text-amber-400"
        : "text-rose-500";

  return <span className={`text-xs font-mono font-medium ${color}`}>{avg.toFixed(2)}</span>;
}

function ClusterPanel({
  cluster,
  dimensions,
  raw,
}: {
  cluster: Cluster;
  dimensions: Record<string, number | null>;
  raw: Record<string, number | null>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-muted/40 hover:bg-muted/70 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown size={14} className="text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight size={14} className="text-muted-foreground shrink-0" />
          )}
          <span className="text-xs font-semibold uppercase tracking-wide text-foreground/80">
            {cluster.label}
          </span>
        </div>
        <ClusterSummaryScore cluster={cluster} dimensions={dimensions} />
      </button>

      {open && (
        <div className="divide-y">
          {cluster.dimensions.map((dim) => {
            const score = dimensions[dim.key] ?? null;
            const rawVal = raw[dim.key] ?? null;
            return (
              <div key={dim.key} className="px-3 py-2">
                <div className="flex items-start justify-between gap-3 mb-1">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-foreground">{dim.label}</span>
                      {dim.higher_is === "better" ? (
                        <TrendingUp size={10} className="text-emerald-500 shrink-0" />
                      ) : (
                        <TrendingDown size={10} className="text-rose-500 shrink-0" />
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground leading-snug mt-0.5">
                      {dim.description}
                    </p>
                    {rawVal != null && (
                      <span className="text-[10px] text-muted-foreground/60 font-mono">
                        raw: {rawVal.toFixed(4)}
                      </span>
                    )}
                  </div>
                </div>
                <ScoreBar score={score} higherIs={dim.higher_is} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function TickerCard({ row }: { row: TickerRow }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border rounded-xl overflow-hidden shadow-sm">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full text-left px-4 py-3 hover:bg-muted/30 transition-colors"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-bold text-sm text-foreground font-mono">{row.ticker}</span>
              {expanded ? (
                <ChevronDown size={14} className="text-muted-foreground" />
              ) : (
                <ChevronRight size={14} className="text-muted-foreground" />
              )}
            </div>
            <p className="text-xs text-muted-foreground truncate mt-0.5">{row.metadata.name}</p>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {row.metadata.sector && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                  {row.metadata.sector}
                </span>
              )}
              {row.metadata.industry && (
                <span className="text-[10px] text-muted-foreground truncate">
                  {row.metadata.industry}
                </span>
              )}
            </div>
          </div>
          <div className="text-right shrink-0">
            <p className="text-xs font-mono font-medium">{formatMarketCap(row.metadata.market_cap)}</p>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {new Date(row.vector_date).toLocaleDateString()}
            </p>
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t bg-background">
          <div className="grid gap-2">
            {CLUSTERS.map((cluster) => (
              <ClusterPanel
                key={cluster.id}
                cluster={cluster}
                dimensions={row.dimensions}
                raw={row.raw}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function VectorsUI({ tickers, count }: { tickers: TickerRow[]; count: number }) {
  const [search, setSearch] = useState("");
  const [sectorFilter, setSectorFilter] = useState("all");

  const sectors = useMemo(() => {
    const s = new Set(tickers.map((t) => t.metadata.sector).filter(Boolean));
    return ["all", ...Array.from(s).sort()];
  }, [tickers]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tickers.filter((t) => {
      const matchSearch =
        !q ||
        t.ticker.toLowerCase().includes(q) ||
        t.metadata.name?.toLowerCase().includes(q) ||
        t.metadata.sector?.toLowerCase().includes(q) ||
        t.metadata.industry?.toLowerCase().includes(q);
      const matchSector = sectorFilter === "all" || t.metadata.sector === sectorFilter;
      return matchSearch && matchSector;
    });
  }, [tickers, search, sectorFilter]);

  if (count === 0) {
    return (
      <div className="text-center py-16 text-muted-foreground">
        <p className="text-sm">No company vectors found in the database.</p>
        <p className="text-xs mt-1">
          Run{" "}
          <code className="font-mono bg-muted px-1 rounded">
            python -m news_impact.build_vectors_cli --tickers AAPL MSFT
          </code>{" "}
          to populate.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="text"
            placeholder="Search ticker, name, sector…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <select
          value={sectorFilter}
          onChange={(e) => setSectorFilter(e.target.value)}
          className="text-sm border rounded-lg px-3 py-1.5 bg-background focus:outline-none focus:ring-2 focus:ring-ring"
        >
          {sectors.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All sectors" : s}
            </option>
          ))}
        </select>
      </div>

      <p className="text-xs text-muted-foreground">
        {filtered.length} of {count} companies — scores are rank-normalised 0–1 within the
        stored universe
      </p>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[11px] text-muted-foreground flex-wrap">
        <span className="font-medium text-foreground/70">Score guide:</span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-emerald-500" /> favorable
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-amber-400" /> neutral
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-rose-500" /> risk
        </span>
        <span className="flex items-center gap-1">
          <TrendingUp size={10} className="text-emerald-500" /> higher = better
        </span>
        <span className="flex items-center gap-1">
          <TrendingDown size={10} className="text-rose-500" /> higher = worse
        </span>
      </div>

      {/* Ticker list */}
      <div className="grid gap-3">
        {filtered.map((row) => (
          <TickerCard key={row.ticker} row={row} />
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="text-center py-8 text-muted-foreground text-sm">No results match your filter.</div>
      )}
    </div>
  );
}
