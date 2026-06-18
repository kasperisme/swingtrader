import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from "d3-force";
import type { Simulation, SimulationLinkDatum, SimulationNodeDatum } from "d3-force";

export type GraphLayoutEdge = { from: string; to: string; strength: number };

export type GraphForceNode = SimulationNodeDatum & { id: string };

/**
 * Per-node unit direction (relative to the anchor) for type-clustered layout:
 *   supplier  → (-1, 0) left   ·  customer   → (+1, 0) right
 *   partner   → (0, +1) below  ·  competitor → (0, -1) above   (SVG y points down)
 * Nodes absent from the map (and 2-hop nodes) get no directional pull.
 */
export type GraphNodeDirections = Record<string, { x: number; y: number }>;

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
  anchorId?: string | null,
  directions?: GraphNodeDirections,
): {
  simulation: Simulation<GraphForceNode, undefined>;
  nodes: GraphForceNode[];
} | null {
  if (nodeIds.length === 0) return null;

  const cx = width / 2;
  const cy = height / 2;
  // Start farther out so initial settle has less overlap pressure.
  const ring = Math.min(width, height) * 0.46;
  // Directional (type-clustered) layout: anchor pinned at center, neighbours pulled
  // to a side by edge type. Cluster offset ~ the link length so a clustered
  // neighbour's preferred spot agrees with its link to the anchor.
  const directional = Boolean(anchorId && directions && Object.keys(directions).length > 0);
  const R = Math.max(180, Math.min(320, Math.min(width, height) * 0.32));

  const nodes: GraphForceNode[] = nodeIds.map((id, i) => {
    const seed = initialPositions[id];
    let node: GraphForceNode;
    if (seed && Number.isFinite(seed.x) && Number.isFinite(seed.y)) {
      node = { id, x: seed.x, y: seed.y, vx: 0, vy: 0 };
    } else if (directional && directions?.[id]) {
      // Seed clustered nodes already in their quadrant so they settle cleanly.
      const d = directions[id];
      node = { id, x: cx + d.x * R, y: cy + d.y * R, vx: 0, vy: 0 };
    } else {
      const angle = (2 * Math.PI * i) / nodeIds.length - Math.PI / 2;
      node = { id, x: cx + ring * Math.cos(angle), y: cy + ring * Math.sin(angle), vx: 0, vy: 0 };
    }
    if (directional && id === anchorId) {
      // Pin the focused node at the center — relationships orbit it.
      node.x = cx; node.y = cy; node.fx = cx; node.fy = cy;
    }
    return node;
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
        .distance(directional ? R : 180)
        .strength(directional ? 0.18 : 0.38),
    )
    .force("charge", forceManyBody<GraphForceNode>().strength(directional ? -520 : -760))
    .force("collide", forceCollide<GraphForceNode>(nodeRadius + 10))
    .velocityDecay(0.35)
    .alphaDecay(0.0228);

  if (directional) {
    const targetX = (n: GraphForceNode) => cx + (directions?.[n.id]?.x ?? 0) * R;
    const targetY = (n: GraphForceNode) => cy + (directions?.[n.id]?.y ?? 0) * R;
    // Strong pull for type-clustered neighbours; a faint tether to centre for the
    // rest (2-hop / untyped) so they don't drift off but stay out of the clusters.
    const strength = (n: GraphForceNode) =>
      n.id === anchorId ? 0 : directions?.[n.id] ? 0.55 : 0.05;
    simulation
      .force("x", forceX<GraphForceNode>(targetX).strength(strength))
      .force("y", forceY<GraphForceNode>(targetY).strength(strength));
  } else {
    simulation.force("center", forceCenter(cx, cy));
  }

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
