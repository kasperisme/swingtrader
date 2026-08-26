"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  relationshipsGetAliases,
  relationshipsGetAliasesBulk,
  relationshipsGetEdgeEvidence,
  relationshipsGetNeighborhood,
  relationshipsGetNodeNews,
  relationshipsGetNodeSentiment,
  relationshipsGetPairStats,
  relationshipsResolveTicker,
  type AliasRow,
  type AliasMap,
  type EdgeEvidence,
  type NodeNewsRow,
  type NodeSentimentRow,
  type NodeSentimentWindow,
  type PairStat,
  type RelationshipEdge,
} from "@/app/actions/relationships";
import { TickerSearchCombobox } from "@/components/ticker-search-combobox";
import { ChevronRight, Loader2, Network, Table as TableIcon, X } from "lucide-react";
import type { ReactNode } from "react";
import { VectorsUI, type TickerRow } from "@/app/protected/vectors/vectors-ui";
import { NetworkGraphD3 } from "./network-graph-d3";
import { RelationshipTableView } from "./relationship-table-view";

const REL_COLORS: Record<string, string> = {
  competitor: "hsl(var(--chart-3))",
  supplier: "hsl(var(--chart-2))",
  customer: "hsl(var(--chart-1))",
  partner: "hsl(var(--chart-4))",
  acquirer: "hsl(var(--chart-5))",
  subsidiary: "hsl(var(--primary))",
};

const REL_TYPES = [
  "competitor",
  "supplier",
  "customer",
  "partner",
  "acquirer",
  "subsidiary",
] as const;

// The "vectors" tab is named for what it renders — the company's dimension
// vectors — not "Company Profile", which is what the quote page shows.
const SIDE_TABS = [
  { key: "details", label: "How it's linked" },
  { key: "vectors", label: "Dimensions" },
  { key: "sentiment", label: "Sentiment" },
] as const;

export type RelationshipNetworkExplorerProps = {
  vectors?: TickerRow[];
  initialSeedTicker?: string;
  /** Hide ticker search + Explore when the host UI supplies the seed (e.g. screenings nav). */
  hideSeedControls?: boolean;
  /** When true, the graph fills its parent container via ResizeObserver instead of using fixed GW/GH. */
  fillViewport?: boolean;
};

const NODE_R = 18;

/** Rows per page for every paginated list in the details drawer. */
const DRAWER_PAGE_SIZE = 10;

type SelectedEdge = {
  from_ticker: string;
  to_ticker: string;
  rel_type?: string;
} | null;

/**
 * The drawer's three paginated lists (edge evidence, node news, sentiment) each
 * inlined their own Prev/Next pair. None of them bounded `Next`, so paging past
 * the end showed an empty list with no explanation; none disabled `Prev` at page
 * 1; and all three rendered the same two accessible names, so a screen reader
 * heard "Prev, Next" six times on one panel with no way to tell them apart.
 *
 * `hasNext` is inferred from a full page of rows — the queries return rows, not
 * a total count.
 */
function Pager({
  label,
  page,
  setPage,
  rowCount,
  disabled = false,
}: {
  label: string;
  page: number;
  setPage: Dispatch<SetStateAction<number>>;
  rowCount: number;
  disabled?: boolean;
}) {
  const btnClass =
    "inline-flex min-h-9 cursor-pointer items-center rounded border border-border px-2.5 text-xs font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40";
  const hasNext = rowCount >= DRAWER_PAGE_SIZE;
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => setPage((p) => Math.max(1, p - 1))}
        disabled={disabled || page <= 1}
        className={btnClass}
        aria-label={`Previous page of ${label}`}
      >
        Prev
      </button>
      <span
        className="min-w-6 text-center text-xs tabular-nums text-muted-foreground"
        aria-label={`${label}, page ${page}`}
      >
        {page}
      </span>
      <button
        type="button"
        onClick={() => setPage((p) => p + 1)}
        disabled={disabled || !hasNext}
        className={btnClass}
        aria-label={`Next page of ${label}`}
      >
        Next
      </button>
    </div>
  );
}

/** Section heading for the explain-it tab — sentence case, no graph jargon. */
function SectionHeading({ children }: { children: ReactNode }) {
  return <h4 className="text-sm font-semibold tracking-tight">{children}</h4>;
}

function fmtDay(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(d);
}

/**
 * Plain-English definition of each relationship type, written for someone who
 * wants to know what the link *means for the two businesses* — not what an edge
 * is. Phrased without asserting which side is which: the stored direction is
 * whatever the articles described, and it is shown separately rather than baked
 * into a sentence we can't guarantee.
 */
const REL_MEANING: Record<string, string> = {
  competitor:
    "They chase the same customers in the same market. News that helps one often works against the other.",
  supplier:
    "One supplies parts, components or services to the other. Demand at the buyer flows back to the supplier.",
  customer:
    "One buys the other's products or services, so its spending turns up in the other's revenue.",
  partner:
    "They work together — a joint venture, a distribution deal, or shared technology.",
  acquirer: "One has acquired, or is moving to acquire, the other.",
  subsidiary: "One is owned by, or operates under, the other.",
};

/**
 * Reasoning text is stored with a direction marker (`[a_to_b]` / `[b_to_a]`)
 * glued to the front. That's a storage detail; it read as noise at the start of
 * every explanation. Strip it, and surface the reversed case as words instead.
 */
function cleanReasoning(text: string): { text: string; reversed: boolean } {
  const m = text.match(/^\s*\[(a_to_b|b_to_a)\]\s*/i);
  if (!m) return { text: text.trim(), reversed: false };
  return {
    text: text.slice(m[0].length).trim(),
    reversed: m[1].toLowerCase() === "b_to_a",
  };
}

/**
 * Database and transport failures are not written for readers. Translate the
 * ones we actually see into something a non-engineer can act on, and keep the
 * raw text available underneath rather than throwing it away.
 */
function humaneError(raw: string): { headline: string; detail: string | null } {
  const s = raw.toLowerCase();
  if (s.includes("statement timeout") || s.includes("canceling statement")) {
    return {
      headline:
        "This is taking too long to load — the query timed out. Try a narrower view (Tier 1) or reload.",
      detail: raw,
    };
  }
  if (s.includes("fetch") || s.includes("network")) {
    return { headline: "Couldn't reach the server. Check your connection and retry.", detail: raw };
  }
  return { headline: raw, detail: null };
}

/** A failed panel section, in words rather than a stack trace. */
function SectionError({ raw }: { raw: string }) {
  const { headline, detail } = humaneError(raw);
  return (
    <div role="alert" className="text-xs">
      <p className="text-destructive">{headline}</p>
      {detail ? (
        <details className="mt-1">
          <summary className="cursor-pointer text-muted-foreground">
            Technical detail
          </summary>
          <p className="mt-1 break-words font-mono text-[11px] text-muted-foreground">
            {detail}
          </p>
        </details>
      ) : null}
    </div>
  );
}

