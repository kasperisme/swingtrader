"use client";

/**
 * Tabular view of the relationship neighbourhood — the secondary read of exactly
 * the data the force graph draws.
 *
 * The graph answers "what is the shape of this neighbourhood". It is bad at
 * "who are this company's competitors, in order", which is the question this
 * view exists for. So the pivot is FOCUS-RELATIVE: rows are the focused
 * company's counterparties and columns are relationship types, so reading down
 * the `competitor` column gives you that company's competitors by name. (An
 * earlier cut pivoted link *counts* per company, which told you AAPL had 22
 * competitor links without ever naming one of them.)
 *
 * It shares the explorer's state — same seed, same rel-type legend, same tier
 * depth, same selection — rather than fetching its own, so toggling between
 * graph and table never changes what you are looking at, only how.
 */

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, CornerDownRight, X } from "lucide-react";

import type { RelationshipEdge } from "@/app/actions/relationships";

/** One counterparty of the focused company. */
type PeerRow = {
  peer: string;
  /** The focus↔peer link for each relationship type they share. */
  byType: Record<string, RelationshipEdge>;
  /** Strongest link with the focus, across types. */
  strongest: number;
  /** Article mentions across their shared links. */
  mentions: number;
  /** The peer's own total links anywhere in the loaded graph. */
  degree: number;
  lastSeen: string | null;
};

type PeerSortKey = "peer" | "strongest" | "mentions" | "degree" | "last" | `rel:${string}`;
type EdgeSortKey = "from" | "type" | "to" | "strength" | "mentions" | "articles" | "last";
type SortDir = "asc" | "desc";

/**
 * Derive a translucent fill from a rel-type colour. The palette is written as
 * `hsl(var(--chart-3))`, so the alpha slots in before the closing paren. Guarded
 * because anything not in that exact shape (a hex, say) can't take an alpha this
 * way and should just render untinted.
 */
function relTint(color: string | undefined, alpha: number): string | undefined {
  if (!color) return undefined;
  if (!color.startsWith("hsl(var(") || !color.endsWith(")")) return undefined;
  return `${color.slice(0, -1)} / ${alpha})`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    year: "2-digit",
    month: "short",
    day: "2-digit",
  }).format(d);
}

function newer(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
}

/** Sortable column header. Carries `aria-sort` so the order is announced. */
function SortHeader({
  label,
  active,
  dir,
  onClick,
  align = "left",
  title,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  align?: "left" | "right";
  title?: string;
}) {
  return (
    <th
      scope="col"
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
      className="px-2 py-1.5 font-medium"
    >
      <button
        type="button"
        onClick={onClick}
        title={title}
        className={`inline-flex min-h-9 w-full cursor-pointer items-center gap-1 rounded px-1 text-[11px] uppercase tracking-wide transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
          align === "right" ? "justify-end" : "justify-start"
        } ${active ? "text-foreground" : "text-muted-foreground"}`}
      >
        {label}
        {active ? (
          dir === "asc" ? (
            <ArrowUp className="h-3 w-3 shrink-0" aria-hidden />
          ) : (
            <ArrowDown className="h-3 w-3 shrink-0" aria-hidden />
          )
        ) : null}
      </button>
    </th>
  );
}

/**
 * A relationship-type column header. Clicking it isolates that relationship —
 * "show me this company's competitors" is the actual question, and answering it
 * by sorting alone leaves the 18 competitors interleaved with 52 companies that
 * aren't. Sorting still happens (strongest link first); the filter is the part
 * that makes the column readable.
 */
function RelHeader({
  type,
  count,
  color,
  isolated,
  sorted,
  dir,
  focusTicker,
  onClick,
}: {
  type: string;
  count: number;
  color: string | undefined;
  isolated: boolean;
  sorted: boolean;
  dir: SortDir;
  focusTicker: string;
  onClick: () => void;
}) {
  return (
    <th
      scope="col"
      aria-sort={sorted ? (dir === "asc" ? "ascending" : "descending") : "none"}
      className="px-2 py-1.5 font-medium"
    >
      <button
        type="button"
        onClick={onClick}
        aria-pressed={isolated}
        title={
          isolated
            ? `Show all of ${focusTicker}'s relationships again`
            : `Show only ${focusTicker}'s ${count} ${type} relationships`
        }
        className={`inline-flex min-h-9 w-full cursor-pointer items-center justify-end gap-1 rounded px-1.5 text-[11px] uppercase tracking-wide transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
          isolated
            ? "font-semibold text-foreground ring-1 ring-foreground/40"
            : "text-muted-foreground hover:text-foreground"
        }`}
        style={isolated ? { backgroundColor: relTint(color, 0.2) } : undefined}
      >
        <span
          className="h-2 w-2 shrink-0 rounded-sm"
          style={{ backgroundColor: color }}
          aria-hidden
        />
        {type} ({count})
        {sorted ? (
          dir === "asc" ? (
            <ArrowUp className="h-3 w-3 shrink-0" aria-hidden />
          ) : (
            <ArrowDown className="h-3 w-3 shrink-0" aria-hidden />
          )
        ) : null}
      </button>
    </th>
  );
}

