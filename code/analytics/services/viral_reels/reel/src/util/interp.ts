import {Keyframe} from '../types';

export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/**
 * A 0 -> 1 -> 0 attention "bump" over [startF, peakF, endF] (in frames). Used to
 * fire a discrete spotlight beat early in the reel that catches the viewer,
 * without altering the animation's natural pace.
 */
export const bump = (frame: number, startF: number, peakF: number, endF: number): number => {
  if (frame <= startF || frame >= endF) return 0;
  if (frame < peakF) return easeOutCubic((frame - startF) / (peakF - startF));
  return 1 - easeInOutCubic((frame - peakF) / (endF - peakF));
};

export interface EntityState {
  id: string;
  label: string;
  value: number;
  rank: number; // 0 = leader; fractional during transitions
}

interface PreparedKeyframe {
  valueById: Map<string, number>;
  rankById: Map<string, number>;
  labelById: Map<string, string>;
  ids: string[];
}

/**
 * Pre-compute value + rank lookups per keyframe. Ranks are assigned by sorting
 * entries by value descending — interpolating rank (not just value) between
 * keyframes gives the buttery overtakes the bar-chart-race format is known for.
 */
export const prepareKeyframes = (keyframes: Keyframe[]): PreparedKeyframe[] => {
  return keyframes.map((kf) => {
    const valueById = new Map<string, number>();
    const labelById = new Map<string, string>();
    for (const e of kf.entries) {
      valueById.set(e.id, e.value);
      labelById.set(e.id, e.label);
    }
    const sorted = [...kf.entries].sort((a, b) => b.value - a.value);
    const rankById = new Map<string, number>();
    sorted.forEach((e, i) => rankById.set(e.id, i));
    return {valueById, rankById, labelById, ids: sorted.map((e) => e.id)};
  });
};

/**
 * State of every entity at a continuous progress p ∈ [0, K-1].
 * Returns entities sorted by interpolated rank (leader first).
 */
export const stateAtProgress = (
  prepared: PreparedKeyframe[],
  allIds: string[],
  labelById: Map<string, string>,
  p: number,
): EntityState[] => {
  const K = prepared.length;
  const pc = clamp(p, 0, K - 1);
  const i = Math.min(Math.floor(pc), K - 2);
  const frac = pc - i;
  const a = prepared[i];
  const b = prepared[Math.min(i + 1, K - 1)];

  const states = allIds.map((id) => {
    const va = a.valueById.get(id) ?? 0;
    const vb = b.valueById.get(id) ?? va;
    const ra = a.rankById.get(id) ?? allIds.length;
    const rb = b.rankById.get(id) ?? ra;
    return {
      id,
      label: labelById.get(id) ?? id,
      value: lerp(va, vb, frac),
      rank: lerp(ra, rb, frac),
    };
  });
  states.sort((x, y) => x.rank - y.rank);
  return states;
};

/** All entity ids that ever appear, in a stable order (by first keyframe rank). */
export const collectIds = (prepared: PreparedKeyframe[]): string[] => {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const kf of prepared) {
    for (const id of kf.ids) {
      if (!seen.has(id)) {
        seen.add(id);
        order.push(id);
      }
    }
  }
  return order;
};

export const labelMap = (keyframes: Keyframe[]): Map<string, string> => {
  const m = new Map<string, string>();
  for (const kf of keyframes) {
    for (const e of kf.entries) m.set(e.id, e.label);
  }
  return m;
};
