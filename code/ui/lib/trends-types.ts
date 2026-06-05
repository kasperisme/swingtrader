// Shared trend types — kept separate from lib/trends.ts (which is `server-only`)
// so client components can import the types without pulling the data layer into
// the client bundle.

export type TrendKind = "ticker" | "tag";

/** Scoreboard filter modes. */
export type SortMode = "mentions" | "growth" | "new";

export type TrendItem = {
  /** ticker (UPPER) or theme slug (lower) — also the `?tag=` value */
  key: string;
  /** display label */
  label: string;
  kind: TrendKind;
  /** mentions/articles in the current window */
  current: number;
  /** mentions/articles in the immediately prior window */
  previous: number;
  /** (current - previous) / previous, or null when previous is 0 */
  deltaPct: number | null;
  /** brand-new this window (no activity in the prior window) */
  isNew: boolean;
  /** confidence-weighted mean sentiment over the window (tickers only) */
  avgSentiment: number | null;
  /** daily counts across the full 2×window span, oldest → newest */
  spark: number[];
};

/** One kind's ranked lists, one per filter mode. */
export type TrendColumn = Record<SortMode, TrendItem[]>;

export type TrendingBoard = {
  tickers: TrendColumn;
  tags: TrendColumn;
};
