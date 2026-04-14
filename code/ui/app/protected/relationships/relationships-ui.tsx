"use client";

import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import {
  relationshipsGetAliases,
  relationshipsGetAliasesBulk,
  relationshipsGetEdgeEvidence,
  relationshipsGetNeighborhood,
  relationshipsGetNodeNews,
  relationshipsGetNodeSentiment,
  relationshipsResolveTicker,
  type AliasRow,
  type AliasMap,
  type EdgeEvidence,
  type NodeNewsRow,
  type NodeSentimentRow,
  type NodeSentimentWindow,
  type RelationshipEdge,
} from "@/app/actions/relationships";
import { fmpGetCompanyProfile, type FmpCompanyProfile } from "@/app/actions/fmp";
import { TickerSearchCombobox } from "@/components/ticker-search-combobox";
import { VectorsUI, type TickerRow } from "../vectors/vectors-ui";
import { NetworkGraphD3 } from "./network-graph-d3";

const REL_COLORS: Record<string, string> = {
  competitor: "hsl(var(--chart-3))",
  supplier: "hsl(var(--chart-2))",
  customer: "hsl(var(--chart-1))",
  partner: "hsl(var(--chart-4))",
  acquirer: "hsl(var(--chart-5))",
  subsidiary: "hsl(var(--primary))",
};

const REL_TYPES = ["competitor", "supplier", "customer", "partner", "acquirer", "subsidiary"] as const;

const GW = 980;
const GH = 560;
const NODE_R = 18;

type SelectedEdge = { from_ticker: string; to_ticker: string; rel_type?: string } | null;

