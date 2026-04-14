"use client";

import { useMemo, useState } from "react";
import { CLUSTERS, DIMENSION_MAP, type Cluster } from "./dimensions";
import { Search, TrendingDown, TrendingUp } from "lucide-react";

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

function formatVectorDate(dateString: string): string {
  const parsed = new Date(dateString);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "UTC",
  }).format(parsed);
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

function DimensionRow({
  label,
  description,
  higherIs,
  score,
  rawValue,
}: {
  label: string;
  description: string;
  higherIs: "better" | "worse";
  score: number | null;
  rawValue: number | null;
}) {
  return (
    <div className="border-t border-border py-2 first:border-t-0">
      <div className="mb-1 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium text-foreground">{label}</span>
            {higherIs === "better" ? (
              <TrendingUp size={10} className="shrink-0 text-emerald-500" />
            ) : (
              <TrendingDown size={10} className="shrink-0 text-rose-500" />
            )}
          </div>
          <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{description}</p>
          {rawValue != null ? (
            <span className="font-mono text-[10px] text-muted-foreground/60">
              raw: {rawValue.toFixed(4)}
            </span>
          ) : null}
        </div>
      </div>
      <ScoreBar score={score} higherIs={higherIs} />
    </div>
  );
}

function ClusterSection({
  cluster,
  dimensions,
  raw,
}: {
  cluster: Cluster;
  dimensions: Record<string, number | null>;
  raw: Record<string, number | null>;
}) {
  return (
    <section className="pt-2">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">{cluster.label}</p>
        <ClusterSummaryScore cluster={cluster} dimensions={dimensions} />
      </div>
      <div>
        {cluster.dimensions.map((dim) => (
          <DimensionRow
            key={dim.key}
            label={dim.label}
            description={dim.description}
            higherIs={dim.higher_is}
            score={dimensions[dim.key] ?? null}
            rawValue={raw[dim.key] ?? null}
          />
        ))}
      </div>
    </section>
  );
}

function TickerProfile({ row }: { row: TickerRow }) {
  return (
    <section className="space-y-3 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-bold text-foreground">{row.ticker}</span>
            <span className="text-xs text-muted-foreground">{row.metadata.name}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {row.metadata.sector ? (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {row.metadata.sector}
              </span>
            ) : null}
            {row.metadata.industry ? (
              <span className="truncate text-[10px] text-muted-foreground">{row.metadata.industry}</span>
            ) : null}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-xs font-medium">{formatMarketCap(row.metadata.market_cap)}</p>
          <p className="mt-0.5 text-[10px] text-muted-foreground">{formatVectorDate(row.vector_date)}</p>
        </div>
      </div>

      {CLUSTERS.map((cluster) => (
        <ClusterSection
          key={cluster.id}
          cluster={cluster}
          dimensions={row.dimensions}
          raw={row.raw}
        />
      ))}
    </section>
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
      <div className="rounded-xl border border-border bg-card p-6 text-center text-muted-foreground">
        <p className="text-sm">No vectors found for this selection.</p>
        <p className="mt-1 text-xs">
          Run{" "}
          <code className="rounded bg-muted px-1 font-mono">
            python -m news_impact.build_vectors_cli --tickers AAPL MSFT
          </code>{" "}
          to populate.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {count > 1 ? (
        <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
          <label className="relative block">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <span className="sr-only">Search vectors</span>
            <input
              type="text"
              placeholder="Search ticker, company, sector…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-background pl-8 pr-3 text-sm outline-none ring-ring/50 transition focus-visible:ring-2"
            />
          </label>
          <label className="sr-only" htmlFor="vectors-sector-filter">
            Filter by sector
          </label>
          <select
            id="vectors-sector-filter"
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm outline-none ring-ring/50 transition focus-visible:ring-2"
          >
            {sectors.map((s) => (
              <option key={s} value={s}>
                {s === "all" ? "All sectors" : s}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground/80">Guide</span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" /> favorable
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm bg-amber-400" /> neutral
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2.5 w-2.5 rounded-sm bg-rose-500" /> risk
        </span>
        <span className="inline-flex items-center gap-1">
          <TrendingUp size={10} className="text-emerald-500" /> high = better
        </span>
        <span className="inline-flex items-center gap-1">
          <TrendingDown size={10} className="text-rose-500" /> high = worse
        </span>
      </div>

      <div className="grid gap-3">
        {filtered.map((row) => (
          <TickerProfile key={row.ticker} row={row} />
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          No vectors match your current filter.
        </div>
      ) : null}
    </div>
  );
}
