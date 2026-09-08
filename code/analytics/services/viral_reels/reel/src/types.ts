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

export interface HeadlineItem {
  articleId?: number; // source news_articles.id (traceability; not rendered)
  title: string;
  source?: string; // shown uppercased, e.g. "REUTERS.COM" or the raw URL
  url?: string;
  publishedAt?: string; // ISO; used to derive age if `age` absent
  age?: string; // pre-baked relative age, e.g. "2h ago"
  imageUrl?: string; // optional thumbnail
}

export interface ReelSpec {
  version: number;
  format: ReelFormat;
  theme: string;
  intro?: IntroSpec;
  race: RaceSpec;
  overlay?: Overlay;
  captions?: Caption[];
  headlines?: HeadlineItem[];
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

// ---------------------------------------------------------------------------
// Format 2: Price + News — an animated OHLC candlestick chart with news events
// plotted on it, to show whether headlines moved the stock.
// ---------------------------------------------------------------------------

export interface OHLCPoint {
  t: string; // ISO date
  close: number;
  open?: number;
  high?: number;
  low?: number;
}

export interface NewsEvent {
  t: string; // ISO date the news hit (snaps to the nearest price point)
  articleId?: number; // source news_articles.id (traceability; not rendered)
  title: string;
  source?: string;
  url?: string;
  imageUrl?: string;
  sentiment?: number; // -1..1; colours the marker green/red
  age?: string;
  move?: string; // optional pre-baked reaction, e.g. "+3.2% next day"
}

// Optional variable-speed draw schedule: control points mapping a wall-clock
// second to a fractional point index (0..n-1). When present, the line draws
// piecewise-linearly through these instead of at a constant rate — used to land
// each event's candle exactly when its voice-over beat starts (dialog-reel).
export interface DrawKeyframe {
  t: number; // seconds from the start of the reel
  idx: number; // fractional point index the line should have reached by `t`
}

export interface PriceNewsChartSpec {
  ticker: string;
  label: string;
  valuePrefix?: string; // e.g. "$"
  points: OHLCPoint[];
  events: NewsEvent[];
  keyframes?: DrawKeyframe[]; // optional variable-speed draw schedule
}

export interface PriceNewsSpec {
  version: number;
  format: ReelFormat;
  theme: string;
  intro?: IntroSpec;
  chart: PriceNewsChartSpec;
  outro?: OutroSpec;
  sources?: string[];
}

export type PriceNewsProps = {
  spec: PriceNewsSpec;
};

// ---------------------------------------------------------------------------
// Format 3: Stock card — a still poster (CEO/hero portrait + company logo + a
// rating badge + headline + a stat grid), in the style of eyeball.football's
// player cards. Rendered as a single PNG via Remotion `still`.
// ---------------------------------------------------------------------------

export interface CardStat {
  label: string;
  value: string;
  sub?: string; // optional small line under the value
}

export interface CardBadge {
  label?: string; // small caption, e.g. "Impact"
  value: string; // the big number/word, e.g. "9.2"
  tone?: 'positive' | 'negative' | 'neutral';
}

export interface CardSpec {
  ticker: string;
  company: string;
  ceo?: string;
  sector?: string;
  exchange?: string;
  logoUrl?: string;
  heroImageUrl?: string; // CEO photo the director fetches; falls back to logo
  headline: string; // big top hook (rendered uppercase)
  tag?: string; // pill under the headline, e.g. "EARNINGS"
  badge?: CardBadge; // top-right rating
  stats: CardStat[]; // 1–4 stat cards
  // Latest NIS screenings featuring this ticker (e.g. "NIS Momentum"). When
  // present, the card shows a "NIS" credibility badge listing them.
  nisScreenings?: string[];
  cta?: string; // e.g. "Swipe to Watch"
  footer?: string; // e.g. "newsimpactscreener.com"
}

export interface CardReelSpec {
  version: number;
  format: ReelFormat;
  theme: string;
  card: CardSpec;
  sources?: string[];
}

export type StockCardProps = {
  spec: CardReelSpec;
};

// ---------------------------------------------------------------------------
// Format 4: The Arena — a league table (still) and the same table racing over a
// season (video). Mirror of services/arena_creatives/spec.py — keep in sync.
//
// The two share `ArenaRow` on purpose: a weekly package only reads as a package
// if the still and the video are visibly the same graphic.
// ---------------------------------------------------------------------------

export type FormResult = 'W' | 'L' | 'D';

export interface ArenaRow {
  rank: number;
  slug: string;
  name: string;
  code: string; // three-letter table code, e.g. "BOG"
  color: string; // club colour
  isControl: boolean; // the non-LLM baselines, styled without a hue
  nav: number;
  return: number; // fraction, e.g. 0.0289
  drawdown: number; // fraction, negative
  sharpe: number | null;
  trades: number; // CLOSED trades (not filled orders)
  winRate: number | null; // fraction over closes; null when nothing has closed
  positions: number;
  move: number | null; // rank change vs the lookback; positive = climbed
  form: FormResult[]; // oldest first
  streak: number; // signed run length; 0 when the last session was flat
}

export interface ArenaHeader {
  kicker: string;
  title: string;
  subtitle?: string;
}

export interface ArenaFooter {
  asOf: string;
  cta?: string;
  disclaimer: string; // never optional — every arena asset carries it
}

export interface ArenaZones {
  top: number; // rows tinted as the "promotion" band
  bottom: number; // rows tinted as the "relegation" band
}

export interface ArenaTableSpec {
  version: number;
  kind: 'arenaTable';
  format: ReelFormat;
  theme: string;
  header: ArenaHeader;
  hook?: string; // the strap line across the top of the table
  storyKey?: string;
  zones: ArenaZones;
  rows: ArenaRow[];
  footer: ArenaFooter;
}

export interface ArenaAgent {
  slug: string;
  name: string;
  code: string;
  color: string;
  isControl: boolean;
}

export interface ArenaKeyframe {
  t: string; // ISO session date
  label: string; // "Sep 4"
  entries: {id: string; value: number}[]; // value = cumulative return, a fraction
}

export interface ArenaRaceSpec {
  version: number;
  kind: 'arenaRace';
  format: ReelFormat;
  theme: string;
  header: ArenaHeader;
  hook?: string;
  storyKey?: string;
  metricLabel: string;
  agents: ArenaAgent[];
  keyframes: ArenaKeyframe[];
  finalRows: ArenaRow[];
  captions?: Caption[];
  outro?: OutroSpec;
  footer: ArenaFooter;
  sources?: string[];
}

export type ArenaTableProps = {spec: ArenaTableSpec};
export type ArenaRaceProps = {spec: ArenaRaceSpec};
