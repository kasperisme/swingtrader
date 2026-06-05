"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, Flame } from "lucide-react";
import type { SortMode, TrendItem, TrendingBoard } from "@/lib/trends-types";

// ── Sparkline ────────────────────────────────────────────────────────────────
// Dependency-free inline SVG so we can render one per row cheaply.
function Sparkline({
  values,
  className = "",
  width = 56,
  height = 18,
}: {
  values: number[];
  className?: string;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return <span className="inline-block" style={{ width, height }} />;
  const max = Math.max(...values, 1);
  const stepX = width / (values.length - 1);
  const points = values
    .map((v, i) => `${(i * stepX).toFixed(1)},${(height - (v / max) * height).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      aria-hidden
      preserveAspectRatio="none"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function DeltaBadge({ item }: { item: TrendItem }) {
  if (item.isNew) {
    return (
      <span className="rounded-sm bg-amber-500/15 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider text-amber-400">
        New
      </span>
    );
  }
  if (item.deltaPct == null) return null;
  const pct = Math.round(item.deltaPct * 100);
  if (pct === 0) {
    return <span className="font-mono text-[10px] tabular-nums text-muted-foreground">—</span>;
  }
  const up = pct > 0;
  return (
    <span
      className={`font-mono text-[10px] font-semibold tabular-nums ${
        up ? "text-emerald-500" : "text-rose-500"
      }`}
    >
      {up ? "▲" : "▼"}
      {Math.abs(pct)}%
    </span>
  );
}

function SentimentDot({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/30" title="No sentiment yet" />;
  }
  const cls = value > 0.03 ? "bg-emerald-500" : value < -0.03 ? "bg-rose-500" : "bg-muted-foreground/40";
  return (
    <span
      className={`h-1.5 w-1.5 rounded-full ${cls}`}
      title={`Avg sentiment ${value >= 0 ? "+" : ""}${value.toFixed(2)}`}
    />
  );
}

function TrendRow({ item, idx }: { item: TrendItem; idx: number }) {
  const unit = item.kind === "ticker" ? "mentions" : "stories";
  const sparkColor =
    item.deltaPct != null && item.deltaPct < 0 ? "text-rose-500/70" : "text-amber-500/70";
  return (
    <li>
      <Link
        href={`/articles?tag=${encodeURIComponent(item.key)}`}
        className="group flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted/40"
      >
        <span className="w-4 shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground/60">
          {idx + 1}
        </span>
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {item.kind === "ticker" ? <SentimentDot value={item.avgSentiment} /> : null}
          <span
            className={`truncate font-semibold tracking-tight text-foreground group-hover:text-amber-400 ${
              item.kind === "ticker" ? "font-mono text-sm" : "text-sm"
            }`}
          >
            {item.label}
          </span>
        </div>
        <Sparkline values={item.spark} className={`shrink-0 ${sparkColor}`} />
        <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
          {item.current.toLocaleString("en-US")}
          <span className="ml-1 hidden text-[9px] uppercase tracking-wide text-muted-foreground/50 sm:inline">
            {unit}
          </span>
        </span>
        <span className="w-12 shrink-0 text-right">
          <DeltaBadge item={item} />
        </span>
      </Link>
    </li>
  );
}

function Column({
  title,
  items,
  visible,
  canExpand,
  expanded,
  total,
  onToggle,
}: {
  title: string;
  items: TrendItem[];
  visible: number;
  canExpand: boolean;
  expanded: boolean;
  total: number;
  onToggle: () => void;
}) {
  return (
    <div className="min-w-0">
      <h3 className="mb-3 text-sm font-semibold tracking-tight text-foreground/90">{title}</h3>
      {items.length === 0 ? (
        <p className="px-2 py-6 text-xs text-muted-foreground/70">Nothing here for this filter yet.</p>
      ) : (
        <ul className="-mx-2">
          {items.slice(0, visible).map((it, idx) => (
            <TrendRow key={it.key} item={it} idx={idx} />
          ))}
        </ul>
      )}
      {/* Per-column expander — mobile only. On desktop a single shared button
          (below the grid) controls both columns together. */}
      {canExpand ? (
        <div className="mt-3 flex justify-center border-t border-border/50 pt-3 md:hidden">
          <ExpandButton expanded={expanded} total={total} onToggle={onToggle} />
        </div>
      ) : null}
    </div>
  );
}

function ExpandButton({
  expanded,
  total,
  onToggle,
}: {
  expanded: boolean;
  total: number;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      className="group inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-amber-400"
    >
      {expanded ? "Show less" : `Show top ${total}`}
      <ChevronDown
        size={12}
        className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
      />
    </button>
  );
}

const FILTERS: { mode: SortMode; label: string }[] = [
  { mode: "mentions", label: "Most mentions" },
  { mode: "growth", label: "Most growth" },
  { mode: "new", label: "New" },
];

function FilterTabs({
  active,
  onChange,
}: {
  active: SortMode;
  onChange: (m: SortMode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Trending filter"
      className="inline-flex items-center gap-0.5 rounded-lg border border-border/60 bg-muted/30 p-0.5"
    >
      {FILTERS.map((f) => {
        const selected = f.mode === active;
        return (
          <button
            key={f.mode}
            role="tab"
            type="button"
            aria-selected={selected}
            onClick={() => onChange(f.mode)}
            className={`rounded-md px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] transition-colors ${
              selected
                ? "bg-background text-amber-400 shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {f.label}
          </button>
        );
      })}
    </div>
  );
}

