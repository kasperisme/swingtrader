# The momentum universe — the standing decision, and what it measures

**Decision: the Minervini trend template on NYSE + NASDAQ is the universe.
Everything is built for it from here.**

This document records what that universe is, how it is pinned so runs stay
comparable, and the first measurement made on it — which is a null.

Reproduce:
```bash
.venv/bin/python -m strategylab.momentum.cli pin        # build + fingerprint
.venv/bin/python -m strategylab.momentum.cli ic         # IC + incremental IC
```
Artifacts: `output/momentum/{universe.json, universe_mask.npz, ic_H21.json, signal_correlations_H21.csv}`

---

## 1. The universe

Eight criteria, unmodified and untuned, plus three tradability floors the
template says nothing about:

| filter | qualifying name-days |
|---|---|
| priced | 8,745,893 |
| 1. price > 150d and 200d MA | 4,790,891 |
| 2. 150d MA > 200d MA | 3,732,745 |
| 3. 200d MA rising ≥ 1 month | 3,571,226 |
| 4. 50d MA > 150d and 200d | 3,299,001 |
| 5. price > 50d MA | 2,463,581 |
| 6. ≥ 30% above the 52-week low | 2,138,012 |
| 7. within 25% of the 52-week high | 2,108,041 |
| 8. RS percentile ≥ 70 | 1,436,788 |
| + price > $5 | 1,369,287 |
| + ADV ≥ $5M | 1,155,910 |
| + ≥ 252 bars of history | **1,149,011** |

**Median 206 names per day** (range 1–507), 2,006 distinct names ever qualified,
2004-01 → 2026-06. That is a sane book size: wide enough for a cross-section,
narrow enough to hold.

**It is pinned.** `universe.json` records the spec, the symbol list, the date
range and a SHA-256 fingerprint of the eligibility mask
(`b714bb044e11…`). `verify(panel)` refuses to certify a run against a panel the
pin was not built on. This is not bureaucracy — the single largest source of
incomparable results in this project was universe drift: the same incumbent
genome scored Sharpe 0.464 and later 0.22 across a restart, and part of the gap
was the cached symbol set growing from 800 to 2,357 underneath a `--limit` flag
that then selected a different 800 names.

## 2. Why momentum is a mandatory control

Before this universe was adopted, the obvious test was run: does conditioning
post-earnings drift on the trend template improve it? The raw answer looked
excellent — the screen roughly **tripled** the announcement spread
(+0.53% → +2.01% pre-2014, t 1.87 → 4.16).

The matched no-news control said otherwise:

| era | subset | announcements | control | excess | t |
|---|---|---|---|---|---|
| dev 2014-2023 | all | −0.18% | −0.67% | +0.49% | 1.46 |
| dev 2014-2023 | **minervini** | +0.61% | **+1.04%** | **−0.43%** | −0.43 |
| vault 2024-2026 | minervini | +0.75% | +1.67% | −0.93% | −0.61 |

The screen lifts the announcement events and the *non*-announcement events
alike, and in the recent eras it lifts the control by more. Tier composition is
nearly identical (median ADV $32M vs $39M), so it is not a liquidity artefact.
**The trend template adds momentum, not information.**

Everything measured on this universe is exposed to that same confusion by
construction, because the universe *is* a momentum screen. So `signals.py`
marks `mom_12_1` and `rs_rank` as mandatory controls, and the reported number
is the Fama-MacBeth coefficient with every other signal in the same regression.
A signal that only works by re-encoding the screen shows up here as adding
nothing. `test_incremental_ic_collapses_for_a_relabelled_control` plants a noisy
copy of a control and asserts exactly that.

## 3. The first measurement: sixteen signals, dev 2014-2023

Every predictor this project has produced, scored on the pinned universe,
21-day horizon, fills at the next open, Newey-West t with 21 lags.

