"use client";

import { useEffect, useRef } from "react";
import { drag, type D3DragEvent, select, zoom, zoomIdentity } from "d3";
import type { RelationshipEdge } from "@/app/actions/relationships";
import { createGraphForceSimulation, type GraphForceNode } from "./d3-force-layout";

export type SelectedEdge = { from_ticker: string; to_ticker: string; rel_type?: string } | null;

const EDGE_ARROW_MARKER_ID = "swingtrader-rel-edge-arrow";

function directedEdgeEndpoints(
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  nodeR: number,
): { x1: number; y1: number; x2: number; y2: number } {
  const dx = toX - fromX;
  const dy = toY - fromY;
  const len = Math.hypot(dx, dy);
  if (!Number.isFinite(len) || len < 1e-6) {
    return { x1: fromX, y1: fromY, x2: toX, y2: toY };
  }
  const ux = dx / len;
  const uy = dy / len;
  const tailInset = nodeR + 1;
  const headInset = nodeR + 10;
  if (len < tailInset + headInset + 2) {
    const half = Math.max(2, (len - 2) / 2);
    return {
      x1: fromX + ux * half,
      y1: fromY + uy * half,
      x2: toX - ux * half,
      y2: toY - uy * half,
    };
  }
  return {
    x1: fromX + ux * tailInset,
    y1: fromY + uy * tailInset,
    x2: toX - ux * headInset,
    y2: toY - uy * headInset,
  };
}

export type NetworkGraphD3Props = {
  width: number;
  height: number;
  nodeRadius: number;
  relColors: Record<string, string>;
  nodes: string[];
  edges: RelationshipEdge[];
  allEdges: RelationshipEdge[];
  selectedNode: string | null;
  selectedEdge: SelectedEdge;
  connectedSet: Set<string>;
  /** When false, node/link opacity ignores neighborhood dimming (full-graph view). */
  dimDistantGraph: boolean;
  manualPositions: Record<string, { x: number; y: number }>;
  onManualPositionsMerge: (patch: Record<string, { x: number; y: number }>) => void;
  onNodeClick: (node: string) => void;
  onNodeDoubleClick: (node: string) => void;
  onEdgeClick: (edge: { from_ticker: string; to_ticker: string; rel_type: string }) => void;
  onEdgeDoubleClick: (edge: { from_ticker: string; to_ticker: string; rel_type: string }) => void;
  onSvgBackgroundDoubleClick: () => void;
};