/** How much weight to put on a link, in words rather than a bare percentage. */
function confidenceRead(strength: number): string {
  if (strength >= 0.85) return "Sources agree strongly on this.";
  if (strength >= 0.6) return "Most sources describe it this way.";
  if (strength >= 0.35) return "Mixed support — worth checking the articles.";
  return "Only loosely supported. Read the articles before relying on it.";
}

/** What this link is, and how it came to exist. */
function RelationshipExplainer({
  edge,
  detail,
}: {
  edge: NonNullable<SelectedEdge>;
  detail: RelationshipEdge | null;
}) {
  const relType = edge.rel_type ?? "related";
  return (
    <section className="flex flex-col gap-2">
      <SectionHeading>What this link says</SectionHeading>
      <p className="text-sm">
        <span className="font-mono font-semibold">{edge.from_ticker}</span> and{" "}
        <span className="font-mono font-semibold">{edge.to_ticker}</span> are
        recorded as <span className="font-semibold">{relType}</span>.
      </p>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {REL_MEANING[relType] ??
          "The two companies are linked, but this link type has no plain-language description yet."}
      </p>
      <p className="rounded-md border border-border bg-muted/30 p-2 text-xs leading-relaxed text-muted-foreground">
        Nobody typed this in. Each time a news article describes these two
        companies this way, the link is recorded and its confidence re-scored —
        so the numbers below summarise what the coverage actually said, and the
        articles underneath are the receipts. Direction is stored as the articles
        put it ({edge.from_ticker} → {edge.to_ticker}); it is not a claim about
        who depends on whom.
      </p>
      {detail ? (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Metric
              label="confidence"
              value={`${(detail.strength_avg * 100).toFixed(0)}%`}
            />
            <Metric label="articles" value={String(detail.article_count ?? 0)} />
            <Metric label="mentions" value={String(detail.mention_count ?? 0)} />
            <Metric label="first said" value={fmtDay(detail.first_seen_at)} />
            <Metric label="last said" value={fmtDay(detail.last_seen_at)} />
            <Metric
              label="peak"
              value={`${(detail.strength_max * 100).toFixed(0)}%`}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">
              {confidenceRead(detail.strength_avg)}
            </span>{" "}
            Confidence is the average across every article that described the
            link — not a probability that it is true.
          </p>
        </>
      ) : null}
    </section>
  );
}