| signal | family | IC | t(NW) | hit | placebo t | **incr bps/σ** | **incr t** |
|---|---|---|---|---|---|---|---|
| proximity_52w_high | momentum | −0.0150 | −1.51 | 46.5% | −0.25 | −15.9 | **−1.91** |
| volume_surge | volume | −0.0076 | −2.05 | 46.4% | −0.81 | −5.8 | −1.87 |
| rs_rank * | momentum | +0.0093 | +0.86 | 53.1% | −0.59 | +16.6 | +1.84 |
| reversal_21d | reversal | +0.0127 | +1.64 | 53.9% | +0.83 | +14.9 | +1.67 |
| extension_from_sma50 | reversal | −0.0067 | −0.82 | 48.9% | −0.27 | +13.2 | +1.38 |
| pct_above_52w_low | momentum | +0.0151 | +1.21 | 55.2% | −0.10 | +14.7 | +1.14 |
| tightness | volatility | −0.0011 | −0.14 | 53.0% | −0.42 | +6.6 | +0.99 |
| rs_line_high | momentum | −0.0087 | −1.44 | 48.2% | −0.08 | −5.5 | −0.98 |
| low_adr | volatility | −0.0095 | −0.68 | 48.4% | −0.34 | −11.7 | −0.90 |
| residual_momentum | momentum | +0.0070 | +0.70 | 56.8% | −0.13 | −9.5 | −0.67 |
| reversal_5d | reversal | +0.0096 | +1.65 | 53.2% | −0.54 | +2.5 | +0.46 |
| gap_fade | reversal | +0.0016 | +0.64 | 49.9% | −0.50 | −0.8 | −0.35 |
| squeeze | volatility | +0.0033 | +0.99 | 51.4% | −0.08 | −2.4 | −0.35 |
| mom_12_1 * | momentum | +0.0066 | +0.60 | 54.7% | +0.23 | +6.2 | +0.32 |
| volume_confirmation | volume | −0.0002 | −0.04 | 52.5% | +0.63 | +0.7 | +0.12 |
| info_discreteness | momentum | +0.0015 | +0.17 | 47.9% | −0.06 | +0.3 | +0.03 |

`*` = mandatory control.

**Nothing clears the bar.** The multiplicity-corrected threshold for 16 signals
is |t| > 2.96; the largest incremental t is 1.91. No signal reaches |t| ≥ 2 even
uncorrected. Every placebo is clean (|t| ≤ 0.83 across five seeds).

Two supporting observations:

- **A naive t-stat would have overstated significance by 3.2×.** Sampling a
  21-day forward return daily produces an IC series with ~21 days of
  autocorrelation. Without the Newey-West correction, `volume_surge` at t = −2.05
  becomes t ≈ −6.6 and reads as a discovery.
- **Signs are unstable across horizons.** `mom_12_1` runs +0.0092 at 5 days and
  −0.0080 at 63; `tightness` runs −0.0011 at 21 and +0.0194 at 63. A signal
  whose sign depends on the holding period is not a signal yet.

## 4. Breadth is largely an illusion here

Stacking only helps to the extent components are different things. On a
momentum-screened universe they mostly are not:

| pair | average daily cross-sectional rank correlation |
|---|---|
| residual_momentum ↔ mom_12_1 | **+0.83** |
| pct_above_52w_low ↔ rs_rank | **+0.81** |
| reversal_21d ↔ extension_from_sma50 | −0.76 |
| low_adr ↔ pct_above_52w_low | −0.68 |
| mom_12_1 ↔ pct_above_52w_low | +0.65 |

Sixteen signals, but far fewer independent ones. `IR ≈ IC × √breadth` rewards
*independent* bets; correlations of 0.8 mean the same bet counted twice.

## 5. What this means for the ensemble

The architecture is built and correct — pinned universe, a common signal
interface, one measurement layer, honest multiplicity accounting. What is
missing is inputs. **An ensemble multiplies breadth, not edge; stacking sixteen
nulls produces a well-diversified null.**

Three things would change the answer, in order of how much I would bet on them:

