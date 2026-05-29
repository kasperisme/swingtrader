// Mirror of the Python ReelSpec in services/viral_reels/spec.py — keep in sync.

export type ValueFormat = 'count' | 'score' | 'percent' | 'currency' | 'signed';

export interface ReelFormat {
  width: number;
  height: number;
  fps: number;
  durationInSeconds: number;
}

export interface IntroSpec {
  kicker?: string;
  title: string;
  subtitle?: string;
  durationInSeconds: number;
}

export interface OutroSpec {
  title: string;
  takeaway?: string;
  cta?: string;
  durationInSeconds: number;
}

export interface RaceEntry {
  id: string;
  label: string;
  value: number;
}

export interface Keyframe {
  t: string; // ISO date
  label: string; // human label, e.g. "May 15"
  entries: RaceEntry[];
}

export interface RaceSpec {
  metricLabel: string;
  valueFormat: ValueFormat;
  barsVisible: number;
  keyframes: Keyframe[];
}

export interface PricePoint {
  t: string;
  close: number;
}

export interface PriceSparkOverlay {
  type: 'priceSpark';
  ticker: string;
  label: string;
  points: PricePoint[];
}

export type Overlay = PriceSparkOverlay | null;

export interface Caption {
  atSeconds: number;
  text: string;
}

export interface ReelSpec {
  version: number;
  format: ReelFormat;
  theme: string;
  intro?: IntroSpec;
  race: RaceSpec;
  overlay?: Overlay;
  captions?: Caption[];
  outro?: OutroSpec;
  sources?: string[];
}

// Must be a `type` (not `interface`) so it satisfies Remotion's
// `Props extends Record<string, unknown>` constraint via the implicit index
// signature — an interface would fall back to Record<string, unknown> and break
// component inference in <Composition>.
export type BarChartRaceProps = {
  spec: ReelSpec;
};