/** The articles the link was derived from — the "show me why" section. */
function GraphDetailsEdgeEvidence({
  selectedEdge,
  evidencePage,
  setEvidencePage,
  evidenceRows,
  loading,
  listMaxClass,
}: {
  selectedEdge: SelectedEdge;
  evidencePage: number;
  setEvidencePage: Dispatch<SetStateAction<number>>;
  evidenceRows: EdgeEvidence[];
  loading: boolean;
  listMaxClass: string;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionHeading>The articles behind it</SectionHeading>
        {selectedEdge ? (
          <Pager
            label="supporting articles"
            page={evidencePage}
            setPage={setEvidencePage}
            rowCount={evidenceRows.length}
            disabled={loading}
          />
        ) : null}
      </div>
      {selectedEdge && evidenceRows.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Every article that described this relationship, with the sentence-level
          reason it counted.
        </p>
      ) : null}
      <div className={`overflow-auto ${listMaxClass}`}>
        {loading ? (
          // Without this the empty state renders mid-fetch and tells the user
          // there are no articles for a link that has six of them.
          <p className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            Loading articles…
          </p>
        ) : evidenceRows.length === 0 ? (
          // "No articles for this link" and "you haven't picked a link" are
          // different states; one message for both read as if the selection
          // hadn't registered.
          <p className="text-xs text-muted-foreground">
            {selectedEdge ? (
              <>
                No articles are retained for{" "}
                <span className="font-mono">
                  {selectedEdge.from_ticker} → {selectedEdge.to_ticker}
                </span>
                {evidencePage > 1 ? " on this page." : "."}
              </>
            ) : (
              "Pick a relationship to see the articles it came from."
            )}
          </p>
        ) : (
          <ol className="divide-y divide-border">
            {evidenceRows.map((row) => (
              <li key={`${row.edge_id}-${row.article_id}`} className="py-2">
                <a
                  href={row.article_url ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs font-medium text-foreground hover:underline"
                >
                  {row.article_title ?? `Article #${row.article_id}`}
                </a>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {row.published_at
                    ? new Date(row.published_at).toLocaleDateString("en-GB", {
                        year: "numeric",
                        month: "short",
                        day: "2-digit",
                      })
                    : "Date unknown"}
                  {row.head_confidence == null
                    ? ""
                    : ` · ${(row.head_confidence * 100).toFixed(0)}% confident`}
                </p>
                {row.reasoning_text ? (
                  (() => {
                    const { text, reversed } = cleanReasoning(row.reasoning_text);
                    if (!text) return null;
                    return (
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        <span className="font-medium text-foreground">
                          Why it counted:
                        </span>{" "}
                        {text}
                        {reversed ? (
                          <span className="text-muted-foreground/70">
                            {" "}
                            (this article put the relationship the other way
                            round)
                          </span>
                        ) : null}
                      </p>
                    );
                  })()
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

/** Map a z-score to a 0–100% position on a [-4, +4] track. */
function zToPct(z: number): number {
  const clamped = Math.max(-4, Math.min(4, z));
  return ((clamped + 4) / 8) * 100;
}

/** Trading regime + colour for the current |z|, mirroring the CLI thresholds. */
function zRegime(z: number): { label: string; color: string } {
  const az = Math.abs(z);
  if (az >= 3.5) return { label: "Stop — diverging", color: "hsl(var(--destructive))" };
  if (az >= 2) return { label: "Entry signal", color: "hsl(var(--chart-3))" };
  if (az >= 0.5) return { label: "Watch", color: "hsl(var(--chart-5))" };
  return { label: "At mean — no signal", color: "hsl(var(--muted-foreground))" };
}

/** Long/short read of a z-score for a cointegrated pair (spread = A − β·B). */
function zTradeRead(z: number, a: string, b: string): string {
  if (z >= 2) return `${a} rich vs ${b} → short ${a}, long ${b}`;
  if (z <= -2) return `${a} cheap vs ${b} → long ${a}, short ${b}`;
  return "Within band — wait for |z| > 2";
}

/** -4…+4 z-score band with entry/exit/stop ticks and the live marker. */
function ZScoreGauge({ z }: { z: number }) {
  const ticks = [-3.5, -2, -0.5, 0.5, 2, 3.5];
  const regime = zRegime(z);
  return (
    <div className="mt-2">
      <div className="relative h-6">
        {/* track */}
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-muted" />
        {/* threshold ticks */}
        {ticks.map((t) => (
          <div
            key={t}
            className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-border"
            style={{ left: `${zToPct(t)}%` }}
          />
        ))}
        {/* zero line */}
        <div
          className="absolute top-1/2 h-4 w-px -translate-y-1/2 bg-foreground/40"
          style={{ left: "50%" }}
        />
        {/* live marker */}
        <div
          className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background shadow"
          style={{ left: `${zToPct(z)}%`, backgroundColor: regime.color }}
        />
      </div>
      <div className="mt-0.5 flex justify-between text-[11px] text-muted-foreground">
        <span>-3.5</span>
        <span>-2</span>
        <span>0</span>
        <span>+2</span>
        <span>+3.5</span>
      </div>
    </div>
  );
}

/** Cointegration / pairs-trading metrics for the selected edge's pair. */
function PairCointegrationPanel({
  pairStat,
  loading,
}: {
  pairStat: PairStat | null;
  loading: boolean;
}) {
  const header = (
    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      Cointegration
    </p>
  );

  if (loading) {
    return (
      <div className="mb-3">
        {header}
        <div className="mt-1 flex items-center gap-2 p-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Loading pair stats…
        </div>
      </div>
    );
  }

  if (!pairStat || pairStat.hedge_ratio == null) {
    return (
      <div className="mb-3">
        {header}
        <p className="mt-1 p-2 text-xs text-muted-foreground">
          No price calibration yet for this pair. It will be fitted on the next
          calibration run if it clears the candidate threshold.
        </p>
      </div>
    );
  }

  const { ticker_a, ticker_b, is_cointegrated, coint_pvalue, half_life_days, current_zscore } =
    pairStat;
  const z = current_zscore;
  const regime = z == null ? null : zRegime(z);

  return (
    <div className="mb-3">
      <div className="flex items-center justify-between">
        {header}
        <span
          className="rounded px-1.5 py-0.5 text-[11px] font-semibold"
          style={{
            color: is_cointegrated ? "hsl(var(--chart-3))" : "hsl(var(--muted-foreground))",
            backgroundColor: is_cointegrated
              ? "hsl(var(--chart-3) / 0.12)"
              : "hsl(var(--muted))",
          }}
        >
          {is_cointegrated ? "COINTEGRATED" : "NOT COINTEGRATED"}
        </span>
      </div>

      <div className="mt-1 grid grid-cols-3 gap-2 text-xs">
        <Metric label="p-value" value={coint_pvalue == null ? "—" : coint_pvalue.toFixed(3)} />
        <Metric label="half-life" value={half_life_days == null ? "—" : `${half_life_days.toFixed(1)}d`} />
        <Metric
          label="z-score"
          value={z == null ? "—" : `${z >= 0 ? "+" : ""}${z.toFixed(2)}`}
          valueColor={regime?.color}
        />
      </div>

      {z == null ? (
        <p className="mt-2 text-[11px] text-muted-foreground">Awaiting z-score refresh.</p>
      ) : (
        <>
          <ZScoreGauge z={z} />
          <p className="mt-1.5 text-[11px]" style={{ color: regime?.color }}>
            {regime?.label}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {is_cointegrated
              ? zTradeRead(z, ticker_a, ticker_b)
              : `Not cointegrated (p=${coint_pvalue == null ? "—" : coint_pvalue.toFixed(2)}) — a large |z| here is divergence risk, not a signal.`}
          </p>
        </>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="rounded border border-border px-2 py-1">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono text-sm font-medium" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </p>
    </div>
  );
}

export function RelationshipNetworkExplorer(
  props: RelationshipNetworkExplorerProps,
) {
  const vectors = props.vectors ?? [];
  const hideSeedControls = props.hideSeedControls ?? false;
  const fillViewport = props.fillViewport ?? false;
  const FIXED_MIN_STRENGTH = 0.25;
  const FIXED_MIN_MENTIONS = 1;

  const containerRef = useRef<HTMLDivElement>(null);
  const [dynamicSize, setDynamicSize] = useState<{
    w: number;
    h: number;
  } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      // A hidden ancestor — a closed tab panel on a quote page — measures 0x0.
      // Committing that gives the SVG viewBox="0 0 0 0": every node renders,
      // none of them visible, and it never recovers unless the observer
      // happens to fire again. Zero means "not laid out yet", not "no space",
      // so hold the last good size (or the defaults) instead.
      if (width < 1 || height < 1) return;
      setDynamicSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const GW = dynamicSize?.w ?? 980;
  const GH = fillViewport ? (dynamicSize?.h ?? 560) : 560;
  const [sideTab, setSideTab] = useState<
    "details" | "vectors" | "sentiment"
  >("details");
  // Graph vs table are two reads of the SAME loaded neighbourhood — switching
  // never refetches and never changes the selection, only the presentation.
  const [viewMode, setViewMode] = useState<"graph" | "table">("graph");
  // Which company the table is pivoted on. Deliberately NOT `selectedNode`:
  // clicking a cell in AAPL's row of competitors should load Samsung into the
  // details panel while the table stays on AAPL. Re-rooting only happens when
  // you click a company name.
  const [tableFocus, setTableFocus] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [seedInput, setSeedInput] = useState(props.initialSeedTicker ?? "AAPL");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seedTicker, setSeedTicker] = useState<string>("");
  const [edges, setEdges] = useState<RelationshipEdge[]>([]);
  const [nodes, setNodes] = useState<string[]>([]);
  const [truncated, setTruncated] = useState(false);

  // Fetch depth: tier-1 (direct neighbours) by default; tier-2 pulls in the
  // neighbours-of-neighbours when the user opts in.
  const [hops, setHops] = useState<1 | 2>(1);
  const [selectedRelTypes, setSelectedRelTypes] = useState<string[]>([
    ...REL_TYPES,
  ]);

  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<SelectedEdge>(null);
  const [aliases, setAliases] = useState<AliasRow[]>([]);
  const [aliasesByNode, setAliasesByNode] = useState<AliasMap>({});
  const [nodeNewsRows, setNodeNewsRows] = useState<NodeNewsRow[]>([]);
  const [nodeNewsPage, setNodeNewsPage] = useState(1);
  const [nodeNewsLoading, setNodeNewsLoading] = useState(false);
  const [nodeNewsError, setNodeNewsError] = useState<string | null>(null);
  const [sentimentRows, setSentimentRows] = useState<NodeSentimentRow[]>([]);
  const [sentimentWindows, setSentimentWindows] = useState<
    NodeSentimentWindow[]
  >([]);
  const [sentimentPage, setSentimentPage] = useState(1);
  const [sentimentLoading, setSentimentLoading] = useState(false);
  const [sentimentError, setSentimentError] = useState<string | null>(null);
  const [evidenceRows, setEvidenceRows] = useState<EdgeEvidence[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidencePage, setEvidencePage] = useState(1);
  const [pairStat, setPairStat] = useState<PairStat | null>(null);
  const [pairStatLoading, setPairStatLoading] = useState(false);
  const [manualPositions, setManualPositions] = useState<
    Record<string, { x: number; y: number }>
  >({});

  const filteredEdges = useMemo(
    () => edges.filter((e) => selectedRelTypes.includes(e.rel_type)),
    [edges, selectedRelTypes],
  );

  // `selectedEdge` is only an identity triple. The explainer needs the link's
  // real numbers (confidence, article/mention counts, first and last seen),
  // which live on the loaded edge set.
  const selectedEdgeDetail = useMemo(() => {
    if (!selectedEdge) return null;
    return (
      edges.find(
        (e) =>
          e.from_ticker === selectedEdge.from_ticker &&
          e.to_ticker === selectedEdge.to_ticker &&
          (selectedEdge.rel_type == null || e.rel_type === selectedEdge.rel_type),
      ) ?? null
    );
  }, [edges, selectedEdge]);

  // The loaded neighborhood, with the rel-type legend applied live (all types are
  // selected by default, so the default view shows everything). Fetch depth is the
  // Tier 1 / Tier 2 toggle. Nodes left with no visible edge are dropped, but the
  // seed and the selected node are always kept.
  const visibleGraph = useMemo(() => {
    const present = new Set<string>();
    for (const e of filteredEdges) {
      present.add(e.from_ticker);
      present.add(e.to_ticker);
    }
    if (seedTicker) present.add(seedTicker);
    if (selectedNode) present.add(selectedNode);
    return { nodes: nodes.filter((n) => present.has(n)), edges: filteredEdges };
  }, [nodes, filteredEdges, seedTicker, selectedNode]);

  const connectedSet = useMemo(() => {
    if (!selectedNode) return new Set<string>();
    const out = new Set<string>();
    for (const edge of visibleGraph.edges) {
      if (edge.from_ticker === selectedNode) out.add(edge.to_ticker);
      if (edge.to_ticker === selectedNode) out.add(edge.from_ticker);
    }
    return out;
  }, [selectedNode, visibleGraph.edges]);

  const searchSuggestions = useMemo(() => {
    const base = new Set<string>();
    if (seedTicker) base.add(seedTicker);
    for (const n of nodes) base.add(n);
    for (const [canonical, aliases] of Object.entries(aliasesByNode)) {
      if (canonical) base.add(canonical);
      for (const a of aliases) base.add(a);
    }
    const q = seedInput.trim().toUpperCase();
    const all = Array.from(base)
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
    if (!q) return all.slice(0, 20);
    const starts = all.filter((s) => s.startsWith(q));
    const contains = all.filter((s) => !s.startsWith(q) && s.includes(q));
    return [...starts, ...contains].slice(0, 20);
  }, [aliasesByNode, nodes, seedInput, seedTicker]);

  const nodeConnections = useMemo(() => {
    if (!selectedNode) return [];
    return visibleGraph.edges
      .filter(
        (e) => e.from_ticker === selectedNode || e.to_ticker === selectedNode,
      )
      .map((e) => ({
        ...e,
        peer: e.from_ticker === selectedNode ? e.to_ticker : e.from_ticker,
      }))
      .sort((a, b) => b.strength_avg - a.strength_avg);
  }, [selectedNode, visibleGraph.edges]);

  const selectedNodeVectors = useMemo(() => {
    if (!selectedNode) return [];
    const allowed = new Set<string>([
      selectedNode,
      ...(aliasesByNode[selectedNode] ?? []).map((v) => v.toUpperCase()),
    ]);
    return vectors.filter((row) => allowed.has(row.ticker.toUpperCase()));
  }, [aliasesByNode, selectedNode, vectors]);

  const showBootstrapSpinner =
    hideSeedControls && loading && nodes.length === 0 && !error;
  const showMainGraph = !hideSeedControls || !showBootstrapSpinner;

  async function loadNeighborhood(
    resetSelection = true,
    seedOverride?: string,
  ) {
    setLoading(true);
    setError(null);
    const resolved = await relationshipsResolveTicker(
      seedOverride ?? seedInput,
    );
    if (!resolved.ok) {
      setLoading(false);
      setError(resolved.error);
      return;
    }
    const canonical = resolved.data.canonicalTicker;
    const result = await relationshipsGetNeighborhood({
      seedTicker: canonical,
      hops,
      minStrength: FIXED_MIN_STRENGTH,
      minMentions: FIXED_MIN_MENTIONS,
      relTypes: selectedRelTypes,
      limitNodes: 140,
      limitEdges: 360,
    });
    setLoading(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setSeedTicker(result.data.seedTicker);
    setSeedInput(result.data.seedTicker);
    setNodes(result.data.nodes);
    setEdges(result.data.edges);
    setTruncated(result.data.truncated);
    if (resetSelection) {
      setSelectedEdge(null);
      setTableFocus(null);
      setEvidenceRows([]);
      setEvidencePage(1);
      setNodeNewsRows([]);
      setNodeNewsPage(1);
      setSentimentRows([]);
      setSentimentPage(1);
      const seed = result.data.seedTicker;
      const seedNode =
        seed.length > 0
          ? (result.data.nodes.find(
              (n) => n.toUpperCase() === seed.toUpperCase(),
            ) ?? null)
          : null;
      setSelectedNode(seedNode);
    }
  }

  const expandAroundNode = useCallback(
    async (node: string) => {
      const result = await relationshipsGetNeighborhood({
        seedTicker: node,
        hops,
        minStrength: FIXED_MIN_STRENGTH,
        minMentions: FIXED_MIN_MENTIONS,
        relTypes: selectedRelTypes,
        limitNodes: 140,
        limitEdges: 360,
      });
      if (!result.ok) {
        setError(result.error);
        return;
      }

      setNodes((prev) =>
        Array.from(new Set([...prev, ...result.data.nodes])).sort(),
      );
      setEdges((prev) => {
        const byKey = new Map<string, RelationshipEdge>();
        for (const edge of prev) {
          byKey.set(
            `${edge.from_ticker}|${edge.to_ticker}|${edge.rel_type}`,
            edge,
          );
        }
        for (const edge of result.data.edges) {
          byKey.set(
            `${edge.from_ticker}|${edge.to_ticker}|${edge.rel_type}`,
            edge,
          );
        }
        return Array.from(byKey.values());
      });
      setTruncated((prev) => prev || result.data.truncated);
    },
    [hops, selectedRelTypes],
  );

  const onManualPositionsMerge = useCallback(
    (patch: Record<string, { x: number; y: number }>) => {
      setManualPositions((prev) => ({ ...prev, ...patch }));
    },
    [],
  );

  const onGraphNodeClick = useCallback(
    (node: string) => {
      void (async () => {
        setSelectedNode(node);
        setSelectedEdge(null);
        setEvidenceRows([]);
        setNodeNewsPage(1);
        setSentimentPage(1);
        await expandAroundNode(node);
      })();
    },
    [expandAroundNode],
  );

  const onGraphNodeDoubleClick = useCallback((node: string) => {
    setSelectedNode(node);
    setIsDrawerOpen((prev) => !prev);
  }, []);

  const onGraphEdgeClick = useCallback(
    (edge: { from_ticker: string; to_ticker: string; rel_type: string }) => {
      setSelectedNode(null);
      setSelectedEdge(edge);
      setEvidencePage(1);
    },
    [],
  );

  const onGraphEdgeDoubleClick = useCallback(
    (edge: { from_ticker: string; to_ticker: string; rel_type: string }) => {
      setSelectedNode(null);
      setSelectedEdge(edge);
      setEvidencePage(1);
      setSideTab("details");
      setIsDrawerOpen((prev) => !prev);
    },
    [],
  );

  /**
   * Picking a relationship in the table. The panel loads the COUNTERPARTY —
   * clicking Samsung's cell in AAPL's competitor column is a question about
   * Samsung — while the table itself stays pivoted on AAPL.
   *
   * Table mode has no floating Details toggle, so this is also what opens the
   * panel; the current tab is left alone so the answer lands where the user was
   * already looking.
   */
  const onTableEdgeSelect = useCallback(
    (
      edge: { from_ticker: string; to_ticker: string; rel_type: string },
      peer?: string,
    ) => {
      if (peer) setSelectedNode(peer);
      setSelectedEdge(edge);
      setEvidencePage(1);
      setNodeNewsPage(1);
      setSentimentPage(1);
      setIsDrawerOpen(true);
    },
    [],
  );

  /** Clicking a company NAME re-roots the table on it. */
  const onTableFocusNode = useCallback(
    (ticker: string) => {
      setTableFocus(ticker);
      onGraphNodeClick(ticker);
    },
    [onGraphNodeClick],
  );

  const onGraphSvgBackgroundDoubleClick = useCallback(() => {
    setIsDrawerOpen((prev) => {
      if (prev) return false;
      return prev;
    });
  }, []);

  useEffect(() => {
    void loadNeighborhood(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch the neighbourhood at the new depth when the tier toggle changes
  // (skip the initial mount, which the effect above already covers).
  const hopsInitialized = useRef(false);
  useEffect(() => {
    if (!hopsInitialized.current) {
      hopsInitialized.current = true;
      return;
    }
    void loadNeighborhood(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hops]);

  useEffect(() => {
    if (!selectedNode) return;
    relationshipsGetAliases(selectedNode).then((res) => {
      if (!res.ok) return;
      setAliases(res.data);
    });
  }, [selectedNode]);

  useEffect(() => {
    if (nodes.length === 0) {
      setAliasesByNode({});
      return;
    }
    relationshipsGetAliasesBulk(nodes).then((res) => {
      if (!res.ok) return;
      setAliasesByNode(res.data);
    });
  }, [nodes]);

  useEffect(() => {
    if (!selectedNode) return;
    setNodeNewsLoading(true);
    setNodeNewsError(null);
    relationshipsGetNodeNews({
      ticker: selectedNode,
      page: nodeNewsPage,
      pageSize: DRAWER_PAGE_SIZE,
    })
      .then((res) => {
        setNodeNewsLoading(false);
        if (!res.ok) {
          setNodeNewsError(res.error);
          setNodeNewsRows([]);
          return;
        }
        setNodeNewsRows(res.data.rows);
      })
      .catch((err) => {
        setNodeNewsLoading(false);
        setNodeNewsError(
          err instanceof Error ? err.message : "Failed to load node news",
        );
        setNodeNewsRows([]);
      });
  }, [selectedNode, nodeNewsPage]);

  useEffect(() => {
    if (!selectedNode) return;
    setSentimentLoading(true);
    setSentimentError(null);
    relationshipsGetNodeSentiment({
      ticker: selectedNode,
      page: sentimentPage,
      pageSize: DRAWER_PAGE_SIZE,
    })
      .then((res) => {
        setSentimentLoading(false);
        if (!res.ok) {
          setSentimentError(res.error);
          setSentimentRows([]);
          setSentimentWindows([]);
          return;
        }
        setSentimentRows(res.data.rows);
        setSentimentWindows(res.data.windows);
      })
      .catch((err) => {
        setSentimentLoading(false);
        setSentimentError(
          err instanceof Error ? err.message : "Failed to load node sentiment",
        );
        setSentimentRows([]);
        setSentimentWindows([]);
      });
  }, [selectedNode, sentimentPage]);

  useEffect(() => {
    if (!selectedEdge) {
      setEvidenceRows([]);
      setEvidenceLoading(false);
      return;
    }
    let cancelled = false;
    setEvidenceLoading(true);
    // Drop the previous link's articles immediately — they are evidence for a
    // different claim, and leaving them up attributes them to the new one.
    setEvidenceRows([]);
    relationshipsGetEdgeEvidence({
      fromTicker: selectedEdge.from_ticker,
      toTicker: selectedEdge.to_ticker,
      relType: selectedEdge.rel_type,
      page: evidencePage,
      pageSize: DRAWER_PAGE_SIZE,
    })
      .then((res) => {
        if (cancelled) return;
        setEvidenceLoading(false);
        if (!res.ok) return;
        setEvidenceRows(res.data.rows);
      })
      .catch(() => {
        if (!cancelled) setEvidenceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEdge, evidencePage]);

  useEffect(() => {
    if (!selectedEdge) {
      setPairStat(null);
      setPairStatLoading(false);
      return;
    }
    let cancelled = false;
    setPairStatLoading(true);
    relationshipsGetPairStats({
      fromTicker: selectedEdge.from_ticker,
      toTicker: selectedEdge.to_ticker,
    })
      .then((res) => {
        if (cancelled) return;
        setPairStat(res.ok ? res.data : null);
        setPairStatLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setPairStat(null);
        setPairStatLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEdge]);

  useEffect(() => {
    setManualPositions((prev) => {
      const next: Record<string, { x: number; y: number }> = {};
      for (const id of nodes) {
        if (prev[id]) next[id] = prev[id]!;
      }
      return next;
    });
  }, [nodes]);

  return (
    <div
      className={
        fillViewport
          ? "flex flex-col h-full min-h-0 w-full"
          : "flex flex-col gap-4 w-full"
      }
    >
      {showBootstrapSpinner ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading relationship graph…
        </div>
      ) : null}
      {showMainGraph ? (
        <>
          <div
            className={
              fillViewport
                ? "shrink-0 px-2 py-1.5 w-full  "
                : "px-2 py-1.5 w-full  "
            }
          >
            {!hideSeedControls ? (
              <div data-tour="relations-search" className="flex gap-2">
                <TickerSearchCombobox
                  className="flex-1"
                  value={seedInput}
                  onChange={setSeedInput}
                  onSubmit={() => void loadNeighborhood(true)}
                  options={searchSuggestions}
                  placeholder="Search ticker or alias…"
                />
                <button
                  onClick={() => void loadNeighborhood(true)}
                  className="min-h-11 shrink-0 cursor-pointer rounded-md border border-border bg-background px-4 text-sm font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default disabled:opacity-50"
                  disabled={loading}
                >
                  {loading ? "Loading..." : "Explore"}
                </button>
              </div>
            ) : null}
            <div data-tour="relations-filters" className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Edges
              </span>
              {REL_TYPES.map((type) => {
                const active = selectedRelTypes.includes(type);
                return (
                  <button
                    key={`legend-${type}`}
                    type="button"
                    onClick={(e) => {
                      if (e.detail > 1) return;
                      setSelectedRelTypes((prev) =>
                        active
                          ? prev.filter((v) => v !== type)
                          : [...prev, type],
                      );
                    }}
                    onDoubleClick={(e) => {
                      e.preventDefault();
                      setSelectedRelTypes([...REL_TYPES]);
                    }}
                    className={`inline-flex min-h-11 cursor-pointer items-center gap-1 rounded border px-2 text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                      active
                        ? "border-foreground/40 text-foreground"
                        : "border-border text-muted-foreground opacity-50 hover:opacity-80"
                    }`}
                    aria-pressed={active}
                    aria-label={`${active ? "Hide" : "Show"} ${type} edges`}
                    title={active ? `Hide ${type} edges` : `Show ${type} edges`}
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-sm"
                      style={{
                        backgroundColor:
                          REL_COLORS[type] ?? "hsl(var(--muted-foreground))",
                      }}
                    />
                    {type}
                  </button>
                );
              })}
              {/* Graph ↔ table. The graph shows shape; the table answers
                  "rank these" — which the force layout is bad at. */}
              <div
                role="radiogroup"
                aria-label="View mode"
                className="ml-auto inline-flex rounded-md border border-border bg-muted/40 p-0.5"
              >
                {(
                  [
                    { key: "graph", label: "Graph", Icon: Network },
                    { key: "table", label: "Table", Icon: TableIcon },
                  ] as const
                ).map(({ key, label, Icon }) => {
                  const active = viewMode === key;
                  return (
                    <button
                      key={key}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      onClick={() => setViewMode(key)}
                      className={`inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                        active
                          ? "bg-background text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                      {label}
                    </button>
                  );
                })}
              </div>
              <div className="inline-flex rounded-md border border-border bg-muted/40 p-0.5">
                <button
                  type="button"
                  onClick={() => setHops(1)}
                  className={`inline-flex min-h-11 cursor-pointer items-center rounded px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                    hops === 1
                      ? "bg-background text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  title="Show only directly-connected (tier-1) companies"
                >
                  Tier 1
                </button>
                <button
                  type="button"
                  onClick={() => setHops(2)}
                  className={`inline-flex min-h-11 cursor-pointer items-center rounded px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                    hops === 2
                      ? "bg-background text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  title="Also include tier-2 — the connections of the connected companies"
                >
                  Tier 2
                </button>
              </div>
              {seedTicker ? (
                <span className="ml-2 text-[11px] text-muted-foreground">
                  <span className="font-mono text-foreground">
                    {seedTicker}
                  </span>
                  {" · "}
                  {visibleGraph.nodes.length}N · {visibleGraph.edges.length}E
                  {truncated ? " (capped)" : ""}
                </span>
              ) : null}
            </div>
          </div>

          {error ? (
            <p role="alert" className="px-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}

          <div
            className={fillViewport ? "relative flex-1 min-h-0" : "relative"}
          >
            {/* Opens only. The drawer closes via its own X, so this no longer
                needs a "Hide" state — as a toggle it rendered directly on top
                of that X at the same corner. Hidden in table mode, where a
                relationship is opened by clicking it and a floating button
                would just cover the table headers. */}
            {viewMode === "graph" && !isDrawerOpen ? (
              <button
                type="button"
                data-tour="relations-edges"
                onClick={() => setIsDrawerOpen(true)}
                className="absolute right-3 top-3 z-40 inline-flex min-h-11 cursor-pointer items-center rounded-md border border-border bg-background px-3 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                Details
              </button>
            ) : null}
            <div
              ref={containerRef}
              data-tour="relations-graph"
              className={`${
                fillViewport
                  ? "relative z-0 isolate h-full overflow-hidden bg-card"
                  : "relative z-0 isolate overflow-hidden rounded-xl bg-card"
              } ${
                // The panel is an overlay. Over a force graph that's fine — the
                // interesting nodes are centred and reflowing would re-run the
                // simulation and move everything. Over a table it just hides
                // columns, so the table gets out of its way instead.
                // Mobile keeps the overlay: the panel is a bottom sheet there.
                viewMode === "table" && isDrawerOpen
                  ? "transition-[padding] duration-200 sm:pr-[30rem]"
                  : "transition-[padding] duration-200"
              }`}
            >
              {viewMode === "graph" ? (
                <NetworkGraphD3
                  width={GW}
                  height={GH}
                  nodeRadius={NODE_R}
                  relColors={REL_COLORS}
                  nodes={visibleGraph.nodes}
                  edges={visibleGraph.edges}
                  allEdges={edges}
                  selectedNode={selectedNode}
                  selectedEdge={selectedEdge}
                  connectedSet={connectedSet}
                  dimDistantGraph={false}
                  manualPositions={manualPositions}
                  onManualPositionsMerge={onManualPositionsMerge}
                  onNodeClick={onGraphNodeClick}
                  onNodeDoubleClick={onGraphNodeDoubleClick}
                  onEdgeClick={onGraphEdgeClick}
                  onEdgeDoubleClick={onGraphEdgeDoubleClick}
                  onSvgBackgroundDoubleClick={onGraphSvgBackgroundDoubleClick}
                />
              ) : (
                <RelationshipTableView
                  edges={visibleGraph.edges}
                  relTypes={REL_TYPES.filter((t) => selectedRelTypes.includes(t))}
                  relColors={REL_COLORS}
                  seedTicker={seedTicker}
                  focusTicker={tableFocus ?? seedTicker}
                  selectedEdge={selectedEdge}
                  onSelectNode={onTableFocusNode}
                  onSelectEdge={onTableEdgeSelect}
                />
              )}
            </div>

            {isDrawerOpen ? (
              <>
                {/* Mobile backdrop — tap to close */}
                <div
                  className="sm:hidden fixed inset-0 z-20 bg-black/40"
                  onClick={() => setIsDrawerOpen(false)}
                />
              <div className="fixed sm:absolute bottom-0 left-0 right-0 sm:bottom-auto sm:left-auto sm:right-0 sm:top-0 max-h-[65dvh] sm:max-h-none sm:h-full w-full sm:max-w-[30rem] rounded-t-2xl sm:rounded-none border-t border-border sm:border-t-0 sm:border-l z-30 overflow-y-auto bg-background/95 p-2 backdrop-blur-sm">
                {/* Drag handle — mobile only */}
                <div className="sm:hidden flex justify-center pt-1 pb-2">
                  <div className="w-8 h-1 rounded-full bg-border" />
                </div>
                {/* The drawer owns its own dismissal — it used to be closable
                    only via the floating toggle outside it, which table mode
                    doesn't render. */}
                <div className="flex items-start justify-between gap-2">
                {/* A real tablist. These were four bare <button>s switching a
                    panel with no role/aria-selected, so assistive tech had no
                    idea they were a set or which one was active. */}
                <div
                  role="tablist"
                  aria-label="Selection details"
                  className="inline-flex w-fit flex-wrap items-center gap-1 rounded-md bg-muted/60 p-1"
                >
                  {SIDE_TABS.map((tab) => {
                    const active = sideTab === tab.key;
                    return (
                      <button
                        key={tab.key}
                        type="button"
                        role="tab"
                        id={`reltab-${tab.key}`}
                        aria-selected={active}
                        aria-controls="reltabpanel"
                        onClick={() => setSideTab(tab.key)}
                        className={`inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                          active
                            ? "bg-background text-foreground"
                            : "text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {tab.label}
                      </button>
                    );
                  })}
                </div>
                  <button
                    type="button"
                    onClick={() => setIsDrawerOpen(false)}
                    className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    aria-label="Close details panel"
                  >
                    <X className="h-4 w-4" aria-hidden />
                  </button>
                </div>

                <div
                  role="tabpanel"
                  id="reltabpanel"
                  aria-labelledby={`reltab-${sideTab}`}
                >
                {sideTab === "vectors" ? (
                  <div className="p-2">
                    {!selectedNode ? (
                      <p className="text-sm text-muted-foreground">
                        Select a node to view its dimension vectors.
                      </p>
                    ) : (
                      <VectorsUI
                        tickers={selectedNodeVectors}
                        count={selectedNodeVectors.length}
                      />
                    )}
                  </div>
                ) : sideTab === "sentiment" ? (
                  <div className="p-2">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Ticker Sentiment
                      </p>
                      {selectedNode ? (
                        <Pager
                          label="ticker sentiment"
                          page={sentimentPage}
                          setPage={setSentimentPage}
                          rowCount={sentimentRows.length}
                          disabled={sentimentLoading}
                        />
                      ) : null}
                    </div>
                    <div className="mt-2 max-h-[36rem] overflow-auto">
                      {selectedNode && !sentimentLoading && !sentimentError ? (
                        <div className="grid grid-cols-2 gap-2 border-b border-border p-2 md:grid-cols-4">
                          {[10, 21, 50, 200].map((days) => {
                            const bucket = sentimentWindows.find(
                              (w) => w.days === days,
                            );
                            const score =
                              bucket?.weighted_sentiment ??
                              bucket?.avg_sentiment ??
                              null;
                            const toneClass =
                              score == null
                                ? "text-muted-foreground"
                                : score > 0
                                  ? "text-emerald-500"
                                  : score < 0
                                    ? "text-rose-500"
                                    : "text-muted-foreground";
                            return (
                              <div
                                key={`sent-window-${days}`}
                                className="bg-background/60 px-2 py-1.5"
                              >
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                  {days}D
                                </p>
                                <p
                                  className={`mt-0.5 font-mono text-sm font-semibold ${toneClass}`}
                                >
                                  {score == null
                                    ? "—"
                                    : `${score > 0 ? "+" : ""}${score.toFixed(2)}`}
                                </p>
                                <p className="text-[11px] text-muted-foreground">
                                  {bucket?.mention_count ?? 0} mentions
                                </p>
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                      {!selectedNode ? (
                        <p className="p-2 text-xs text-muted-foreground">
                          Select a node to load ticker sentiment.
                        </p>
                      ) : sentimentLoading ? (
                        <p className="p-2 text-xs text-muted-foreground">
                          Loading sentiment…
                        </p>
                      ) : sentimentError ? (
                        <div className="p-2">
                          <SectionError raw={sentimentError} />
                        </div>
                      ) : sentimentRows.length === 0 ? (
                        <p className="p-2 text-xs text-muted-foreground">
                          No sentiment rows found for{" "}
                          <span className="font-mono">{selectedNode}</span>.
                        </p>
                      ) : (
                        <div className="divide-y divide-border">
                          {sentimentRows.map((row) => (
                            <div
                              key={`${row.head_id}-${row.article_id}-${row.ticker}`}
                              className="p-2"
                            >
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs font-semibold">
                                  {row.ticker}
                                </span>
                                <span
                                  className={`text-xs font-semibold ${
                                    row.sentiment_score > 0
                                      ? "text-emerald-500"
                                      : row.sentiment_score < 0
                                        ? "text-rose-500"
                                        : "text-muted-foreground"
                                  }`}
                                >
                                  {row.sentiment_score > 0 ? "+" : ""}
                                  {row.sentiment_score.toFixed(2)}
                                </span>
                                <span className="text-[11px] text-muted-foreground">
                                  conf{" "}
                                  {row.confidence == null
                                    ? "—"
                                    : row.confidence.toFixed(2)}
                                </span>
                              </div>
                              <a
                                href={row.article_url ?? "#"}
                                target="_blank"
                                rel="noreferrer"
                                className="mt-1 block text-xs font-medium text-foreground hover:underline"
                              >
                                {row.article_title ??
                                  `Article #${row.article_id}`}
                              </a>
                              <p className="mt-0.5 text-[11px] text-muted-foreground">
                                {row.article_ts
                                  ? new Date(row.article_ts).toLocaleString()
                                  : "Unknown date"}
                                {row.article_source
                                  ? ` · ${row.article_source}`
                                  : ""}
                                {row.article_publisher
                                  ? ` · ${row.article_publisher}`
                                  : ""}
                              </p>
                              {row.reasoning_text ? (
                                <p className="mt-1 text-[11px] text-muted-foreground line-clamp-3">
                                  {row.reasoning_text}
                                </p>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-5 p-2">
                    {!selectedNode && !selectedEdge ? (
                      <p className="text-sm text-muted-foreground">
                        Pick a company or one of its relationships to see how the
                        link was worked out, the articles behind it, and the
                        latest news.
                      </p>
                    ) : null}

                    {/* 1 — what the link actually says, and where it came from. */}
                    {selectedEdge ? (
                      <RelationshipExplainer
                        edge={selectedEdge}
                        detail={selectedEdgeDetail}
                      />
                    ) : null}

                    {/* 2 — the receipts. */}
                    {selectedEdge ? (
                      <GraphDetailsEdgeEvidence
                        selectedEdge={selectedEdge}
                        evidencePage={evidencePage}
                        setEvidencePage={setEvidencePage}
                        evidenceRows={evidenceRows}
                        loading={evidenceLoading}
                        listMaxClass="max-h-[min(30rem,50vh)]"
                      />
                    ) : null}

                    {/* 3 — what is being said about the company right now. */}
                    {selectedNode ? (
                      <section className="flex flex-col gap-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <SectionHeading>
                            Latest news about{" "}
                            <span className="font-mono">{selectedNode}</span>
                          </SectionHeading>
                          <Pager
                            label={`news about ${selectedNode}`}
                            page={nodeNewsPage}
                            setPage={setNodeNewsPage}
                            rowCount={nodeNewsRows.length}
                            disabled={nodeNewsLoading}
                          />
                        </div>
                        <div className="max-h-[min(24rem,44vh)] overflow-auto">
                          {nodeNewsLoading ? (
                            <p className="text-xs text-muted-foreground">
                              Loading news…
                            </p>
                          ) : nodeNewsError ? (
                            <SectionError raw={nodeNewsError} />
                          ) : nodeNewsRows.length === 0 ? (
                            <p className="text-xs text-muted-foreground">
                              No recent articles mention{" "}
                              <span className="font-mono">{selectedNode}</span>.
                            </p>
                          ) : (
                            <ol className="divide-y divide-border">
                              {nodeNewsRows.map((row) => (
                                <li
                                  key={`${row.article_id}-${row.matched_ticker}`}
                                  className="py-2"
                                >
                                  <a
                                    href={row.url ?? "#"}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-xs font-medium text-foreground hover:underline"
                                  >
                                    {row.title ?? `Article #${row.article_id}`}
                                  </a>
                                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                                    {row.published_at
                                      ? new Date(row.published_at).toLocaleDateString(
                                          "en-GB",
                                          {
                                            year: "numeric",
                                            month: "short",
                                            day: "2-digit",
                                          },
                                        )
                                      : "Date unknown"}
                                    {row.source ? ` · ${row.source}` : ""}
                                  </p>
                                </li>
                              ))}
                            </ol>
                          )}
                        </div>
                      </section>
                    ) : null}

                    {/* Supporting context, deliberately below the three things
                        the user came for. */}
                    {selectedEdge ? (
                      <details className="group border-t border-border pt-3">
                        <summary className="flex min-h-9 cursor-pointer list-none items-center gap-1.5 text-sm font-semibold tracking-tight">
                          <ChevronRight
                            className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90"
                            aria-hidden
                          />
                          Do their share prices actually track each other?
                        </summary>
                        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                          A relationship in the news does not guarantee the two
                          stocks move together. This is the statistical check on
                          whether they historically have — and whether they are
                          unusually far apart right now.
                        </p>
                        <div className="mt-2">
                          <PairCointegrationPanel
                            pairStat={pairStat}
                            loading={pairStatLoading}
                          />
                        </div>
                      </details>
                    ) : null}

                    {selectedNode ? (
                      <details className="group border-t border-border pt-3">
                        <summary className="flex min-h-9 cursor-pointer list-none items-center gap-1.5 text-sm font-semibold tracking-tight">
                          <ChevronRight
                            className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90"
                            aria-hidden
                          />
                          Its other relationships ({nodeConnections.length})
                        </summary>
                        <p className="mt-2 text-xs text-muted-foreground">
                          Pick one to see how that link was established.
                        </p>
                        <ul className="mt-2 max-h-44 divide-y divide-border overflow-auto">
                          {nodeConnections.slice(0, 20).map((c, idx) => (
                            <li key={`${c.peer}-${c.rel_type}-${idx}`}>
                              <button
                                type="button"
                                onClick={() =>
                                  setSelectedEdge({
                                    from_ticker: c.from_ticker,
                                    to_ticker: c.to_ticker,
                                    rel_type: c.rel_type,
                                  })
                                }
                                className="flex min-h-11 w-full cursor-pointer items-center justify-between gap-2 px-1 text-left text-xs transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
                              >
                                <span className="font-mono font-medium">
                                  {c.peer}
                                </span>
                                <span className="text-muted-foreground">
                                  {c.rel_type} ·{" "}
                                  <span className="tabular-nums">
                                    {(c.strength_avg * 100).toFixed(0)}%
                                  </span>
                                </span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}

                    {selectedNode && aliases.length > 0 ? (
                      <details className="group border-t border-border pt-3">
                        <summary className="flex min-h-9 cursor-pointer list-none items-center gap-1.5 text-sm font-semibold tracking-tight">
                          <ChevronRight
                            className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90"
                            aria-hidden
                          />
                          Other names it appears under
                        </summary>
                        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                          Articles rarely use the ticker. These are the names
                          matched to{" "}
                          <span className="font-mono">{selectedNode}</span> when
                          reading coverage.
                        </p>
                        <ul className="mt-2 flex flex-wrap gap-1.5">
                          {aliases.slice(0, 12).map((a, idx) => (
                            <li
                              key={`${a.alias_kind}-${a.alias_value}-${idx}`}
                              className="rounded-full border border-border px-2 py-0.5 text-[11px]"
                              title={
                                a.verified
                                  ? `${a.alias_kind}, verified`
                                  : `${a.alias_kind}, not verified`
                              }
                            >
                              {a.alias_value}
                              {a.verified ? null : (
                                <span className="text-muted-foreground"> ?</span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                )}
                </div>{/* end tabpanel */}
              </div>{/* end panel */}
            </>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