1. **A signal with genuine information advantage.** The NIS news pipeline is the
   only candidate this project has, and it starts in 2025 — enough for the vault
   window, nowhere near enough for a dev test. Data-blocked, not idea-blocked.
2. **A different dependent variable.** Everything above predicts the
   cross-section of forward returns. The momentum universe's actual decisions are
   *when to enter a base*, *where to stop*, and *when to exit* — path questions,
   not cross-sectional ones. A signal can be null on 21-day return ranking and
   still improve exit efficiency, which the existing `investigate.py` critic
   already measures.
3. **A shorter horizon.** Everything here is 5-63 days. The universe turns over
   faster than that.

## 5b. Does holding the whole screen beat the market?

Three studies pointed here: the breakout trigger underperforms a random entry in
this universe, no conditioner sorts expectancy, and base structure does not
separate triggers. So the implied alternative — stop timing and just own what
qualifies — was simulated as a portfolio. Equal weight across every qualifying
name, monthly rebalance, weights drifting in between, 26bp round trip on
realised turnover, cash earning nothing.

```bash
.venv/bin/python -m strategylab.momentum.cli hold --breadth-scaled
```

**The answer is no — it matches the index rather than beating it, and it does so
on a panel that has removed the failures.**

| 2005-2026 | CAGR | vol | Sharpe | max DD | total | beta | alpha t |
|---|---|---|---|---|---|---|---|
| screen, always invested | +11.1% | 21.4% | 0.60 | **−56.9%** | +850% | 0.99 | 0.41 |
| screen, breadth-scaled | +10.4% | 17.1% | **0.66** | **−39.1%** | +734% | **0.69** | 1.25 |
| **SPY** | **+10.8%** | 18.4% | **0.65** | −55.4% | +804% | — | — |

On return and on risk-adjusted return it is a coin flip: CAGR 10.4% against
10.8%, Sharpe 0.66 against 0.65, alpha t = 1.25 and an information ratio of
−0.05. Split by era it is worse than that — the screen returned **+7.3% against
SPY's +11.9% across 2014-2023**, with an information ratio of −0.36. The
2024-2026 vault looks excellent (+30.5% vs +21.4%, IR 0.60) but that is 2.5
years and alpha t = 1.15.

