# Momentum search — where the long-only genome plateaus

**Result: the search improves the incumbent substantially, and the winner still
loses to buy-and-hold.** That is the headline, and no amount of internal
improvement changes it.

| 2014-2023, after costs | Sharpe | CAGR | max DD | total return |
|---|---|---|---|---|
| **SPY buy-and-hold** | **0.738** | **12.06%** | 33.7% | **+211.4%** |
| best evolved genome | 0.464 | 6.82% | 16.2% | +93.3% |
| incumbent NIS Momentum | −0.06 | ~0% | — | — |

The strategy wins on drawdown (16.2% vs 33.7%) — but it is only 43% invested on
average, so that is what half-deployed capital buys, not skill. Information
ratio is **−0.36**: it underperforms the benchmark on a tracking-error-adjusted
basis too.

Run `evolve2`: 800 most liquid US names, dev 2014-01 → 2023-12, vault never
opened, **110 distinct configurations** evaluated.
Charts: `output/runs/evolve2/charts/report.html`

---

## The trajectory

| | reward | Sharpe | max DD | trades | turnover | exposure | fold Sharpes |
|---|---|---|---|---|---|---|---|
| incumbent NIS Momentum | −0.673 | −0.06 | — | — | 13.2×/yr | — | — |
| best found | **+0.285** | **0.464** | 16.2% | 440 | 4.2×/yr | 43% | −0.08 / 0.71 / 0.52 / 0.75 / 0.71 |

The incumbent had two negative folds out of five and gave back its edge in
frictions. The evolved genome has one marginally negative fold, a third of the
turnover, and a 16% drawdown.

## What the search actually did — it simplified

The winning move came from the LLM policy under the `loosen_gates` operator,
and its argument was structural rather than numerical:

> *"The trend screen is six near-collinear expressions of one idea: the funnel
> shows price>sma200 → sma_stack → sma200_rising → above_52w_low removes names
> in overlapping slices... Keeping only close>SMA200, near-52w-high and the RS
> percentile should preserve nearly the same candidate set while deleting five
> to six active parameters."*

It deleted five of the six trend gates, replaced breakout timing with pure
cross-sectional ranking, and widened the stop from 2.5 to ~5.5 ATR. Turnover
collapsed and the fold spread narrowed. The complexity penalty in the reward is
what made that direction profitable to explore.

## Why it stopped

Eight iterations at 0.285 with the proposal count falling (8 → 5 → 6), while the
operators kept varying — `tune_exits`, `tighten_gates`, `tune_ranking`,
`diversify`, `tune_universe`, `tune_portfolio`, random restarts. It is not a
stuck sampler; it is a genuine local plateau. The reward gap between #1 and #4
is 0.285 → 0.146, so the top is a real cluster, not a knife edge.

**The binding constraints are structural, not parametric:**

1. **Long-only.** The regime filter can stand the book down in a bear fold, but
   standing down earns zero. Two of five folds can never contribute.
2. **43% average exposure.** Over half the capital is idle. Return is capped
   regardless of signal quality, and the search's attempts to fix it
   (`diversify`, `tune_portfolio`) both scored worse — deploying more capital
   into the same signal degraded the risk-adjusted result.
3. **alpha_t = 1.03** against a gate of 1.50. Beta is only 0.32, so this is not
   a closet index fund — but the alpha is not statistically strong either.

## The gate says no, and it should

| check | actual | required | |
|---|---|---|---|
| Sharpe | 0.464 | ≥ 1.00 | FAIL |
| Deflated Sharpe | 0.557 | ≥ 0.95 | FAIL |
| alpha t-stat | 1.031 | ≥ 1.50 | FAIL |
| **PBO** | **0.59** | ≤ 0.35 | **FAIL** |
| fold win rate | 0.80 | ≥ 0.60 | pass |
| max drawdown | 16.2% | ≤ 30% | pass |
| trades | 440 | ≥ 60 | pass |

**PBO is the one to read.** At 41 configurations it was 0.255 — selection on
backtest performance carried real information. At 110 it is **0.59**: the
in-sample winner lands in the bottom half out of sample more often than not.

The search did not merely stop improving. Past roughly 40 configurations it
began *fitting noise*, and every additional trial made its own winner less
credible. That is backtest overfitting caught in the act by the instrument
built to catch it, and it is a hard argument for stopping a search when the
reward curve flattens rather than letting it run.

The alternative — lowering `min_sharpe` until something passes — would produce a
deployable artifact and a worthless one.

## A reproducibility bug this exposed

The first `finalize` reported alpha_t = 0.59; the ledger said 1.03 — for the
same genome. Cause: 726 more symbols had been synced between the search and the
finalize, so `--limit 800` selected a **different** 800 most-liquid names. The
re-evaluation was silently measuring a different universe.

Fixed by having `finalize` read each genome's **stored return series** from the
ledger instead of re-running the backtest, and re-running only when no series
exists (with a warning, and a `metrics_recomputed` flag in the output). A
result that changes because the cache grew is not a result.

Not more search. The response surface has been mapped and it tops out here.

- **A short sleeve.** The single largest structural lever: it converts the two
  dead folds from "flat" into "contributing", and would raise exposure without
  raising net long risk. It is also the biggest engineering change, touching
  sign handling throughout the simulator.
- **Better entry information.** The flow-inertia programme was the attempt to
  find it, and Tier 1 established that daily OHLCV does not contain it
  (`STAGE1-FINDINGS.md`).
- **A longer, cleaner universe.** The delisted feed is page-capped at 57 names
  on this FMP plan, so absolute returns here are optimistic.

Both threads hit their ceiling for the same reason: **daily price and volume
data does not carry enough information.** Momentum from price alone plateaus
around Sharpe 0.46 after realistic costs; flow from price alone is not
measurable at all. That is an argument for buying better data, not for running
more experiments on this data.