export function TrendingScoreboardView({
  board,
  windowDays = 7,
  collapsed = 6,
}: {
  board: TrendingBoard;
  windowDays?: number;
  collapsed?: number;
}) {
  const [mode, setMode] = useState<SortMode>("mentions");
  // Independent state per column so they expand separately on mobile. On
  // desktop a single shared button drives both together.
  const [tickersExpanded, setTickersExpanded] = useState(false);
  const [tagsExpanded, setTagsExpanded] = useState(false);

  const tickers = board.tickers[mode];
  const tags = board.tags[mode];
  const maxLen = Math.max(tickers.length, tags.length);

  const tickersCanExpand = tickers.length > collapsed;
  const tagsCanExpand = tags.length > collapsed;
  const tickersVisible = tickersExpanded ? tickers.length : collapsed;
  const tagsVisible = tagsExpanded ? tags.length : collapsed;

  // Desktop shared button: collapsed unless both columns are expanded; one
  // click expands (or collapses) both at once.
  const canExpand = tickersCanExpand || tagsCanExpand;
  const bothExpanded = tickersExpanded && tagsExpanded;
  const toggleBoth = () => {
    const next = !bothExpanded;
    setTickersExpanded(next);
    setTagsExpanded(next);
  };

  return (
    <section
      aria-labelledby="trending-now-heading"
      className="rounded-2xl border border-border/60 bg-card/30 p-5 sm:p-6"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="inline-flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.2em] text-amber-500/80">
          <Flame size={12} className="text-amber-500/80" />
          Trending now
        </p>
        <FilterTabs active={mode} onChange={setMode} />
      </div>
      <h2 id="trending-now-heading" className="sr-only">
        Trending tickers and tags
      </h2>
      <p className="mb-5 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {mode === "new" ? `New this ${windowDays}d` : `Last ${windowDays}d · vs prior ${windowDays}d`}
      </p>

      <div className="grid gap-8 md:grid-cols-2">
        <Column
          title="Tickers"
          items={tickers}
          visible={tickersVisible}
          canExpand={tickersCanExpand}
          expanded={tickersExpanded}
          total={tickers.length}
          onToggle={() => setTickersExpanded((v) => !v)}
        />
        <Column
          title="Themes"
          items={tags}
          visible={tagsVisible}
          canExpand={tagsCanExpand}
          expanded={tagsExpanded}
          total={tags.length}
          onToggle={() => setTagsExpanded((v) => !v)}
        />
      </div>

      {/* Shared expander — desktop only. Mobile uses the per-column buttons. */}
      {canExpand ? (
        <div className="mt-5 hidden justify-center border-t border-border/50 pt-4 md:flex">
          <ExpandButton expanded={bothExpanded} total={maxLen} onToggle={toggleBoth} />
        </div>
      ) : null}
    </section>
  );
}