**What it does buy is drawdown.** Breadth-scaled, the maximum drawdown falls from
−55.4% to **−39.1%** at a beta of 0.69 and 86% average exposure. Same return,
two-thirds of the market risk. That is the same profile the evolved genome
showed (16.2% drawdown against SPY's 33.7%) reproduced with no strategy at all —
just the screen and a position-sizing rule.

**Breadth scaling is the whole of that.** The screen's count collapses in bear
markets — median 63 qualifying names in 2008 and 26 in 2009, against 206 overall
— so exposure is scaled by the qualifying count against its own *trailing*
median. Left always-invested, the book goes 100% into whatever handful still
qualifies and takes a −56.9% drawdown, worse than the index. The de-risking is
not a regime overlay; it falls out of the screen emptying, but only if the
sizing rule listens to it.

Rebalance frequency matters more than anything else measured:

| variant | CAGR | Sharpe | max DD | turnover |
|---|---|---|---|---|
| weekly | +5.4% | 0.36 | −65.9% | 26.8x |
| **monthly** | **+11.1%** | 0.60 | −56.9% | 11.4x |
| quarterly | +10.4% | 0.55 | −59.8% | 5.4x |

Weekly rebalancing destroys the strategy outright — 26.8x annual turnover at
26bp a round trip is roughly 7% a year in frictions.

### The caveat that outweighs the result

**Survivorship here is total.** Of 2,130 symbols in the panel, **2,129 still have
data at the panel end**, and of the 2,006 names the screen ever held, **zero**
stopped trading. This backtest has never once held a company that failed.

For a momentum book that is not a footnote. The characteristic risk of owning
strong-trending names is the one that gaps down 40% and never recovers, and the
panel contains almost none of them, because the FMP plan page-caps the delisted
feed at ~57 tickers against 5,762 live listings. The bias runs one way only.

So the honest statement is stronger than the table: **on a panel with the losers
removed, holding the screen still fails to beat the index.** The true figure is
worse than shown by an amount this data cannot measure.

## 5c. Concentration: "hold only the best one and rotate"

The natural alternative to holding the whole screen is to hold only the best
name and reallocate when another becomes better. It is a sharp question because
it isolates one thing: **does the ranking have enough skill to justify giving up
diversification?** Grinold's `IR ~ IC x sqrt(breadth)` says holding one name
sets breadth to 1, so the entire result must come from the ranking — and every
measurement in §3 puts the incremental IC of every available score at zero.

```bash
.venv/bin/python -m strategylab.momentum.cli rotate
```

Monthly rebalance, 2x hysteresis so an incumbent is kept while it stays inside
the top `N x 2` (without it the book churns on rank noise and pays 26bp a
switch on 100% of capital). Full period 2005-2026, ranked by RS:

| hold | CAGR | vol | Sharpe | max DD | worst 12m | **beta** | alpha t |
|---|---|---|---|---|---|---|---|
| **1** | +8.0% | **98.4%** | 0.52 | **−96.6%** | **−88.4%** | **1.62** | +1.56 |
| 2 | +24.0% | 69.9% | 0.64 | −86.4% | −75.6% | 1.46 | +1.97 |
| 5 | +22.8% | 51.5% | 0.65 | −71.5% | −55.0% | 1.42 | +1.74 |
| 10 | +22.4% | 42.2% | 0.69 | −64.3% | −51.6% | 1.36 | +1.75 |
| 50 | +16.2% | 29.2% | 0.66 | −58.4% | −53.4% | 1.16 | +1.27 |
| **all** | +10.4% | 17.1% | **0.66** | **−39.1%** | −31.7% | **0.69** | +1.25 |
| SPY | +10.8% | 18.4% | 0.65 | −55.4% | — | — | — |

**Concentration is leverage, not skill.** Three things say so together:

* **Beta rises monotonically with concentration** — 0.69 holding everything,
  1.16 at fifty names, 1.62 at one. The extra return arrives with matching extra
  market exposure.
* **Sharpe does not move.** The entire spread across every concentration level
  and both scores is 0.45 to 0.69 — **1.1 standard errors** at a 21-year Sharpe
  SE of 0.22. Statistically there is one number here, not eight.
* **No alpha t-stat clears its bar.** The largest is +2.04 against a
  multiplicity-corrected requirement of about 2.9 for the sixteen variants run.

**What does change, categorically, is ruin risk.** A −39.1% maximum drawdown
becomes **−96.6%**, and the worst rolling twelve months goes from −31.7% to
**−88.4%**. That is not a bad year, it is the end of the account — and unlike
the Sharpe differences it is far outside noise.

The seductive cell is `mom_12_1` at one name on the dev decade: **CAGR +45.4%,
Sharpe 0.84**, the best risk-adjusted number in the study. The identical
configuration over the full period is CAGR +20.6%, Sharpe 0.62, max drawdown
**−98.0%**. One lucky decade-path, and exactly the number a search would have
stopped on.

### The rotation itself: how often to look, and how much better is better

The concentrated book above is not buy-and-hold — at monthly review it made
**135 switches over 21.5 years (6.3/yr, median holding 23 sessions)**, rotating
LNG → FRO → ITRI → NDAQ → DXPE → BCRX → SRPT → NVAX and on. But monthly review
is only one version of "reallocate when a better one appears", so the switching
rule was swept in both directions it can vary: how often the book looks, and how
much better the challenger must be before it takes over.

```bash
.venv/bin/python -m strategylab.momentum.cli switch
```

| look \| hysteresis | switches/yr | hold days | gross CAGR | net CAGR | cost drag | Sharpe | max DD |
|---|---|---|---|---|---|---|---|
| **daily, always switch** | **46.1** | **2** | **−12.5%** | **−22.5%** | +9.9% | 0.22 | **−99.9%** |
| daily, top-2 band | 23.4 | 5 | +11.0% | +4.4% | +6.6% | 0.49 | −98.0% |
| daily, top-5 band | 12.9 | 14 | +18.5% | +14.5% | +3.9% | 0.57 | −96.6% |
| weekly, always switch | 19.7 | 5 | −11.7% | −16.1% | +4.4% | 0.29 | −99.5% |
| monthly, top-2 band | 6.3 | 23 | +9.8% | +8.0% | +1.8% | 0.52 | −96.6% |
| quarterly, top-2 band | 3.3 | 63 | −14.5% | −15.2% | +0.7% | 0.25 | −99.0% |

Three readings, in descending order of how much they can be trusted.

**1. The drawdown is unanimous and structural.** Every one of the twelve rules
draws down between **−96.2% and −99.9%**. Not one switching discipline, at any
frequency, avoids effectively total loss. This is the only column in the table
that is not noise.

**2. The cost drag is mechanical.** Each switch is a full round trip on 100% of
the account, so 46 switches a year is **9.9% a year** in frictions before
anything else happens. That is the price of looking often, and it is knowable in
advance.

**3. Which switching rule is "best" is not knowable from this data.** The
one-stock book runs at **95% annualised volatility**, so the standard error on a
21-year CAGR estimate is **21% a year**. The gross CAGR spread across all twelve
rules is 34 percentage points — **1.7 standard errors**. The apparent winner
(daily review with a top-5 band, +14.5% net) and the apparent disaster (daily
review switching every time, −22.5%) are not distinguishable. Picking the top row
of that table would be selecting on noise, which is precisely what the rest of
this project exists to avoid.

What *can* be said is that the two effects push in opposite directions and only
one of them is real: looking more often costs a known amount and buys an unknown
amount. At 46 switches a year you pay 9.9% for the privilege of reacting to a
ranking whose short-horizon movement has never been shown to carry information —
§3 measured the incremental IC of every available score at zero.

### Why this is worse than the table shows

A one-stock book is *maximally* exposed to the survivorship problem in §5b.
Zero of the 2,006 names the screen ever held stopped trading, so the panel
contains almost no company that failed. Holding a single name is precisely the
strategy for which "the one that gaps down 40% and never recovers" is the
dominant risk, and that event is essentially absent from the data. **The −96.6%
is an understatement.**

### The practical form of the answer

If the appeal is the higher return, note what the beta column implies: the same
exposure is available by **levering the diversified book about 2.3x** (0.69 to
1.6), which delivers comparable expected return with a fraction of the
idiosyncratic risk, none of the 12.5x turnover, and no path to ruin.
Concentration is the expensive way to buy beta.

## 6. Bugs found

- **`extension_from_sma50` silently vanished from an entire IC table.** It asked
  for a feature name that does not exist (`dist_from_sma50` rather than
  `dist_from_sma(length=50)`), raised, and was swallowed by a `log.warning` in a
  loop. It read as "tested, found wanting". Failures are now logged at ERROR and
  `test_every_registered_signal_computes` asserts the registry is complete.
- **A one-seed placebo read as a broken control.** `reversal_21d` came in at
  placebo t = +2.68 on a single shuffle. Across five seeds it is +0.83. With
  sixteen signals in a table, a one-draw mean-zero statistic will land beyond
  |t| = 2 somewhere almost every time; the placebo now reports the distribution.
- **A look-ahead I reported and then withdrew.** The point-in-time test flagged
  50,357 cells of `high_52w` differing before the scramble point. The rolling
  helpers are correctly backward-looking; the *test* rebuilt `high` and `low` as
  `close × 1.01` for every row, changing the inputs everywhere. Recorded because
  a false look-ahead alarm costs as much time as a real one.
