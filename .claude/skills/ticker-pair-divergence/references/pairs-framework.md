# Pairs / Divergence — how to read the stats honestly

Everything comes from `pair.json` (built by `pair_data.py` from
`swingtrader.ticker_pair_stats` + `ticker_pair_candidates_v` + FMP prices).

## The relationship (the hook)
- `relationship.rel_types` — the news-derived economic link(s) between the two
  companies, surfaced by the relationship graph: `supplier`, `customer`,
  `partner`, `competitor`, `acquirer`. This is the "few people know this" angle.
- `relationship.article_count` — how many headlines link them (evidence the link
  is real, not coincidence).
- The pair only exists in the stats table because it shared a *verified* link —
  this is a curated graph, not a blind N² scan. Lead with the surprising link.

## The proof (cointegration)
- `stats.is_cointegrated` — true when `coint_pvalue < 0.05` (Engle-Granger ADF on
  the spread). **Only say "cointegrated" when this is true.** Otherwise the two
  merely tend to track / mean-revert — say that instead.
- `stats.coint_pvalue` — the test p-value (lower = stronger statistical tether).
- `stats.half_life_days` — Ornstein-Uhlenbeck mean-reversion half-life: roughly how
  long it takes a deviation to halve. Small (days–weeks) = a tradeable spring;
  large (months) = slow, lower-conviction.
- `stats.hedge_ratio` — OLS beta of A on B; the spread is `A − hedge_ratio·B`.
- `stats.correlation` — daily-return correlation (often *low* even for cointegrated
  pairs — they're tethered in levels, not tick-for-tick; don't lead with this).

## The trade (divergence → mean reversion)
- `stats.current_zscore` — how many σ the live spread sits from its mean. This is
  the divergence signal.
  - `|z| ≥ 2` → stretched: the classic entry band → **the trade is live**.
  - `1.5 ≤ |z| < 2` → **a setup is forming**.
  - `|z| → 0` → at fair value, no edge.
- `series.z` — the z-score over the window (so the chart can show it stretching);
  `series.divergence_idx` marks where it started pulling apart.
- `trade.long` / `trade.short` — direction (computed from the sign of z):
  - z > 0 → spread rich (A expensive vs B) → **short A, long B**.
  - z < 0 → **long A, short B**.
  - Bet: the spread reverts to its mean (target z = 0); stop if it stretches to ~3σ.
  - Expected timing ≈ `half_life_days`.

## The honest caveats (always)
- Cointegration is estimated on a trailing window and **can break** (a merger,
  a guidance change, a structural shift). Past tracking ≠ future tracking.
- A diverged spread **can keep diverging** well past 2σ before it reverts — or
  never revert. Size for that; a pairs trade is not risk-free arbitrage.
- A *forming* setup is not an entry. State which it is.

## The visual
- Both legs normalized to 100 at the window start → the eye sees them track, then
  separate. The amber-shaded gap from `divergence_idx` onward is the divergence.
- Each company **logo rides the right end of its line** (the latest data point) so
  the viewer instantly knows which line is which.
