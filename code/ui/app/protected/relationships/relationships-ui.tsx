"use client";

import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";
import {
  relationshipsGetAliases,
  relationshipsGetAliasesBulk,
  relationshipsGetEdgeEvidence,
  relationshipsGetNeighborhood,
  relationshipsGetNodeNews,
  relationshipsResolveTicker,
  type AliasRow,
  type AliasMap,
  type EdgeEvidence,
  type NodeNewsRow,
  type RelationshipEdge,
} from "@/app/actions/relationships";
import { TickerSearchCombobox } from "@/components/ticker-search-combobox";

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

function runForceLayout(
  nodeIds: string[],
  edges: Array<{ from: string; to: string; strength: number }>,
): Record<string, { x: number; y: number }> {
  if (nodeIds.length === 0) return {};
  const cx = GW / 2;
  const cy = GH / 2;
  const repulsion = 6400;
  const damping = 0.86;
  const springK = 0.03;
  const centerK = 0.01;
  const steps = 280;
  const radius = Math.min(GW, GH) * 0.34;
  const pos: Record<string, { x: number; y: number; vx: number; vy: number }> = {};

  nodeIds.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / nodeIds.length - Math.PI / 2;
    pos[id] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle), vx: 0, vy: 0 };
  });

  const validEdges = edges.filter((e) => pos[e.from] && pos[e.to]);
  for (let step = 0; step < steps; step += 1) {
    const cool = 1 - step / steps;
    for (let i = 0; i < nodeIds.length; i += 1) {
      for (let j = i + 1; j < nodeIds.length; j += 1) {
        const a = pos[nodeIds[i]!]!;
        const b = pos[nodeIds[j]!]!;
        const dx = a.x - b.x || 0.001;
        const dy = a.y - b.y || 0.001;
        const dist2 = Math.max(1, dx * dx + dy * dy);
        const dist = Math.sqrt(dist2);
        const f = repulsion / dist2;
        const fx = (dx / dist) * f;
        const fy = (dy / dist) * f;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }

    for (const e of validEdges) {
      const a = pos[e.from]!;
      const b = pos[e.to]!;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
      const rest = 90 + 80 * (1 - Math.max(0, Math.min(1, e.strength)));
      const disp = dist - rest;
      const f = springK * disp;
      const fx = (dx / dist) * f;
      const fy = (dy / dist) * f;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }

    for (const id of nodeIds) {
      const n = pos[id]!;
      n.vx += (cx - n.x) * centerK;
      n.vy += (cy - n.y) * centerK;
      n.vx *= damping;
      n.vy *= damping;
      n.x += n.vx * cool;
      n.y += n.vy * cool;
      n.x = Math.max(NODE_R + 6, Math.min(GW - NODE_R - 6, n.x));
      n.y = Math.max(NODE_R + 6, Math.min(GH - NODE_R - 6, n.y));
    }
  }

  return Object.fromEntries(nodeIds.map((id) => [id, { x: pos[id]!.x, y: pos[id]!.y }]));
}