function GraphDetailsEdgeEvidence({
  selectedEdge,
  evidencePage,
  setEvidencePage,
  evidenceRows,
  listMaxClass,
}: {
  selectedEdge: SelectedEdge;
  evidencePage: number;
  setEvidencePage: Dispatch<SetStateAction<number>>;
  evidenceRows: EdgeEvidence[];
  listMaxClass: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Edge Evidence</p>
        {selectedEdge ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setEvidencePage((p) => Math.max(1, p - 1))}
              className="rounded border border-border px-2 py-0.5 text-xs"
            >
              Prev
            </button>
            <span className="text-xs text-muted-foreground">{evidencePage}</span>
            <button
              type="button"
              onClick={() => setEvidencePage((p) => p + 1)}
              className="rounded border border-border px-2 py-0.5 text-xs"
            >
              Next
            </button>
          </div>
        ) : null}
      </div>
      <div className={`mt-1 overflow-auto ${listMaxClass}`}>
        {evidenceRows.length === 0 ? (
          <p className="p-2 text-xs text-muted-foreground">Select an edge to load article provenance.</p>
        ) : (
          <div className="divide-y divide-border">
            {evidenceRows.map((row) => (
              <div key={`${row.edge_id}-${row.article_id}`} className="p-2">
                <a
                  href={row.article_url ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs font-medium text-foreground hover:underline"
                >
                  {row.article_title ?? `Article #${row.article_id}`}
                </a>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {row.published_at ? new Date(row.published_at).toLocaleString() : "Unknown date"} · confidence{" "}
                  {row.head_confidence == null ? "—" : row.head_confidence.toFixed(2)}
                </p>
                {row.reasoning_text ? (
                  <p className="mt-1 text-[11px] text-muted-foreground line-clamp-3">{row.reasoning_text}</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function formatCompactNumber(n: number | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function formatFixed(n: number | undefined, digits: number): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function RelationshipsUI({ vectors = [] }: { vectors?: TickerRow[] }) {
  const FIXED_MIN_STRENGTH = 0.25;
  const FIXED_MIN_MENTIONS = 1;
  const [sideTab, setSideTab] = useState<"overview" | "details" | "vectors" | "sentiment">("overview");
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [seedInput, setSeedInput] = useState("AAPL");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seedTicker, setSeedTicker] = useState<string>("");
  const [edges, setEdges] = useState<RelationshipEdge[]>([]);
  const [nodes, setNodes] = useState<string[]>([]);
  const [truncated, setTruncated] = useState(false);

  const [hops] = useState<2>(2);
  /** Full graph vs 2-hop subgraph around the selected node (requires a selected node). */
  const [graphScope, setGraphScope] = useState<"full" | "twoHop">("full");
  const [selectedRelTypes, setSelectedRelTypes] = useState<string[]>([...REL_TYPES]);

  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<SelectedEdge>(null);
  const [aliases, setAliases] = useState<AliasRow[]>([]);
  const [aliasesByNode, setAliasesByNode] = useState<AliasMap>({});
  const [nodeNewsRows, setNodeNewsRows] = useState<NodeNewsRow[]>([]);
  const [nodeNewsPage, setNodeNewsPage] = useState(1);
  const [nodeNewsLoading, setNodeNewsLoading] = useState(false);
  const [nodeNewsError, setNodeNewsError] = useState<string | null>(null);
  const [sentimentRows, setSentimentRows] = useState<NodeSentimentRow[]>([]);
  const [sentimentWindows, setSentimentWindows] = useState<NodeSentimentWindow[]>([]);
  const [sentimentPage, setSentimentPage] = useState(1);
  const [sentimentLoading, setSentimentLoading] = useState(false);
  const [sentimentError, setSentimentError] = useState<string | null>(null);
  const [evidenceRows, setEvidenceRows] = useState<EdgeEvidence[]>([]);
  const [evidencePage, setEvidencePage] = useState(1);
  const [manualPositions, setManualPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [fmpProfile, setFmpProfile] = useState<FmpCompanyProfile | null>(null);
  const [fmpProfileLoading, setFmpProfileLoading] = useState(false);
  const [fmpProfileError, setFmpProfileError] = useState<string | null>(null);
  /** Ticker the current `fmpProfile` / `fmpProfileError` belongs to (after last completed request). */
  const [fmpProfileForTicker, setFmpProfileForTicker] = useState<string | null>(null);

  const fmpOverviewBusy = useMemo(
    () =>
      Boolean(
        selectedNode &&
          (fmpProfileLoading || fmpProfileForTicker?.toUpperCase() !== selectedNode.toUpperCase()),
      ),
    [fmpProfileLoading, fmpProfileForTicker, selectedNode],
  );

  const filteredEdges = useMemo(
    () => edges.filter((e) => selectedRelTypes.includes(e.rel_type)),
    [edges, selectedRelTypes],
  );

  const visibleGraph = useMemo(() => {
    // "Entire network": every node and every edge from the loaded neighborhood (ignore legend rel-type filters).
    const fullGraph = { nodes, edges };
    if (graphScope === "full" || !selectedNode) {
      return fullGraph;
    }
    const visited = new Set<string>([selectedNode]);
    const depth = new Map<string, number>([[selectedNode, 0]]);
    const queue: string[] = [selectedNode];
    while (queue.length > 0) {
      const current = queue.shift()!;
      const d = depth.get(current) ?? 0;
      if (d >= 2) continue;
      for (const edge of filteredEdges) {
        let next: string | null = null;
        if (edge.from_ticker === current) next = edge.to_ticker;
        else if (edge.to_ticker === current) next = edge.from_ticker;
        if (!next || visited.has(next)) continue;
        visited.add(next);
        depth.set(next, d + 1);
        queue.push(next);
      }
    }
    const visibleNodes = nodes.filter((n) => visited.has(n));
    const visibleEdges = filteredEdges.filter(
      (e) => visited.has(e.from_ticker) && visited.has(e.to_ticker),
    );
    return { nodes: visibleNodes, edges: visibleEdges };
  }, [edges, filteredEdges, graphScope, nodes, selectedNode]);

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
    const all = Array.from(base).filter(Boolean).sort((a, b) => a.localeCompare(b));
    if (!q) return all.slice(0, 20);
    const starts = all.filter((s) => s.startsWith(q));
    const contains = all.filter((s) => !s.startsWith(q) && s.includes(q));
    return [...starts, ...contains].slice(0, 20);
  }, [aliasesByNode, nodes, seedInput, seedTicker]);

  const nodeConnections = useMemo(() => {
    if (!selectedNode) return [];
    return visibleGraph.edges
      .filter((e) => e.from_ticker === selectedNode || e.to_ticker === selectedNode)
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

  const edgeFocusMode = Boolean(selectedEdge && !selectedNode);

  async function loadNeighborhood(resetSelection = true, seedOverride?: string) {
    setLoading(true);
    setError(null);
    const resolved = await relationshipsResolveTicker(seedOverride ?? seedInput);
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
      setSelectedNode(null);
      setSelectedEdge(null);
      setEvidenceRows([]);
      setEvidencePage(1);
      setNodeNewsRows([]);
      setNodeNewsPage(1);
      setSentimentRows([]);
      setSentimentPage(1);
    }
  }

  const expandAroundNode = useCallback(async (node: string) => {
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

    setNodes((prev) => Array.from(new Set([...prev, ...result.data.nodes])).sort());
    setEdges((prev) => {
      const byKey = new Map<string, RelationshipEdge>();
      for (const edge of prev) {
        byKey.set(`${edge.from_ticker}|${edge.to_ticker}|${edge.rel_type}`, edge);
      }
      for (const edge of result.data.edges) {
        byKey.set(`${edge.from_ticker}|${edge.to_ticker}|${edge.rel_type}`, edge);
      }
      return Array.from(byKey.values());
    });
    setTruncated((prev) => prev || result.data.truncated);
  }, [hops, selectedRelTypes]);

  const onManualPositionsMerge = useCallback((patch: Record<string, { x: number; y: number }>) => {
    setManualPositions((prev) => ({ ...prev, ...patch }));
  }, []);

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
      pageSize: 10,
    }).then((res) => {
      setNodeNewsLoading(false);
      if (!res.ok) {
        setNodeNewsError(res.error);
        setNodeNewsRows([]);
        return;
      }
      setNodeNewsRows(res.data.rows);
    }).catch((err) => {
      setNodeNewsLoading(false);
      setNodeNewsError(err instanceof Error ? err.message : "Failed to load node news");
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
      pageSize: 10,
    }).then((res) => {
      setSentimentLoading(false);
      if (!res.ok) {
        setSentimentError(res.error);
        setSentimentRows([]);
        setSentimentWindows([]);
        return;
      }
      setSentimentRows(res.data.rows);
      setSentimentWindows(res.data.windows);
    }).catch((err) => {
      setSentimentLoading(false);
      setSentimentError(err instanceof Error ? err.message : "Failed to load node sentiment");
      setSentimentRows([]);
      setSentimentWindows([]);
    });
  }, [selectedNode, sentimentPage]);

  useEffect(() => {
    if (!selectedEdge) return;
    relationshipsGetEdgeEvidence({
      fromTicker: selectedEdge.from_ticker,
      toTicker: selectedEdge.to_ticker,
      relType: selectedEdge.rel_type,
      page: evidencePage,
      pageSize: 10,
    }).then((res) => {
      if (!res.ok) return;
      setEvidenceRows(res.data.rows);
    });
  }, [selectedEdge, evidencePage]);

  useEffect(() => {
    if (!selectedNode) {
      setFmpProfile(null);
      setFmpProfileError(null);
      setFmpProfileLoading(false);
      setFmpProfileForTicker(null);
      return;
    }
    const ticker = selectedNode;
    let cancelled = false;
    setFmpProfileLoading(true);
    setFmpProfileError(null);
    fmpGetCompanyProfile(ticker).then((res) => {
      if (cancelled) return;
      setFmpProfileLoading(false);
      setFmpProfileForTicker(ticker);
      if (!res.ok) {
        setFmpProfile(null);
        setFmpProfileError(res.error);
        return;
      }
      setFmpProfile(res.data);
      setFmpProfileError(null);
    });
    return () => {
      cancelled = true;
    };
  }, [selectedNode]);

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
    <div className="flex flex-col gap-4">
      <div className="p-1">
        <div className="grid gap-3 md:grid-cols-6">
          <TickerSearchCombobox
            className="md:col-span-5"
            value={seedInput}
            onChange={setSeedInput}
            onSubmit={() => void loadNeighborhood(true)}
            options={searchSuggestions}
            placeholder="Search ticker or alias…"
          />
          <button
            onClick={() => void loadNeighborhood(true)}
            className="h-9 rounded-md border border-border bg-background px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted"
            disabled={loading}
          >
            {loading ? "Loading..." : "Explore"}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Edge legend</span>
          {REL_TYPES.map((type) => {
            const active = selectedRelTypes.includes(type);
            return (
              <button
                key={`legend-${type}`}
                type="button"
                onClick={(e) => {
                  // Ignore click handler when this is part of a double-click gesture.
                  if (e.detail > 1) return;
                  setSelectedRelTypes((prev) =>
                    active ? prev.filter((v) => v !== type) : [...prev, type],
                  );
                }}
                onDoubleClick={(e) => {
                  e.preventDefault();
                  setSelectedRelTypes([...REL_TYPES]);
                }}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition-colors ${
                  active
                    ? "border-foreground text-foreground"
                    : "border-border text-muted-foreground opacity-60 hover:opacity-100"
                }`}
                title={active ? `Hide ${type} edges` : `Show ${type} edges`}
              >
                <span
                  className="h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: REL_COLORS[type] ?? "hsl(var(--muted-foreground))" }}
                />
                <span>{type}</span>
              </button>
            );
          })}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Graph</span>
          <div className="inline-flex rounded-md border border-border bg-muted/40 p-0.5">
            <button
              type="button"
              onClick={() => setGraphScope("full")}
              className={`rounded px-2.5 py-1 text-[11px] font-medium transition-colors ${
                graphScope === "full"
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              title="Show every node and every edge in the loaded neighborhood (edge-type legend does not hide edges)"
            >
              Entire network
            </button>
            <button
              type="button"
              onClick={() => setGraphScope("twoHop")}
              className={`rounded px-2.5 py-1 text-[11px] font-medium transition-colors ${
                graphScope === "twoHop"
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              title={
                selectedNode
                  ? "Show only nodes within 2 hops of the selected node"
                  : "Select a node on the graph, then use this to show a 2-hop neighborhood"
              }
            >
              2-hop neighbors
            </button>
          </div>
        </div>
        {seedTicker && (
          <p className="mt-2 text-xs text-muted-foreground">
            Seed: <span className="font-mono text-foreground">{seedTicker}</span> · Nodes {visibleGraph.nodes.length} · Edges{" "}
            {visibleGraph.edges.length}
            {truncated ? " (capped)" : ""}
            {graphScope === "twoHop" && !selectedNode ? " · 2-hop view needs a selected node — showing full graph" : ""}
          </p>
        )}
      </div>

      {error ? <p className="text-sm text-rose-500">{error}</p> : null}

      <div className="relative">
        <button
          type="button"
          onClick={() => setIsDrawerOpen((prev) => !prev)}
          className="absolute right-3 top-3 z-40 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
        >
          {isDrawerOpen ? "Hide Panel" : "Show Panel"}
        </button>
        <div className="relative z-0 isolate overflow-hidden rounded-xl bg-card">
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
            dimDistantGraph={graphScope === "twoHop" && Boolean(selectedNode) && !selectedEdge}
            manualPositions={manualPositions}
            onManualPositionsMerge={onManualPositionsMerge}
            onNodeClick={onGraphNodeClick}
            onNodeDoubleClick={onGraphNodeDoubleClick}
            onEdgeClick={onGraphEdgeClick}
            onEdgeDoubleClick={onGraphEdgeDoubleClick}
            onSvgBackgroundDoubleClick={onGraphSvgBackgroundDoubleClick}
          />
        </div>

        {isDrawerOpen ? (
          <div className="absolute right-0 top-0 z-30 h-full w-full max-w-[30rem] overflow-y-auto border-l border-border bg-background/95 p-2 backdrop-blur-sm">
          <div className="inline-flex w-fit flex-wrap items-center gap-1 rounded-md bg-muted/60 p-1">
            <button
              type="button"
              onClick={() => setSideTab("overview")}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                sideTab === "overview"
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Basic info
              {selectedNode && fmpOverviewBusy ? (
                <span
                  className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-muted-foreground/80"
                  aria-hidden
                />
              ) : null}
            </button>
            <button
              type="button"
              onClick={() => setSideTab("details")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                sideTab === "details"
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Graph Details
            </button>
            <button
              type="button"
              onClick={() => setSideTab("vectors")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                sideTab === "vectors"
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Company Profile
            </button>
            <button
              type="button"
              onClick={() => setSideTab("sentiment")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                sideTab === "sentiment"
                  ? "bg-background text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Sentiment
            </button>
          </div>

          {sideTab === "overview" ? (
            <div className="p-2">
              {!selectedNode ? (
                <p className="text-sm text-muted-foreground">Select a node to load company profile from Financial Modeling Prep.</p>
              ) : fmpOverviewBusy ? (
                <div className="flex flex-col gap-3" aria-busy="true" aria-live="polite">
                  <p className="text-xs text-muted-foreground">
                    Loading profile for <span className="font-mono text-foreground">{selectedNode}</span>…
                  </p>
                  <div className="flex gap-3 border-b border-border pb-3">
                    <div className="h-12 w-12 shrink-0 animate-pulse rounded-md bg-muted" />
                    <div className="min-w-0 flex-1 space-y-2 py-0.5">
                      <div className="h-4 w-[min(100%,14rem)] animate-pulse rounded bg-muted" />
                      <div className="h-3 w-24 animate-pulse rounded bg-muted" />
                      <div className="h-3 w-16 animate-pulse rounded bg-muted" />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {Array.from({ length: 10 }).map((_, i) => (
                      <div key={`sk-${i}`} className="h-3 animate-pulse rounded bg-muted/80" />
                    ))}
                  </div>
                </div>
              ) : fmpProfileError ? (
                <p className="text-xs text-rose-500">{fmpProfileError}</p>
              ) : fmpProfile ? (
                <div className="flex flex-col gap-3">
                  <div className="flex gap-3 border-b border-border pb-3">
                    {fmpProfile.image ? (
                      <img
                        src={fmpProfile.image}
                        alt=""
                        width={48}
                        height={48}
                        className="h-12 w-12 shrink-0 rounded-md border border-border bg-muted object-contain"
                      />
                    ) : (
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-border bg-muted font-mono text-xs font-semibold text-muted-foreground">
                        {(fmpProfile.symbol ?? selectedNode).slice(0, 4)}
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold leading-tight text-foreground">
                        {fmpProfile.companyName ?? selectedNode}
                      </p>
                      <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                        {fmpProfile.symbol ?? selectedNode}
                        {fmpProfile.exchange ? ` · ${fmpProfile.exchange}` : ""}
                      </p>
                      {fmpProfile.website ? (
                        <a
                          href={fmpProfile.website}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 inline-block truncate text-xs font-medium text-foreground hover:underline"
                        >
                          Website
                        </a>
                      ) : null}
                    </div>
                  </div>

                  <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-x-2 gap-y-1.5 text-xs">
                    <dt className="text-muted-foreground">Price</dt>
                    <dd className="text-right font-mono tabular-nums">
                      {fmpProfile.price != null && Number.isFinite(fmpProfile.price)
                        ? `${formatFixed(fmpProfile.price, 2)}${fmpProfile.currency ? ` ${fmpProfile.currency}` : ""}`
                        : "—"}
                    </dd>
                    <dt className="text-muted-foreground">Change</dt>
                    <dd
                      className={`text-right font-mono tabular-nums ${
                        (fmpProfile.change ?? 0) > 0
                          ? "text-emerald-600"
                          : (fmpProfile.change ?? 0) < 0
                            ? "text-rose-600"
                            : ""
                      }`}
                    >
                      {fmpProfile.change != null && Number.isFinite(fmpProfile.change)
                        ? `${fmpProfile.change > 0 ? "+" : ""}${formatFixed(fmpProfile.change, 2)}`
                        : "—"}
                      {fmpProfile.changePercentage != null && Number.isFinite(fmpProfile.changePercentage)
                        ? ` (${fmpProfile.changePercentage > 0 ? "+" : ""}${formatFixed(fmpProfile.changePercentage, 2)}%)`
                        : ""}
                    </dd>
                    <dt className="text-muted-foreground">Market cap</dt>
                    <dd className="text-right font-mono tabular-nums">{formatCompactNumber(fmpProfile.marketCap)}</dd>
                    <dt className="text-muted-foreground">52W range</dt>
                    <dd className="text-right font-mono text-[11px] tabular-nums">{fmpProfile.range ?? "—"}</dd>
                    <dt className="text-muted-foreground">Beta</dt>
                    <dd className="text-right font-mono tabular-nums">{formatFixed(fmpProfile.beta, 3)}</dd>
                    <dt className="text-muted-foreground">Volume</dt>
                    <dd className="text-right font-mono tabular-nums">{formatCompactNumber(fmpProfile.volume)}</dd>
                    <dt className="text-muted-foreground">Avg volume</dt>
                    <dd className="text-right font-mono tabular-nums">{formatCompactNumber(fmpProfile.averageVolume)}</dd>
                    <dt className="text-muted-foreground">Last dividend</dt>
                    <dd className="text-right font-mono tabular-nums">{formatFixed(fmpProfile.lastDividend, 2)}</dd>
                    <dt className="text-muted-foreground">Sector</dt>
                    <dd className="text-right">{fmpProfile.sector ?? "—"}</dd>
                    <dt className="text-muted-foreground">Industry</dt>
                    <dd className="text-right">{fmpProfile.industry ?? "—"}</dd>
                    <dt className="text-muted-foreground">CEO</dt>
                    <dd className="text-right">{fmpProfile.ceo ?? "—"}</dd>
                    <dt className="text-muted-foreground">Employees</dt>
                    <dd className="text-right tabular-nums">{fmpProfile.fullTimeEmployees ?? "—"}</dd>
                    <dt className="text-muted-foreground">IPO</dt>
                    <dd className="text-right font-mono text-[11px]">{fmpProfile.ipoDate ?? "—"}</dd>
                    <dt className="text-muted-foreground">Country</dt>
                    <dd className="text-right">{fmpProfile.country ?? "—"}</dd>
                    <dt className="text-muted-foreground">Exchange</dt>
                    <dd className="text-right text-[11px] leading-snug">{fmpProfile.exchangeFullName ?? fmpProfile.exchange ?? "—"}</dd>
                    <dt className="text-muted-foreground">CIK / ISIN</dt>
                    <dd className="break-all text-right font-mono text-[10px]">
                      {[fmpProfile.cik, fmpProfile.isin].filter(Boolean).join(" · ") || "—"}
                    </dd>
                  </dl>

                  {(fmpProfile.address || fmpProfile.city || fmpProfile.phone) ? (
                    <div className="border-t border-border pt-2 text-xs text-muted-foreground">
                      {fmpProfile.address ? <p>{fmpProfile.address}</p> : null}
                      {(fmpProfile.city || fmpProfile.state || fmpProfile.zip) ? (
                        <p>
                          {[fmpProfile.city, fmpProfile.state, fmpProfile.zip].filter(Boolean).join(", ")}
                        </p>
                      ) : null}
                      {fmpProfile.phone ? <p className="mt-1 font-mono">{fmpProfile.phone}</p> : null}
                    </div>
                  ) : null}

                  <div className="flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
                    {fmpProfile.isEtf ? <span className="rounded border border-border px-1.5 py-0.5">ETF</span> : null}
                    {fmpProfile.isFund ? <span className="rounded border border-border px-1.5 py-0.5">Fund</span> : null}
                    {fmpProfile.isAdr ? <span className="rounded border border-border px-1.5 py-0.5">ADR</span> : null}
                    {fmpProfile.isActivelyTrading === false ? (
                      <span className="rounded border border-amber-500/50 px-1.5 py-0.5 text-amber-700 dark:text-amber-400">
                        Not actively trading
                      </span>
                    ) : null}
                  </div>

                  {fmpProfile.description ? (
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Description</p>
                      <p className="mt-1 max-h-48 overflow-y-auto text-xs leading-relaxed text-muted-foreground">
                        {fmpProfile.description}
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No profile returned for this symbol.</p>
              )}
            </div>
          ) : sideTab === "vectors" ? (
            <div className="p-2">
              {!selectedNode ? (
                <p className="text-sm text-muted-foreground">
                  Select a node to view company profile for that ticker.
                </p>
              ) : (
                <VectorsUI tickers={selectedNodeVectors} count={selectedNodeVectors.length} />
              )}
            </div>
          ) : sideTab === "sentiment" ? (
            <div className="p-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Ticker Sentiment</p>
                {selectedNode ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setSentimentPage((p) => Math.max(1, p - 1))}
                      className="rounded border border-border px-2 py-0.5 text-xs"
                    >
                      Prev
                    </button>
                    <span className="text-xs text-muted-foreground">{sentimentPage}</span>
                    <button
                      onClick={() => setSentimentPage((p) => p + 1)}
                      className="rounded border border-border px-2 py-0.5 text-xs"
                    >
                      Next
                    </button>
                  </div>
                ) : null}
              </div>
              <div className="mt-2 max-h-[36rem] overflow-auto">
                {selectedNode && !sentimentLoading && !sentimentError ? (
                  <div className="grid grid-cols-2 gap-2 border-b border-border p-2 md:grid-cols-4">
                    {[10, 21, 50, 200].map((days) => {
                      const bucket = sentimentWindows.find((w) => w.days === days);
                      const score = bucket?.weighted_sentiment ?? bucket?.avg_sentiment ?? null;
                      const toneClass =
                        score == null
                          ? "text-muted-foreground"
                          : score > 0
                            ? "text-emerald-500"
                            : score < 0
                              ? "text-rose-500"
                              : "text-muted-foreground";
                      return (
                        <div key={`sent-window-${days}`} className="bg-background/60 px-2 py-1.5">
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{days}D</p>
                          <p className={`mt-0.5 font-mono text-sm font-semibold ${toneClass}`}>
                            {score == null ? "—" : `${score > 0 ? "+" : ""}${score.toFixed(2)}`}
                          </p>
                          <p className="text-[10px] text-muted-foreground">
                            {bucket?.mention_count ?? 0} mentions
                          </p>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
                {!selectedNode ? (
                  <p className="p-2 text-xs text-muted-foreground">Select a node to load ticker sentiment.</p>
                ) : sentimentLoading ? (
                  <p className="p-2 text-xs text-muted-foreground">Loading sentiment…</p>
                ) : sentimentError ? (
                  <p className="p-2 text-xs text-rose-500">{sentimentError}</p>
                ) : sentimentRows.length === 0 ? (
                  <p className="p-2 text-xs text-muted-foreground">
                    No sentiment rows found for <span className="font-mono">{selectedNode}</span>.
                  </p>
                ) : (
                  <div className="divide-y divide-border">
                    {sentimentRows.map((row) => (
                      <div key={`${row.head_id}-${row.article_id}-${row.ticker}`} className="p-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-semibold">{row.ticker}</span>
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
                            conf {row.confidence == null ? "—" : row.confidence.toFixed(2)}
                          </span>
                        </div>
                        <a
                          href={row.article_url ?? "#"}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 block text-xs font-medium text-foreground hover:underline"
                        >
                          {row.article_title ?? `Article #${row.article_id}`}
                        </a>
                        <p className="mt-0.5 text-[11px] text-muted-foreground">
                          {row.article_ts ? new Date(row.article_ts).toLocaleString() : "Unknown date"}
                          {row.article_source ? ` · ${row.article_source}` : ""}
                          {row.article_publisher ? ` · ${row.article_publisher}` : ""}
                        </p>
                        {row.reasoning_text ? (
                          <p className="mt-1 text-[11px] text-muted-foreground line-clamp-3">{row.reasoning_text}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="p-2 flex flex-col gap-3">
              <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Selection</p>
            {selectedNode ? (
              <p className="mt-1 text-sm">
                Node: <span className="font-mono font-semibold">{selectedNode}</span>
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">Select a node or edge</p>
            )}
            {selectedNode && (aliasesByNode[selectedNode]?.length ?? 0) > 0 ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Aliases: <span className="font-mono">{aliasesByNode[selectedNode]!.slice(0, 6).join(", ")}</span>
              </p>
            ) : null}
            {selectedEdge ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Edge:{" "}
                <span className="font-mono">
                  {selectedEdge.from_ticker} → {selectedEdge.to_ticker} ({selectedEdge.rel_type})
                </span>
              </p>
            ) : null}
          </div>

              {edgeFocusMode ? (
                <GraphDetailsEdgeEvidence
                  selectedEdge={selectedEdge}
                  evidencePage={evidencePage}
                  setEvidencePage={setEvidencePage}
                  evidenceRows={evidenceRows}
                  listMaxClass="max-h-[min(38rem,76vh)]"
                />
              ) : null}

              {!edgeFocusMode ? (
              <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Aliases</p>
            {aliases.length === 0 ? (
              <p className="mt-1 text-xs text-muted-foreground">No aliases loaded</p>
            ) : (
              <div className="mt-1 max-h-32 overflow-auto">
                <table className="w-full text-xs">
                  <tbody className="divide-y divide-border">
                    {aliases.slice(0, 12).map((a, idx) => (
                      <tr key={`${a.alias_kind}-${a.alias_value}-${idx}`}>
                        <td className="px-2 py-1.5 font-mono">{a.alias_value}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{a.alias_kind}</td>
                        <td className="px-2 py-1.5 text-right">{a.verified ? "verified" : "unverified"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
              ) : null}

              {!edgeFocusMode ? (
              <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Connections ({nodeConnections.length})
            </p>
            <div className="mt-1 max-h-36 overflow-auto">
              <table className="w-full text-xs">
                <tbody className="divide-y divide-border">
                  {nodeConnections.slice(0, 20).flatMap((c, idx) => {
                    const aliasList = aliasesByNode[c.peer] ?? [];
                    const rows: React.ReactNode[] = [
                      <tr
                        key={`${c.peer}-${c.rel_type}-${idx}`}
                        className="cursor-pointer hover:bg-muted/40"
                        onClick={() =>
                          setSelectedEdge({
                            from_ticker: c.from_ticker,
                            to_ticker: c.to_ticker,
                            rel_type: c.rel_type,
                          })
                        }
                      >
                        <td className="px-2 py-1.5 font-mono">{c.peer}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{c.rel_type}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{(c.strength_avg * 100).toFixed(0)}%</td>
                      </tr>,
                    ];
                    if (aliasList.length > 0) {
                      rows.push(
                        <tr key={`${c.peer}-aliases-${idx}`} className="bg-muted/20">
                          <td colSpan={3} className="px-2 py-1 text-[10px] text-muted-foreground">
                            {c.peer} aliases: <span className="font-mono">{aliasList.slice(0, 4).join(", ")}</span>
                          </td>
                        </tr>,
                      );
                    }
                    return rows;
                  })}
                </tbody>
              </table>
            </div>
          </div>
              ) : null}

              {!edgeFocusMode ? (
              <div>
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Node News</p>
              {selectedNode ? (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setNodeNewsPage((p) => Math.max(1, p - 1))}
                    className="rounded border border-border px-2 py-0.5 text-xs"
                  >
                    Prev
                  </button>
                  <span className="text-xs text-muted-foreground">{nodeNewsPage}</span>
                  <button
                    onClick={() => setNodeNewsPage((p) => p + 1)}
                    className="rounded border border-border px-2 py-0.5 text-xs"
                  >
                    Next
                  </button>
                </div>
              ) : null}
            </div>
            <div className="mt-1 max-h-44 overflow-auto">
              {!selectedNode ? (
                <p className="p-2 text-xs text-muted-foreground">
                  Select a node to load related news.
                </p>
              ) : nodeNewsLoading ? (
                <p className="p-2 text-xs text-muted-foreground">Loading node news…</p>
              ) : nodeNewsError ? (
                <p className="p-2 text-xs text-rose-500">{nodeNewsError}</p>
              ) : nodeNewsRows.length === 0 ? (
                <p className="p-2 text-xs text-muted-foreground">
                  No related news found for <span className="font-mono">{selectedNode}</span>.
                </p>
              ) : (
                <div className="divide-y divide-border">
                  {nodeNewsRows.map((row) => (
                    <div key={`${row.article_id}-${row.matched_ticker}`} className="p-2">
                      <a
                        href={row.url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-medium text-foreground hover:underline"
                      >
                        {row.title ?? `Article #${row.article_id}`}
                      </a>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {row.published_at ? new Date(row.published_at).toLocaleString() : "Unknown date"} · matched{" "}
                        <span className="font-mono">{row.matched_ticker}</span>
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
              ) : null}

              {!edgeFocusMode ? (
                <GraphDetailsEdgeEvidence
                  selectedEdge={selectedEdge}
                  evidencePage={evidencePage}
                  setEvidencePage={setEvidencePage}
                  evidenceRows={evidenceRows}
                  listMaxClass="max-h-48"
                />
              ) : null}
            </div>
          )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
