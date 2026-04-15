import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
} from "d3-force";
import type { Simulation, SimulationLinkDatum, SimulationNodeDatum } from "d3-force";

export type GraphLayoutEdge = { from: string; to: string; strength: number };

export type GraphForceNode = SimulationNodeDatum & { id: string };

type GraphLink = SimulationLinkDatum<GraphForceNode> & { strength: number };

/**
 * Builds a d3-force simulation (link + charge + center + collide).
 * Call `simulation.alpha(1).restart()` and listen to `"tick"` to animate the graph.
 * `initialPositions` seeds x/y (e.g. user drag); omitted nodes start on an outer ring.
 * Positions are not clamped to the viewport — nodes may extend past width/height.
 */
export function createGraphForceSimulation(
  width: number,
  height: number,
  nodeRadius: number,
  nodeIds: string[],
  edges: GraphLayoutEdge[],
  initialPositions: Record<string, { x: number; y: number }>,
): {
  simulation: Simulation<GraphForceNode, undefined>;
  nodes: GraphForceNode[];
} | null {
  if (nodeIds.length === 0) return null;

  const cx = width / 2;
  const cy = height / 2;
  // Start farther out so initial settle has less overlap pressure.
  const ring = Math.min(width, height) * 0.46;

  const nodes: GraphForceNode[] = nodeIds.map((id, i) => {
    const seed = initialPositions[id];
    if (seed && Number.isFinite(seed.x) && Number.isFinite(seed.y)) {
      return { id, x: seed.x, y: seed.y, vx: 0, vy: 0 };
    }
    const angle = (2 * Math.PI * i) / nodeIds.length - Math.PI / 2;
    const x = cx + ring * Math.cos(angle);
    const y = cy + ring * Math.sin(angle);
    return { id, x, y, vx: 0, vy: 0 };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));

  const links: GraphLink[] = edges
    .filter((e) => byId.has(e.from) && byId.has(e.to))
    .map((e) => ({
      source: e.from,
      target: e.to,
      strength: e.strength,
    }));

  const simulation = forceSimulation<GraphForceNode>(nodes)
    .force(
      "link",
      forceLink<GraphForceNode, GraphLink>(links)
        .id((d) => d.id)
        // Uniform target length improves visual consistency across the graph.
        .distance(180)
        .strength(0.38),
    )
    .force("charge", forceManyBody<GraphForceNode>().strength(-760))
    .force("center", forceCenter(cx, cy))
    .force("collide", forceCollide<GraphForceNode>(nodeRadius + 10))
    .velocityDecay(0.35)
    .alphaDecay(0.0228);

  return { simulation, nodes };
}

/**
 * One-shot layout (same forces as the live simulation, run to rest).
 */
export function runD3ForceLayout(
  width: number,
  height: number,
  nodeRadius: number,
  nodeIds: string[],
  edges: GraphLayoutEdge[],
): Record<string, { x: number; y: number }> {
  const created = createGraphForceSimulation(width, height, nodeRadius, nodeIds, edges, {});
  if (!created) return {};

  const { simulation, nodes } = created;
  simulation.alpha(1);
  for (let i = 0; i < 420; i += 1) {
    simulation.tick();
  }
  simulation.stop();

  const cx = width / 2;
  const cy = height / 2;

  const out: Record<string, { x: number; y: number }> = {};
  for (const n of nodes) {
    out[n.id] = { x: n.x ?? cx, y: n.y ?? cy };
  }
  return out;
}