export function RelationshipsUI() {
  const [seedInput, setSeedInput] = useState("AAPL");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seedTicker, setSeedTicker] = useState<string>("");
  const [edges, setEdges] = useState<RelationshipEdge[]>([]);
  const [nodes, setNodes] = useState<string[]>([]);
  const [truncated, setTruncated] = useState(false);

  const [hops] = useState<2>(2);
  const [minStrength, setMinStrength] = useState(0.35);
  const [minMentions, setMinMentions] = useState(1);
  const [daysLookback, setDaysLookback] = useState(30);
  const [selectedRelTypes, setSelectedRelTypes] = useState<string[]>([...REL_TYPES]);

  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<SelectedEdge>(null);
  const [aliases, setAliases] = useState<AliasRow[]>([]);
  const [aliasesByNode, setAliasesByNode] = useState<AliasMap>({});
  const [nodeNewsRows, setNodeNewsRows] = useState<NodeNewsRow[]>([]);
  const [nodeNewsPage, setNodeNewsPage] = useState(1);
  const [nodeNewsLoading, setNodeNewsLoading] = useState(false);
  const [nodeNewsError, setNodeNewsError] = useState<string | null>(null);
  const [evidenceRows, setEvidenceRows] = useState<EdgeEvidence[]>([]);
  const [evidencePage, setEvidencePage] = useState(1);
  const [draggingNode, setDraggingNode] = useState<string | null>(null);
  const [dragGroup, setDragGroup] = useState<string[]>([]);
  const [lastDragPoint, setLastDragPoint] = useState<{ x: number; y: number } | null>(null);
  const [manualPositions, setManualPositions] = useState<Record<string, { x: number; y: number }>>({});

  const filteredEdges = useMemo(
    () => edges.filter((e) => selectedRelTypes.includes(e.rel_type)),
    [edges, selectedRelTypes],
  );

  const visibleGraph = useMemo(() => {
    if (!selectedNode) return { nodes, edges };
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
  }, [filteredEdges, nodes, selectedNode]);

  const basePositions = useMemo(
    () =>
      runForceLayout(
        visibleGraph.nodes,
        visibleGraph.edges.map((e) => ({
          from: e.from_ticker,
          to: e.to_ticker,
          strength: e.strength_avg,
        })),
      ),
    [visibleGraph.nodes, visibleGraph.edges],
  );
  const positions = useMemo(
    () => ({ ...basePositions, ...manualPositions }),
    [basePositions, manualPositions],
  );

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
      minStrength,
      minMentions,
      relTypes: selectedRelTypes,
      daysLookback,
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
      setSelectedNode(result.data.seedTicker);
      setSelectedEdge(null);
      setEvidenceRows([]);
      setEvidencePage(1);
      setNodeNewsRows([]);
      setNodeNewsPage(1);
    }
  }

  async function expandAroundNode(node: string) {
    const result = await relationshipsGetNeighborhood({
      seedTicker: node,
      hops,
      minStrength,
      minMentions,
      relTypes: selectedRelTypes,
      daysLookback,
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
  }

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
      daysLookback,
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
  }, [selectedNode, nodeNewsPage, daysLookback]);

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
    setManualPositions((prev) => {
      const next: Record<string, { x: number; y: number }> = {};
      for (const id of nodes) {
        if (prev[id]) next[id] = prev[id]!;
      }
      return next;
    });
  }, [nodes]);

  function toSvgCoords(event: ReactMouseEvent<SVGSVGElement>) {
    const svg = event.currentTarget;
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * GW;
    const y = ((event.clientY - rect.top) / rect.height) * GH;
    return { x, y };
  }

  function clampNodePosition(x: number, y: number) {
    return {
      x: Math.max(NODE_R + 6, Math.min(GW - NODE_R - 6, x)),
      y: Math.max(NODE_R + 6, Math.min(GH - NODE_R - 6, y)),
    };
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-border bg-card/60 p-3">
        <div className="grid gap-3 md:grid-cols-6">
          <TickerSearchCombobox
            className="md:col-span-2"
            value={seedInput}
            onChange={setSeedInput}
            onSubmit={() => void loadNeighborhood(true)}
            options={searchSuggestions}
            placeholder="Search ticker or alias…"
          />
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={minStrength}
            onChange={(e) => setMinStrength(Math.max(0, Math.min(1, Number(e.target.value) || 0)))}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            title="Min strength"
          />
          <input
            type="number"
            min="1"
            value={minMentions}
            onChange={(e) => setMinMentions(Math.max(1, Number(e.target.value) || 1))}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            title="Min mentions"
          />
          <button
            onClick={() => void loadNeighborhood(true)}
            className="h-9 rounded-md bg-foreground px-3 text-sm font-medium text-background"
            disabled={loading}
          >
            {loading ? "Loading..." : "Explore"}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            type="number"
            min="1"
            value={daysLookback}
            onChange={(e) => setDaysLookback(Math.max(1, Number(e.target.value) || 1))}
            className="ml-auto h-8 w-28 rounded-md border border-input bg-background px-2 text-xs"
            title="Days lookback"
          />
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
        {seedTicker && (
          <p className="mt-2 text-xs text-muted-foreground">
            Seed: <span className="font-mono text-foreground">{seedTicker}</span> · Nodes {visibleGraph.nodes.length} · Edges{" "}
            {visibleGraph.edges.length}
            {truncated ? " (capped)" : ""}
          </p>
        )}
      </div>

      {error ? <p className="text-sm text-rose-500">{error}</p> : null}

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <svg
            viewBox={`0 0 ${GW} ${GH}`}
            className="w-full"
            onMouseMove={(e) => {
              if (!draggingNode || !lastDragPoint) return;
              const p = toSvgCoords(e);
              const dx = p.x - lastDragPoint.x;
              const dy = p.y - lastDragPoint.y;
              setLastDragPoint(p);
              setManualPositions((prev) => {
                const next = { ...prev };
                for (const nodeId of dragGroup) {
                  const current = prev[nodeId] ?? positions[nodeId];
                  if (!current) continue;
                  next[nodeId] = clampNodePosition(current.x + dx, current.y + dy);
                }
                return next;
              });
            }}
            onMouseUp={() => {
              setDraggingNode(null);
              setDragGroup([]);
              setLastDragPoint(null);
            }}
            onMouseLeave={() => {
              setDraggingNode(null);
              setDragGroup([]);
              setLastDragPoint(null);
            }}
          >
            {visibleGraph.edges.map((edge, idx) => {
              const p0 = positions[edge.from_ticker];
              const p1 = positions[edge.to_ticker];
              if (!p0 || !p1) return null;
              const isSelected =
                selectedEdge &&
                selectedEdge.from_ticker === edge.from_ticker &&
                selectedEdge.to_ticker === edge.to_ticker &&
                selectedEdge.rel_type === edge.rel_type;
              const isFocused =
                selectedNode && (edge.from_ticker === selectedNode || edge.to_ticker === selectedNode);
              return (
                <line
                  key={`${edge.from_ticker}-${edge.to_ticker}-${edge.rel_type}-${idx}`}
                  x1={p0.x}
                  y1={p0.y}
                  x2={p1.x}
                  y2={p1.y}
                  stroke={REL_COLORS[edge.rel_type] ?? "hsl(var(--muted-foreground))"}
                  strokeWidth={1 + edge.strength_avg * 3}
                  strokeOpacity={isSelected ? 1 : isFocused ? 0.85 : selectedNode ? 0.12 : 0.45}
                  className="cursor-pointer"
                  onClick={() => {
                    setSelectedEdge({
                      from_ticker: edge.from_ticker,
                      to_ticker: edge.to_ticker,
                      rel_type: edge.rel_type,
                    });
                    setEvidencePage(1);
                  }}
                />
              );
            })}
            {visibleGraph.nodes.map((node) => {
              const p = positions[node];
              if (!p) return null;
              const isSelected = node === selectedNode;
              const isConnected = connectedSet.has(node);
              const dimmed = selectedNode && !isSelected && !isConnected;
              return (
                <g
                  key={node}
                  transform={`translate(${p.x},${p.y})`}
                  className="cursor-pointer"
                  style={{ opacity: dimmed ? 0.3 : 1 }}
                  onMouseDown={(e) => {
                    e.stopPropagation();
                    setDraggingNode(node);
                    const connected = new Set<string>([node]);
                    for (const edge of edges) {
                      if (edge.from_ticker === node) connected.add(edge.to_ticker);
                      if (edge.to_ticker === node) connected.add(edge.from_ticker);
                    }
                    setDragGroup(Array.from(connected));
                    // capture initial pointer point for delta-based group dragging
                    const svg = (e.currentTarget.ownerSVGElement ?? e.currentTarget.closest("svg")) as SVGSVGElement | null;
                    if (svg) {
                      const rect = svg.getBoundingClientRect();
                      setLastDragPoint({
                        x: ((e.clientX - rect.left) / rect.width) * GW,
                        y: ((e.clientY - rect.top) / rect.height) * GH,
                      });
                    }
                  }}
                  onClick={() => void (async () => {
                    setSelectedNode(node);
                    setSelectedEdge(null);
                    setEvidenceRows([]);
                    setNodeNewsPage(1);
                    // Keep current graph and append neighborhood from clicked node.
                    await expandAroundNode(node);
                  })()}
                >
                  <circle
                    r={NODE_R}
                    fill={isSelected ? "hsl(var(--foreground))" : "hsl(var(--muted))"}
                    stroke="hsl(var(--border))"
                  />
                  <text
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={node.length > 4 ? 8 : 9}
                    fontWeight="700"
                    fontFamily="monospace"
                    fill={isSelected ? "hsl(var(--background))" : "hsl(var(--foreground))"}
                    className="select-none pointer-events-none"
                  >
                    {node}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        <div className="rounded-xl border border-border bg-card p-3 flex flex-col gap-3">
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

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Aliases</p>
            {aliases.length === 0 ? (
              <p className="mt-1 text-xs text-muted-foreground">No aliases loaded</p>
            ) : (
              <div className="mt-1 max-h-32 overflow-auto rounded-md border border-border">
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

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Connections ({nodeConnections.length})
            </p>
            <div className="mt-1 max-h-36 overflow-auto rounded-md border border-border">
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
            <div className="mt-1 max-h-44 overflow-auto rounded-md border border-border">
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
                  No related news found for <span className="font-mono">{selectedNode}</span> in the current lookback window.
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

          <div>
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Edge Evidence</p>
              {selectedEdge ? (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setEvidencePage((p) => Math.max(1, p - 1))}
                    className="rounded border border-border px-2 py-0.5 text-xs"
                  >
                    Prev
                  </button>
                  <span className="text-xs text-muted-foreground">{evidencePage}</span>
                  <button
                    onClick={() => setEvidencePage((p) => p + 1)}
                    className="rounded border border-border px-2 py-0.5 text-xs"
                  >
                    Next
                  </button>
                </div>
              ) : null}
            </div>
            <div className="mt-1 max-h-48 overflow-auto rounded-md border border-border">
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
        </div>
      </div>
    </div>
  );
}