export function RelationshipTableView({
  edges,
  relTypes,
  relColors,
  seedTicker,
  focusTicker,
  selectedEdge,
  onSelectNode,
  onSelectEdge,
}: {
  /** Already filtered by the rel-type legend — the same set the graph draws. */
  edges: RelationshipEdge[];
  /** Rel types currently enabled in the legend, in display order. */
  relTypes: string[];
  relColors: Record<string, string>;
  seedTicker: string;
  /** The company the pivot is rooted on — the selected node, or the seed. */
  focusTicker: string;
  selectedEdge: { from_ticker: string; to_ticker: string; rel_type?: string } | null;
  onSelectNode: (ticker: string) => void;
  /**
   * `peer` is the company the click was about — the counterparty, not the
   * pivot's focus — so the details panel can load its profile.
   */
  onSelectEdge: (
    edge: { from_ticker: string; to_ticker: string; rel_type: string },
    peer?: string,
  ) => void;
}) {
  const [peerSort, setPeerSort] = useState<PeerSortKey>("strongest");
  const [peerDir, setPeerDir] = useState<SortDir>("desc");
  /** When set, only companies having this relationship with the focus are shown. */
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [edgeSort, setEdgeSort] = useState<EdgeSortKey>("strength");
  const [edgeDir, setEdgeDir] = useState<SortDir>("desc");
  const [edgeScope, setEdgeScope] = useState<"focus" | "all">("focus");

  /** Every company's total link count, used for the drill-down hint column. */
  const degreeByTicker = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of edges) {
      m.set(e.from_ticker, (m.get(e.from_ticker) ?? 0) + 1);
      m.set(e.to_ticker, (m.get(e.to_ticker) ?? 0) + 1);
    }
    return m;
  }, [edges]);

  const peerRows = useMemo<PeerRow[]>(() => {
    if (!focusTicker) return [];
    const byPeer = new Map<string, PeerRow>();
    for (const e of edges) {
      const isFrom = e.from_ticker === focusTicker;
      const isTo = e.to_ticker === focusTicker;
      if (!isFrom && !isTo) continue;
      const peer = isFrom ? e.to_ticker : e.from_ticker;
      // A self-edge would render as a row about the focus itself.
      if (peer === focusTicker) continue;
      let row = byPeer.get(peer);
      if (!row) {
        row = {
          peer,
          byType: {},
          strongest: 0,
          mentions: 0,
          degree: degreeByTicker.get(peer) ?? 0,
          lastSeen: null,
        };
        byPeer.set(peer, row);
      }
      // Keep the strongest link when the same pair shares a type more than once.
      const existing = row.byType[e.rel_type];
      if (!existing || e.strength_avg > existing.strength_avg) {
        row.byType[e.rel_type] = e;
      }
      if (e.strength_avg > row.strongest) row.strongest = e.strength_avg;
      row.mentions += e.mention_count ?? 0;
      row.lastSeen = newer(row.lastSeen, e.last_seen_at);
    }
    return Array.from(byPeer.values());
  }, [edges, focusTicker, degreeByTicker]);

  // Re-rooting on another company (or toggling the legend) can leave a filter
  // pointing at a relationship the new focus doesn't have. Drop it rather than
  // rendering an empty table the user has no obvious way out of.
  const effectiveTypeFilter = useMemo(
    () => (typeFilter && peerRows.some((r) => r.byType[typeFilter]) ? typeFilter : null),
    [typeFilter, peerRows],
  );

  const sortedPeers = useMemo(() => {
    const mult = peerDir === "asc" ? 1 : -1;
    const base = effectiveTypeFilter
      ? peerRows.filter((r) => r.byType[effectiveTypeFilter])
      : peerRows;
    return [...base].sort((a, b) => {
      let cmp = 0;
      if (peerSort === "peer") cmp = a.peer.localeCompare(b.peer);
      else if (peerSort === "strongest") cmp = a.strongest - b.strongest;
      else if (peerSort === "mentions") cmp = a.mentions - b.mentions;
      else if (peerSort === "degree") cmp = a.degree - b.degree;
      else if (peerSort === "last") {
        cmp =
          (a.lastSeen ? new Date(a.lastSeen).getTime() : 0) -
          (b.lastSeen ? new Date(b.lastSeen).getTime() : 0);
      } else {
        const type = peerSort.slice(4);
        // Sorting by a relationship column ranks the companies that HAVE that
        // relationship, strongest first; everyone else falls to the bottom.
        cmp =
          (a.byType[type]?.strength_avg ?? -1) - (b.byType[type]?.strength_avg ?? -1);
      }
      if (cmp === 0) cmp = a.peer.localeCompare(b.peer) * (peerDir === "asc" ? 1 : -1);
      return cmp * mult;
    });
  }, [peerRows, peerSort, peerDir, effectiveTypeFilter]);

  /** Rel types the focus actually has, so empty columns don't pad the table. */
  const activeRelTypes = useMemo(
    () => relTypes.filter((t) => peerRows.some((r) => r.byType[t])),
    [relTypes, peerRows],
  );

  /** Isolate a relationship, and rank it strongest-first while we're there. */
  function toggleTypeFilter(type: string) {
    if (typeFilter === type) {
      setTypeFilter(null);
      setPeerSort("strongest");
      setPeerDir("desc");
      return;
    }
    setTypeFilter(type);
    setPeerSort(`rel:${type}`);
    setPeerDir("desc");
  }

  const countsByType = useMemo(() => {
    const m: Record<string, number> = {};
    for (const t of activeRelTypes) {
      m[t] = peerRows.reduce((n, r) => (r.byType[t] ? n + 1 : n), 0);
    }
    return m;
  }, [activeRelTypes, peerRows]);

  const scopedEdges = useMemo(() => {
    if (edgeScope === "all") return edges;
    return edges.filter(
      (e) => e.from_ticker === focusTicker || e.to_ticker === focusTicker,
    );
  }, [edges, edgeScope, focusTicker]);

  const sortedEdges = useMemo(() => {
    const mult = edgeDir === "asc" ? 1 : -1;
    return [...scopedEdges].sort((a, b) => {
      let cmp = 0;
      if (edgeSort === "from") cmp = a.from_ticker.localeCompare(b.from_ticker);
      else if (edgeSort === "to") cmp = a.to_ticker.localeCompare(b.to_ticker);
      else if (edgeSort === "type") cmp = a.rel_type.localeCompare(b.rel_type);
      else if (edgeSort === "strength") cmp = a.strength_avg - b.strength_avg;
      else if (edgeSort === "mentions") cmp = (a.mention_count ?? 0) - (b.mention_count ?? 0);
      else if (edgeSort === "articles") cmp = (a.article_count ?? 0) - (b.article_count ?? 0);
      else {
        cmp =
          (a.last_seen_at ? new Date(a.last_seen_at).getTime() : 0) -
          (b.last_seen_at ? new Date(b.last_seen_at).getTime() : 0);
      }
      return cmp * mult;
    });
  }, [scopedEdges, edgeSort, edgeDir]);

  function togglePeerSort(key: PeerSortKey) {
    if (peerSort === key) {
      setPeerDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setPeerSort(key);
    setPeerDir(key === "peer" ? "asc" : "desc");
  }

  function toggleEdgeSort(key: EdgeSortKey) {
    if (edgeSort === key) {
      setEdgeDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setEdgeSort(key);
    setEdgeDir(key === "from" || key === "to" || key === "type" ? "asc" : "desc");
  }

  /** Which end of an arbitrary edge the details panel should describe. */
  const edgePeer = (e: RelationshipEdge) =>
    e.from_ticker === focusTicker
      ? e.to_ticker
      : e.to_ticker === focusTicker
        ? e.from_ticker
        : e.from_ticker;

  const isSelectedEdge = (e: RelationshipEdge) =>
    selectedEdge != null &&
    selectedEdge.from_ticker === e.from_ticker &&
    selectedEdge.to_ticker === e.to_ticker &&
    (selectedEdge.rel_type ?? e.rel_type) === e.rel_type;

  if (edges.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-[42ch] text-center">
          <p className="text-sm font-medium text-foreground">Nothing to tabulate</p>
          <p className="mt-1 text-sm text-muted-foreground">
            No relationships match the current edge filters. Re-enable a
            relationship type, widen to Tier 2, or search a different ticker.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-card px-2 pb-6 pt-2">
      {/* ── Focus pivot: who the focused company is connected to ──────────── */}
      <section aria-labelledby="rel-pivot-heading">
        {/* Right padding keeps this clear of the floating Details toggle, which
            the host overlays at the top-right of this same container. */}
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 pb-2">
          <h3 id="rel-pivot-heading" className="text-sm font-semibold tracking-tight">
            <span className="font-mono">{focusTicker}</span>
            <span className="font-sans font-normal text-muted-foreground">
              {effectiveTypeFilter
                ? ` — its ${sortedPeers.length} ${effectiveTypeFilter}${sortedPeers.length === 1 ? "" : "s"}`
                : " — who it's connected to"}
            </span>
          </h3>
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            {effectiveTypeFilter ? (
              <button
                type="button"
                onClick={() => toggleTypeFilter(effectiveTypeFilter)}
                className="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-full border border-border px-2.5 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <X className="h-3 w-3 shrink-0" aria-hidden />
                Show all {peerRows.length} relationships
              </button>
            ) : (
              <span>
                {sortedPeers.length}{" "}
                {sortedPeers.length === 1 ? "company" : "companies"} · pick a
                relationship column to narrow it down
              </span>
            )}
            {focusTicker !== seedTicker ? (
              <button
                type="button"
                onClick={() => onSelectNode(seedTicker)}
                className="cursor-pointer underline underline-offset-2 hover:text-foreground"
              >
                back to {seedTicker}
              </button>
            ) : null}
          </p>
        </div>

        {sortedPeers.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            <span className="font-mono text-foreground">{focusTicker}</span> has no
            links of the currently-enabled types. Re-enable a relationship type or
            pick another company.
          </p>
        ) : (
          <>
            {/* Column meaning is the point here, so each header carries its
                legend swatch and the number of companies in that column. */}
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <caption className="sr-only">
                  Companies connected to {focusTicker}, one column per relationship
                  type. Cells show the strength of that link; select one to load its
                  article evidence.
                </caption>
                <thead className="bg-muted/40">
                  <tr className="border-b border-border">
                    <SortHeader
                      label="Company"
                      active={peerSort === "peer"}
                      dir={peerDir}
                      onClick={() => togglePeerSort("peer")}
                    />
                    {activeRelTypes.map((type) => (
                      <RelHeader
                        key={`ph-${type}`}
                        type={type}
                        count={countsByType[type] ?? 0}
                        color={relColors[type]}
                        isolated={effectiveTypeFilter === type}
                        sorted={peerSort === `rel:${type}`}
                        dir={peerDir}
                        focusTicker={focusTicker}
                        onClick={() => toggleTypeFilter(type)}
                      />
                    ))}
                    <SortHeader
                      label="Strongest"
                      active={peerSort === "strongest"}
                      dir={peerDir}
                      align="right"
                      onClick={() => togglePeerSort("strongest")}
                      title={`Strongest link with ${focusTicker}, across types`}
                    />
                    <SortHeader
                      label="Mentions"
                      active={peerSort === "mentions"}
                      dir={peerDir}
                      align="right"
                      onClick={() => togglePeerSort("mentions")}
                    />
                    <SortHeader
                      label="Own links"
                      active={peerSort === "degree"}
                      dir={peerDir}
                      align="right"
                      onClick={() => togglePeerSort("degree")}
                      title="How connected this company is in the loaded graph — how much there is to drill into"
                    />
                    <SortHeader
                      label="Last seen"
                      active={peerSort === "last"}
                      dir={peerDir}
                      align="right"
                      onClick={() => togglePeerSort("last")}
                    />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {sortedPeers.map((row) => (
                    <tr
                      key={`peer-${row.peer}`}
                      className="transition-colors hover:bg-muted/20"
                    >
                      <th scope="row" className="px-2 py-1 text-left font-normal">
                        <button
                          type="button"
                          onClick={() => onSelectNode(row.peer)}
                          className="group inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded px-1 font-mono text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                          title={`Re-root this table on ${row.peer}`}
                        >
                          {row.peer}
                          <CornerDownRight
                            className="h-3 w-3 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground"
                            aria-hidden
                          />
                          <span className="sr-only">
                            — show {row.peer}&apos;s own relationships
                          </span>
                        </button>
                      </th>
                      {activeRelTypes.map((type) => {
                        const edge = row.byType[type];
                        if (!edge) {
                          return (
                            <td
                              key={`${row.peer}-${type}`}
                              className="px-2 py-1 text-right tabular-nums text-muted-foreground/40"
                            >
                              ·
                            </td>
                          );
                        }
                        const selected = isSelectedEdge(edge);
                        // Tint carries link strength, so a column reads as a
                        // ranked block of colour before you read any numbers.
                        const alpha = 0.1 + edge.strength_avg * 0.35;
                        return (
                          <td key={`${row.peer}-${type}`} className="p-0.5 text-right">
                            <button
                              type="button"
                              onClick={() =>
                                onSelectEdge(
                                  {
                                    from_ticker: edge.from_ticker,
                                    to_ticker: edge.to_ticker,
                                    rel_type: edge.rel_type,
                                  },
                                  row.peer,
                                )
                              }
                              style={{ backgroundColor: relTint(relColors[type], alpha) }}
                              className={`inline-flex min-h-9 w-full cursor-pointer items-center justify-end rounded px-2 tabular-nums transition-shadow focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                                selected ? "ring-1 ring-foreground/50" : ""
                              }`}
                              aria-label={`${row.peer} is a ${type} of ${focusTicker}, strength ${(edge.strength_avg * 100).toFixed(0)} percent. Show the articles behind this link.`}
                            >
                              {(edge.strength_avg * 100).toFixed(0)}%
                            </button>
                          </td>
                        );
                      })}
                      <td className="px-2 py-1 text-right font-semibold tabular-nums">
                        {(row.strongest * 100).toFixed(0)}%
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">
                        {row.mentions.toLocaleString("en-US")}
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">
                        {row.degree.toLocaleString("en-US")}
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">
                        {fmtDate(row.lastSeen)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Below `md` a matrix is unreadable — group by relationship type
                instead, which is the same question answered vertically. */}
            <ul className="mt-2 flex flex-col gap-3 md:hidden">
              {activeRelTypes.map((type) => {
                const rows = sortedPeers.filter((r) => r.byType[type]);
                if (rows.length === 0) return null;
                return (
                  <li key={`m-${type}`}>
                    <p className="flex items-center gap-1.5 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      <span
                        className="h-2 w-2 shrink-0 rounded-sm"
                        style={{ backgroundColor: relColors[type] }}
                        aria-hidden
                      />
                      {type} ({rows.length})
                    </p>
                    <ul className="divide-y divide-border rounded-lg border border-border">
                      {rows.map((row) => {
                        const edge = row.byType[type]!;
                        return (
                          <li key={`m-${type}-${row.peer}`}>
                            <button
                              type="button"
                              onClick={() =>
                                onSelectEdge(
                                  {
                                    from_ticker: edge.from_ticker,
                                    to_ticker: edge.to_ticker,
                                    rel_type: edge.rel_type,
                                  },
                                  row.peer,
                                )
                              }
                              className="flex min-h-11 w-full cursor-pointer items-center justify-between gap-3 px-3 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
                            >
                              <span className="font-mono text-sm font-semibold">
                                {row.peer}
                              </span>
                              <span className="tabular-nums text-xs text-muted-foreground">
                                {(edge.strength_avg * 100).toFixed(0)}% ·{" "}
                                {edge.mention_count ?? 0} mentions
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>

      {/* ── Edge list ─────────────────────────────────────────────────────── */}
      <section aria-labelledby="rel-edges-heading" className="mt-6">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 pb-2">
          <h3
            id="rel-edges-heading"
            className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
          >
            Edges ({sortedEdges.length})
          </h3>
          <div
            role="radiogroup"
            aria-label="Edge list scope"
            className="inline-flex rounded-md border border-border bg-muted/40 p-0.5 text-xs"
          >
            {(
              [
                { key: "focus", label: focusTicker || "Focus" },
                { key: "all", label: "All" },
              ] as const
            ).map(({ key, label }) => {
              const active = edgeScope === key;
              return (
                <button
                  key={key}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setEdgeScope(key)}
                  className={`inline-flex min-h-9 cursor-pointer items-center rounded px-3 font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                    active
                      ? "bg-background text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  } ${key === "focus" ? "font-mono" : ""}`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* A seven-column edge table does not survive a phone; cards below `md`. */}
        <ul className="flex flex-col gap-2 md:hidden">
          {sortedEdges.map((e, i) => (
            <li key={`ec-${e.from_ticker}-${e.to_ticker}-${e.rel_type}-${i}`}>
              <button
                type="button"
                onClick={() => onSelectEdge(e, edgePeer(e))}
                className={`w-full cursor-pointer rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                  isSelectedEdge(e) ? "border-foreground/40 bg-muted/40" : "border-border"
                }`}
              >
                <div className="flex items-center gap-2 font-mono text-sm font-semibold">
                  {e.from_ticker}
                  <span aria-hidden className="text-muted-foreground">
                    →
                  </span>
                  <span className="sr-only">to</span>
                  {e.to_ticker}
                </div>
                <div className="mt-1 flex items-center gap-1.5">
                  <span
                    className="h-2 w-2 shrink-0 rounded-sm"
                    style={{ backgroundColor: relColors[e.rel_type] }}
                    aria-hidden
                  />
                  <span className="text-xs text-muted-foreground">{e.rel_type}</span>
                </div>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Strength</dt>
                    <dd className="tabular-nums">{(e.strength_avg * 100).toFixed(0)}%</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Mentions</dt>
                    <dd className="tabular-nums">{e.mention_count ?? 0}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Articles</dt>
                    <dd className="tabular-nums">{e.article_count ?? 0}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Last seen</dt>
                    <dd className="tabular-nums">{fmtDate(e.last_seen_at)}</dd>
                  </div>
                </dl>
              </button>
            </li>
          ))}
        </ul>

        <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">
              Relationship edges in the current neighbourhood. Select a row to load
              its article evidence.
            </caption>
            <thead className="bg-muted/40">
              <tr className="border-b border-border">
                <SortHeader
                  label="From"
                  active={edgeSort === "from"}
                  dir={edgeDir}
                  onClick={() => toggleEdgeSort("from")}
                />
                <SortHeader
                  label="Type"
                  active={edgeSort === "type"}
                  dir={edgeDir}
                  onClick={() => toggleEdgeSort("type")}
                />
                <SortHeader
                  label="To"
                  active={edgeSort === "to"}
                  dir={edgeDir}
                  onClick={() => toggleEdgeSort("to")}
                />
                <SortHeader
                  label="Strength"
                  active={edgeSort === "strength"}
                  dir={edgeDir}
                  align="right"
                  onClick={() => toggleEdgeSort("strength")}
                />
                <SortHeader
                  label="Mentions"
                  active={edgeSort === "mentions"}
                  dir={edgeDir}
                  align="right"
                  onClick={() => toggleEdgeSort("mentions")}
                />
                <SortHeader
                  label="Articles"
                  active={edgeSort === "articles"}
                  dir={edgeDir}
                  align="right"
                  onClick={() => toggleEdgeSort("articles")}
                />
                <SortHeader
                  label="Last seen"
                  active={edgeSort === "last"}
                  dir={edgeDir}
                  align="right"
                  onClick={() => toggleEdgeSort("last")}
                />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sortedEdges.map((e, i) => {
                const selected = isSelectedEdge(e);
                return (
                  <tr
                    key={`er-${e.from_ticker}-${e.to_ticker}-${e.rel_type}-${i}`}
                    role="button"
                    tabIndex={0}
                    aria-label={`${e.from_ticker} ${e.rel_type} ${e.to_ticker}. Load article evidence.`}
                    onClick={() => onSelectEdge(e, edgePeer(e))}
                    onKeyDown={(ev) => {
                      if (ev.key !== "Enter" && ev.key !== " ") return;
                      ev.preventDefault();
                      onSelectEdge(e, edgePeer(e));
                    }}
                    className={`cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring ${
                      selected ? "bg-muted/50" : "hover:bg-muted/20"
                    }`}
                  >
                    <td className="px-2 py-1.5 font-mono font-medium">{e.from_ticker}</td>
                    <td className="px-2 py-1.5">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 shrink-0 rounded-sm"
                          style={{ backgroundColor: relColors[e.rel_type] }}
                          aria-hidden
                        />
                        <span className="text-xs text-muted-foreground">{e.rel_type}</span>
                      </span>
                    </td>
                    <td className="px-2 py-1.5 font-mono font-medium">{e.to_ticker}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {(e.strength_avg * 100).toFixed(0)}%
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {(e.mention_count ?? 0).toLocaleString("en-US")}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {(e.article_count ?? 0).toLocaleString("en-US")}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {fmtDate(e.last_seen_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {sortedEdges.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
            No edges in this scope.
          </p>
        ) : null}
      </section>
    </div>
  );
}