export function NetworkGraphD3({
  width: GW,
  height: GH,
  nodeRadius: NODE_R,
  relColors: REL_COLORS,
  nodes: nodeIds,
  edges: visibleEdges,
  allEdges,
  selectedNode,
  selectedEdge,
  connectedSet,
  dimDistantGraph,
  manualPositions,
  onManualPositionsMerge,
  onNodeClick,
  onNodeDoubleClick,
  onEdgeClick,
  onEdgeDoubleClick,
  onSvgBackgroundDoubleClick,
}: NetworkGraphD3Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;

    const svg = select(el);
    svg.selectAll("*").remove();

    svg
      .append("defs")
      .append("marker")
      .attr("id", EDGE_ARROW_MARKER_ID)
      .attr("viewBox", "0 -4 10 8")
      .attr("refX", 9)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-3.25L9,0L0,3.25z")
      .attr("fill", "currentColor");

    const layoutEdges = visibleEdges.map((e) => ({
      from: e.from_ticker,
      to: e.to_ticker,
      strength: e.strength_avg,
    }));

    // Seed layout from manual positions on graph (re)build only — omit `manualPositions` from effect
    // deps so drag-merge does not tear down the SVG and reset d3-zoom (felt like "zoom in" after drop).
    const force = createGraphForceSimulation(GW, GH, NODE_R, nodeIds, layoutEdges, manualPositions);

    if (!force) {
      return;
    }

    const { simulation, nodes: simNodes } = force;
    const byId = new Map(simNodes.map((n) => [n.id, n]));

    const viewport = svg.append("g").attr("class", "viewport");

    viewport.append("rect").attr("x", 0).attr("y", 0).attr("width", GW).attr("height", GH).attr("fill", "transparent").style("cursor", "grab");

    const linkLayer = viewport.append("g").attr("class", "links");
    const nodeLayer = viewport.append("g").attr("class", "nodes");

    function edgeStroke(d: RelationshipEdge) {
      return REL_COLORS[d.rel_type] ?? "hsl(var(--muted-foreground))";
    }

    const linkSel = linkLayer
      .selectAll<SVGLineElement, RelationshipEdge>("line.link")
      .data(visibleEdges, (d) => `${d.from_ticker}|${d.to_ticker}|${d.rel_type}`)
      .join("line")
      .attr("class", "link cursor-pointer")
      .attr("stroke", (d) => edgeStroke(d))
      .style("color", (d) => edgeStroke(d))
      .attr("marker-end", `url(#${EDGE_ARROW_MARKER_ID})`)
      .attr("stroke-width", (d) => 1 + d.strength_avg * 3)
      .on("click", (event, d) => {
        event.stopPropagation();
        onEdgeClick({
          from_ticker: d.from_ticker,
          to_ticker: d.to_ticker,
          rel_type: d.rel_type,
        });
      })
      .on("dblclick", (event, d) => {
        event.stopPropagation();
        onEdgeDoubleClick({
          from_ticker: d.from_ticker,
          to_ticker: d.to_ticker,
          rel_type: d.rel_type,
        });
      });

    function linkOpacity(d: RelationshipEdge) {
      const isSelected =
        selectedEdge &&
        selectedEdge.from_ticker === d.from_ticker &&
        selectedEdge.to_ticker === d.to_ticker &&
        selectedEdge.rel_type === d.rel_type;
      if (selectedEdge) return isSelected ? 1 : 0.08;
      if (!dimDistantGraph) return 0.45;
      const isFocused =
        selectedNode && (d.from_ticker === selectedNode || d.to_ticker === selectedNode);
      if (isFocused) return 0.85;
      if (selectedNode) return 0.12;
      return 0.45;
    }

    function syncLinks() {
      linkSel.each(function (d) {
        const fx = byId.get(d.from_ticker)?.x ?? 0;
        const fy = byId.get(d.from_ticker)?.y ?? 0;
        const tx = byId.get(d.to_ticker)?.x ?? 0;
        const ty = byId.get(d.to_ticker)?.y ?? 0;
        const { x1, y1, x2, y2 } = directedEdgeEndpoints(fx, fy, tx, ty, NODE_R);
        select<SVGLineElement, RelationshipEdge>(this)
          .attr("x1", x1)
          .attr("y1", y1)
          .attr("x2", x2)
          .attr("y2", y2)
          .attr("stroke-opacity", linkOpacity(d));
      });
    }

    const nodeSel = nodeLayer
      .selectAll<SVGGElement, GraphForceNode>("g.node")
      .data(simNodes, (d) => d.id)
      .join("g")
      .attr("class", "node cursor-pointer")
      .attr("transform", (d) => `translate(${d.x},${d.y})`)
      .style("opacity", (d) => {
        if (selectedEdge) {
          const isEndpoint =
            d.id === selectedEdge.from_ticker || d.id === selectedEdge.to_ticker;
          return isEndpoint ? 1 : 0.2;
        }
        if (!dimDistantGraph) return 1;
        if (!selectedNode) return 1;
        if (d.id === selectedNode) return 1;
        if (connectedSet.has(d.id)) return 1;
        return 0.3;
      });

    nodeSel
      .append("circle")
      .attr("r", NODE_R)
      .attr("fill", (d) => {
        const edgeFocused =
          selectedEdge &&
          (d.id === selectedEdge.from_ticker || d.id === selectedEdge.to_ticker);
        if (edgeFocused || d.id === selectedNode) return "hsl(var(--foreground))";
        return "hsl(var(--muted))";
      })
      .attr("stroke", "hsl(var(--border))");

    nodeSel
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", (d) => (d.id.length > 4 ? 8 : 9))
      .attr("font-weight", 700)
      .attr("font-family", "monospace")
      .attr("fill", (d) => {
        const edgeFocused =
          selectedEdge &&
          (d.id === selectedEdge.from_ticker || d.id === selectedEdge.to_ticker);
        if (edgeFocused || d.id === selectedNode) return "hsl(var(--background))";
        return "hsl(var(--foreground))";
      })
      .attr("class", "select-none pointer-events-none")
      .text((d) => d.id);

    function updateNodePositions() {
      nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
      syncLinks();
    }

    syncLinks();

    let dragMoved = false;
    let dragGroupIds: string[] = [];

    const dragBehavior = drag<SVGGElement, GraphForceNode>()
      .on("start", (event, d) => {
        simulation.stop();
        dragMoved = false;
        const connected = new Set<string>([d.id]);
        for (const edge of allEdges) {
          if (edge.from_ticker === d.id) connected.add(edge.to_ticker);
          if (edge.to_ticker === d.id) connected.add(edge.from_ticker);
        }
        dragGroupIds = Array.from(connected);
        select<SVGGElement, GraphForceNode>(event.sourceEvent?.currentTarget as SVGGElement).raise();
      })
      .on("drag", (event: D3DragEvent<SVGGElement, GraphForceNode, GraphForceNode>, d) => {
        if (Math.abs(event.dx) + Math.abs(event.dy) > 0) dragMoved = true;
        for (const id of dragGroupIds) {
          const n = byId.get(id);
          if (!n) continue;
          const x = n.x ?? GW / 2;
          const y = n.y ?? GH / 2;
          n.x = x + event.dx;
          n.y = y + event.dy;
        }
        updateNodePositions();
      })
      .on("end", (_event, d) => {
        if (dragMoved) {
          const patch: Record<string, { x: number; y: number }> = {};
          for (const id of dragGroupIds) {
            const n = byId.get(id);
            if (n) patch[id] = { x: n.x ?? GW / 2, y: n.y ?? GH / 2 };
          }
          onManualPositionsMerge(patch);
        } else {
          onNodeClick(d.id);
        }
      });

    nodeSel.call(dragBehavior);

    simulation.on("tick", () => {
      updateNodePositions();
    });

    simulation.alpha(1).restart();

    nodeSel.on("dblclick", (event, d) => {
      event.stopPropagation();
      onNodeDoubleClick(d.id);
    });

    const zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.4, 4])
      .filter((event) => {
        const t = event.target as Element | null;
        if (t?.closest?.(".node")) return false;
        return (!event.ctrlKey || event.type === "wheel") && !event.button;
      })
      .on("zoom", (event) => {
        viewport.attr("transform", event.transform.toString());
      });

    svg.call(zoomBehavior).call(zoomBehavior.transform, zoomIdentity);
    // Keep pan/wheel zoom; avoid capturing double-click (used to close drawer / match prior SVG UX).
    svg.on("dblclick.zoom", null);

    function onSvgDblClick(event: MouseEvent) {
      const t = event.target as Element | null;
      if (t?.closest?.(".node")) return;
      if (t?.closest?.("line.link")) return;
      onSvgBackgroundDoubleClick();
    }
    el.addEventListener("dblclick", onSvgDblClick);

    return () => {
      simulation.on("tick", null);
      simulation.stop();
      el.removeEventListener("dblclick", onSvgDblClick);
      svg.on(".zoom", null);
      svg.on("dblclick.zoom", null);
      nodeSel.on("dblclick", null);
      nodeSel.on(".drag", null);
    };
  }, [
    GW,
    GH,
    NODE_R,
    REL_COLORS,
    nodeIds.join("|"),
    visibleEdges.map((e) => `${e.from_ticker}|${e.to_ticker}|${e.rel_type}|${e.strength_avg}`).join(";"),
    allEdges.map((e) => `${e.from_ticker}|${e.to_ticker}|${e.rel_type}`).join(";"),
    selectedNode,
    selectedEdge
      ? `${selectedEdge.from_ticker}|${selectedEdge.to_ticker}|${selectedEdge.rel_type ?? ""}`
      : "",
    [...connectedSet].sort().join("|"),
    dimDistantGraph,
    onManualPositionsMerge,
    onNodeClick,
    onNodeDoubleClick,
    onEdgeClick,
    onEdgeDoubleClick,
    onSvgBackgroundDoubleClick,
  ]);

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${GW} ${GH}`}
      overflow="visible"
      className="w-full touch-none overflow-visible"
      role="img"
      aria-label="Ticker relationship network graph"
    />
  );
}
