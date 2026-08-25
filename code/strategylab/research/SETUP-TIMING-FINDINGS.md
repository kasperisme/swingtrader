# Setup timing — the Minervini trade, and what actually times it

**Verdict: the breakout trigger is worse than no trigger. Two conditioners lift
the hit rate significantly. Neither lifts expectancy.**

The trade is fixed as specified: enter on a breakout from a base, stop at the
support beneath it with risk capped at 10%, take profit at 2R. Fixing it makes
the question sharp — with a 2R target against a 1R stop the outcome is binary
and the breakeven hit rate is exactly 1/3.

That 1/3 is not an arbitrary bar. **For a driftless random walk, the probability
of touching +2R before −1R is exactly 1/3** (optional stopping on a martingale).
So the headline test is literally "do these setups drift up at all?"

Run: 5,609 breakouts on dev (2014-2023) in the pinned momentum universe, against
10,068 day- and universe-matched pseudo-setups; 1,613 on the sealed vault.
Reproduce: `.venv/bin/python -m strategylab.setups.cli timing` (~27 s).
Artifacts: `output/setups/{timing.json, preregistration.json, setups.csv.gz, pseudo_setups.csv.gz}`

---

## 1. The setup does not clear its own control

| | dev | vault |
|---|---|---|
| P(target \| resolved) | **31.3%** | 28.8% |
| pseudo-setup control | **34.3%** | 33.5% |
| driftless random walk | 33.3% | 33.3% |
| cost-adjusted breakeven | 34.5% | 34.4% |

| pre-registered test | value | t | pass |
|---|---|---|---|
| S1 hit rate minus breakeven | −4.01pp | −2.17 | no |
| S2 minus the pseudo-setup control | −2.14pp | −2.06 | no |
| S3 net expectancy per trade | −0.002R | −0.04 | no |

Read S2 carefully. The control is **buy a random qualifying name from the same
universe on the same day, with the same stop and target geometry, that did not
break out.** It hits the target 34.3% of the time. The breakout hits it 31.3%.

**The trigger is a negative signal.** Waiting for the base to break costs about
three percentage points of hit rate versus simply owning a name that already
passes the trend screen. The vault agrees (28.8% vs 33.5%).

That is not a small print. The entire premise of a breakout entry is that the
break confirms demand. On this universe, over this decade, the confirmation is
worth less than nothing — consistent with the setups buying extension into a
move that has already happened.

## 2. Two conditioners time it, and the effect is real

Hit rate across quintiles of each conditioner, measured on the trigger day:

| conditioner | quintile hit rates (low → high) | Spearman | top − bottom | t | placebo t |
|---|---|---|---|---|---|
| **rs_rank** | 19% 23% 22% 24% **26%** | **+0.90** | **+9.7pp** | **+4.15** | −1.27 |
| **reversal_5d** | 21% 23% 20% 25% **27%** | **+0.70** | **+8.0pp** | **+3.34** | −0.82 |
| info_discreteness | 22% 22% 22% 24% 25% | +1.00 | +5.4pp | +2.07 | −0.99 |
| dist_52w_high | 23% 20% 25% 24% 24% | +0.50 | +3.0pp | +1.48 | +0.90 |

Both survivors clear the Bonferroni bar (α = 0.00179 over 22 variants), are
monotone, and their shuffled-label placebos are clean.

They also say something coherent. `reversal_5d` is the *negative* of the 5-day
return, so its top quintile is breakouts that fired **without** a preceding
run-up — a tight, quiet base rather than a chase. That is Minervini's own rule
about not buying extended, recovered here from the data rather than assumed.

## 3. The finding that matters: hit rate and expectancy come apart

| rs_rank quintile | hit rate | **net expectancy (R)** |
|---|---|---|
| 0 (lowest) | 19.0% | +0.031 |
| 1 | 23.4% | +0.116 |
| 2 | 22.5% | +0.025 |
| 3 | 24.0% | +0.034 |
| 4 (highest) | **26.4%** | **+0.018** |

The hit rate rises monotonically across quintiles. **Expectancy does not — the
best-hit-rate bucket has the worst expectancy of the five.** `reversal_5d`
behaves the same way (+0.083, +0.050, −0.055, +0.120, +0.026).

The reason is that R is not actually fixed:

| exit | n | mean R (net) | share of gross P&L |
|---|---|---|---|
| target | 1,070 | +1.958 | +32.7% |
| target_gap | 222 | +2.241 | +7.8% |
| stop | 2,393 | −1.041 | −38.9% |
| **stop_gap** | 447 | **−1.312** | −9.2% |
| **timeout** | 1,476 | **+0.500** | +11.5% |

Two leaks. **Gaps through the stop cost 1.31R, not 1.00R** — "limited risk" is
limited only when the market opens where you left it, and 447 of 5,609 trades
(8%) gapped through. And **26% of trades never resolve**; they time out at the
60-bar cap and earn +0.50R on average, which is where a meaningful slice of the
profit actually comes from.

So a conditioner that raises the frequency of clean 2R wins can simultaneously
raise gap-through-stop losses or cut profitable timeouts, and net to nothing.
**Optimising the hit rate of a fixed-R system does not optimise the system.**

## 4. Stacking the two survivors adds nothing

Taking only setups in the top two quintiles of *both* rs_rank and reversal_5d —
post-hoc, since the pair was chosen after seeing §2:

| | n | P(target \| resolved) | control, same rule | net R | t |
|---|---|---|---|---|---|
| dev | 742 | **33.7%** | **33.7%** | +0.008 | +0.11 |
| vault | 235 | 40.9% | 37.9% | +0.133 | +0.89 |

On dev the stacked subset matches its control **to the decimal**. Conditioning
lifted the hit rate from 31.3% to 33.7% — and lifted the control by exactly the
same amount, because the conditioners are properties of the *name*, not of the
*trigger*. They select better stocks, which the control also gets.

This is the same lesson the momentum universe delivered one step earlier, in a
new place: a conditioner measured against no control looks like timing, and
measured against the right control turns out to be selection.

## 5. What this says about the trade as specified

Three things, in order of how much the evidence supports them:

1. **The breakout trigger is the weakest component.** Dropping it and holding
   qualifying names outright scored better on both dev and vault. Any future
   version should have to beat "just own the screen" before it earns its
   complexity.
2. **The 2R fixed target caps the distribution, not the expectancy.** Tested in
   §5b: trailing on SMA50 from the target leaves the mean unchanged and triples
   the maximum win. Trailing on SMA21 measurably *hurts*. The target is not
   leaving money on the table in expectation — it is trading skew for
   consistency, which is a sizing choice rather than an error.
3. **Gap risk is unmodelled in the trade design, not just the backtest.** 8% of
   trades lose 31% more than the planned 1R. Position sizing built on "risk is
   capped at 1R" is systematically undersized for the tail.

## 5b. The trailing exit, tested against the fixed target

The fixed-target study pointed at the 2R cap, and the trade as actually run
converts at the target rather than closing: the stop moves to a moving average
and the position runs until price closes below it. Both rules are resolved on
the **same** setup list, so every trade appears under both and the comparison is
paired — `test_trailing_cannot_change_a_trade_that_never_reached_the_target`
asserts the two are byte-identical up to the target, which is what makes the
difference attributable to the exit alone.

| trail MA | era | ΔR per trade | t | R fixed → trail | max win |
|---|---|---|---|---|---|
| SMA10 | dev | −0.0294 | **−4.27** | +0.045 → +0.021 | 82% |
| **SMA21** | dev | **−0.0333** | **−3.37** | +0.045 → +0.018 | 93% |
| SMA21 | vault | +0.0039 | +0.16 | +0.148 → +0.164 | 69% |
| **SMA50** | dev | **−0.0003** | **−0.02** | +0.045 → +0.042 | **185%** |
| SMA50 | vault | +0.0275 | +0.43 | +0.148 → +0.185 | 777% |

**SMA21 is too tight and measurably hurts** (−0.033R, t = −3.37 on dev). **SMA50
is free on the mean** — indistinguishable from taking the fixed 2R — and it
changes the shape of the outcome completely:

| winners (reached 2R), dev | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|
| fixed 2R | +13.84% | +13.88% | +19.1% | +24.1% | +36% |
| SMA50 trail | +13.66% | **+10.42%** | **+28.1%** | **+66.8%** | **+185%** |

The trail gives back on the typical trade and captures the exceptional one. That
is the whole trade-off, and the mean is silent on it: **same expectancy, far more
skew.** Whether that is an improvement depends on whether the book can survive
the give-back long enough to catch the tail — a sizing question, not a signal one.

**On the remembered "~6% average improvement on winners."** At SMA21 the measured
mean effect is **−0.88%** and the median **−2.22%**, with only 33% of winners
improving — but the 90th percentile is +7.9% and the 99th is +23.1%. A +6%
average lands around the 85th–90th percentile of the actual distribution. That
is the signature of remembering the trades that ran: the two-thirds that gave
back 2–5% are not memorable, and the one that went to +93% is.

Two caveats in the other direction, and they are not small. This is a *mechanical*
setup — 5,609 breakouts taken without judgement — whereas a discretionary book is
a selected subset, and if that selection is good the trail may genuinely do
better on it. Nothing here can test that. And conditioning the trail on RS
strength does not help: quintile 3 is significantly *negative* (−0.053R,
t = −2.36) and the rest are noise, so "trail only the strongest" is not supported.

The natural implication, untested but arithmetically forced: since both rules
have the same mean on dev, **any blend of them has the same mean** — so taking
part of the position off at 2R and trailing the remainder on a slow MA buys a
chosen point on the skew spectrum at no cost in expectancy. That is a sizing
decision the evidence supports and does not require a new study.

## 5c. Two defects in the conditioner test, and what they hid

The first version of §2 was measured with a test that had two faults. Both are
fixed; the corrected table is below and it is a cleaner null than the original.

**Binary conditioners were silently dropped.** `qcut(..., 5)` refuses a variable
with fewer than five distinct values, and the caller recorded the result as
"unavailable" — so `market_regime`, `squeeze` and `rs_line_high` appeared in the
report as though they had been examined when they never ran. `market_regime` was
the only genuine *timing* variable in the entire list.

**The test was one-sided.** Scoring only "top bucket beats bottom" marks every
inverse relationship as a failure. That hid the largest effect in the table:

| risk_pct quintile | mean stop | hit rate | cost (R) | expectancy (R) |
|---|---|---|---|---|
| 0 (tightest) | 4.4% | **31.2%** | 0.062 | +0.059 |
| 2 | 7.3% | 21.5% | 0.036 | +0.009 |
| 4 (widest) | 9.5% | **18.9%** | 0.028 | +0.068 |

ρ = −1.00, |t| = 4.91 — larger than anything else measured, and **entirely
mechanical**. A tighter stop puts the 2R target nearer, so it is reached more
often; in R terms nothing has changed, and expectancy shows no pattern at all.
It is also the reason the fixed test now scores **expectancy** rather than hit
rate, with hit-rate-only sorters reported separately.

Corrected results, all 22 conditioners testable, two-sided, against the control:

| conditioner | ρ hit | t hit | ρ R | ΔR | t(R) | control ΔR |
|---|---|---|---|---|---|---|
| rs_rank | +0.90 | **+4.15** | −0.50 | −0.002 | −0.03 | +0.074 |
| reversal_5d | +0.70 | **+3.34** | −0.20 | −0.028 | −0.38 | +0.093 |
| risk_pct | −1.00 | **−4.91** | +0.20 | −0.046 | −0.54 | −0.098 |
| market_regime | +1.00 | −1.39 | +1.00 | −0.192 | −1.23 | −0.143 |

**Conditioners that sort expectancy: none. Conditioners that sort hit rate only:
rs_rank, reversal_5d, risk_pct.** The two "timing signals" reported in the
original §2 were hit-rate sorters and are now correctly excluded.

`market_regime` also answers its own question. Only **281 of 5,609 setups (5%)**
occur with the benchmark below its 200-day average, because the universe screen —
rising 200-day MA, RS ≥ 70, price near the 52-week high — is *already* a regime
filter. There is almost nothing left for an explicit one to add.

## 5d. Base structure: the last place timing could live

Every conditioner above describes the **name** or the **market**. Name-level ones
cannot time a trigger — proven, because stacking them matched the control to the
decimal. Market-level ones are already inside the screen — proven above. What
remained untested was the shape of the base the price broke out of, which is
Minervini's actual claim: a sequence of progressively shallower pullbacks on
progressively lighter volume, breaking out of the tightest contraction.

Twelve features reconstruct it (`setups/vcp.py`): pullback count and depth
sequence, contraction ratio and slope, base depth, volume dry-up and volume
trend through the base, pivot tests, final tightness, prior leg, breakout
extension. Bar: two-sided p < 0.00278 on **expectancy**, |rank correlation| ≥ 0.7.

| feature | hit rates (low→high) | ρ hit | ΔR | t(R) | ρ R | control ΔR |
|---|---|---|---|---|---|---|
| final_tightness | 24 23 22 24 22% | −0.70 | +0.130 | +1.95 | +0.70 | −0.023 |
| volume_dryup | 21 24 22 24 24% | +0.41 | +0.131 | +1.76 | +0.80 | −0.004 |
| volume_trend | 21 24 23 25 23% | +0.30 | +0.131 | +1.67 | +0.90 | −0.003 |
| n_contractions | 23 22 23 31% | +0.80 | +0.163 | +1.44 | +0.20 | −0.012 |
| breakout_extension | 26 23 24 23 19% | −0.70 | +0.045 | +0.57 | +0.60 | −0.097 |
| contraction_ratio | 24 25 22 23 21% | −0.80 | −0.045 | −0.65 | −0.70 | +0.015 |

**Nothing clears the bar.** The largest is `final_tightness` at t = +1.95 against
a required ≈3.0, and with twelve features tested one at t ≈ 2 is exactly what
chance produces.

Three features did point the same way, which was tempting. It does not survive
two checks:

* **They are not three features.** `volume_dryup` and `volume_trend` correlate at
  **+0.92** — one measurement counted twice. Only `final_tightness` is distinct
  (ρ ≈ 0.17 with both).
* **The direction reverses out of sample.** A combined score built from the trio
  sorts expectancy at ρ = **−0.70** on dev and ρ = **+0.90** on the vault. A
  relationship that flips sign across the split is not a relationship.

There is one more thing worth stating plainly, because it contradicts the
premise the features were built from. The signs the data prefers are the
*opposite* of the folklore: expectancy rises with a **looser** final contraction
(ρ_R = +0.70) and with volume **increasing** through the base (ρ_R = +0.80/+0.90).
Weak, insignificant, and sign-unstable — but not evidence for the VCP story
either. Two earlier measurements said the same thing: breakout-day volume and
base tightness both correlate negatively with the hit rate.

**Per the stopping rule set in advance: base structure does not separate
triggers, so the breakout entry has no measurable timing value on this
universe.** The evidence already indicates what to do instead — the control,
which simply holds a qualifying name with the same stop and target, scored 34.3%
against the trigger's 31.3%.

## 5e. The setup strategy as a book, with a cap on concurrent positions

Everything above measures a setup in isolation — every qualifying trade taken,
none competing with another, answer returned as an average R-multiple. A real
account has finite slots. Capping them turns the study into a portfolio and
surfaces three things per-trade statistics cannot.

```bash
.venv/bin/python -m strategylab.setups.cli book
```

25,257 pullback setups, 1% of equity risked per trade, gross exposure capped at
100%, slot contention resolved either at random or by RS rank. Full period
2005-2026:

| cap | pick | CAGR | vol | Sharpe | max DD | gross | avg open | taken | take % |
|---|---|---|---|---|---|---|---|---|---|
| 1 | random | +1.5% | 4.7% | 0.33 | **−16.1%** | 15% | 0.9 | 249 | 1% |
| 3 | random | +2.0% | 8.2% | 0.28 | −25.4% | 43% | 2.8 | 753 | 3% |
| 5 | random | +2.8% | 11.1% | 0.30 | −36.0% | 72% | 4.6 | 1,265 | 5% |
| 10 | random | +4.8% | 12.3% | 0.44 | −50.6% | 91% | 8.4 | 2,218 | 9% |
| 20 | score | +9.2% | 12.1% | **0.79** | −44.5% | 91% | 8.8 | 2,393 | 9% |
| unlimited | either | +6.9% | 11.9% | 0.63 | −43.2% | 91% | 8.8 | 2,381 | 9% |
| **SPY** | | **+10.8%** | 18.4% | 0.65 | −55.4% | | | | |
| **hold-the-screen** | | **+10.4%** | 17.1% | 0.66 | −39.1% | | | | |

**1. The position cap and the risk per trade are the same knob.** At 1% risk
with a ~9% stop, each position is ~11% of the account, so the 100% gross cap
admits about **nine** positions. Caps of 20 and unlimited produce *identical*
books — same 2,381 trades, same 91% exposure, same everything. Above ten the cap
is inert, and "hold twenty names risking 1% each" is not a strategy that exists;
the arithmetic forbids it. Choosing a position count IS choosing a risk per
trade.

**2. Capacity, not opportunity, is the binding constraint.** The book can act on
**1-9%** of the 25,257 setups it finds. Whatever the setup edge is, most of it
is unreachable — a fact invisible in a per-trade study, where every setup counts
equally.

**3. Nothing beats holding the screen.** The best cell (cap 20, RS-ranked, Sharpe
0.79) is the only one above the benchmarks, and it does not replicate:

| cap | full: random | score | | dev: random | score |
|---|---|---|---|---|---|
| 3 | 0.28 | 0.19 | | 0.09 | **0.22** ← flips |
| 5 | 0.30 | 0.23 | | 0.28 | **−0.11** |
| 10 | 0.44 | **0.49** | | **0.64** | 0.07 ← flips |
| 20 | 0.57 | 0.79 | | 0.36 | 0.71 |

**Picking the "best" setups when oversubscribed is not reliably better than
picking at random**, and the ordering reverses between the full period and dev
at two of five caps. Which is what the rest of this study would predict: no
conditioner sorts setup expectancy, so there is nothing for a selection rule to
select on.

**What the cap does buy is risk.** At one position the book runs 4.7% volatility
and a **−16.1%** maximum drawdown against SPY's −55.4% — but on 15% average
exposure and +1.5% a year. That is not a strategy so much as a small position in
a strategy, and it is the same trade-off §5b of `MOMENTUM-UNIVERSE.md` found
from the other direction: on this universe the reliable product is lower
drawdown, and it is bought with exposure rather than with selection.

## 6. Limitations

- **Survivorship.** The delisted feed is page-capped at ~57 tickers against
  5,762 live listings. Breakouts in names that later failed are largely absent,
  which flatters the *real* setups more than the control (both are drawn from
  the same universe, so the differential is modest, but it is not zero).
- **One setup definition.** Base = 40-bar pivot high, stop = 10-bar pivot low,
  volume ≥ 1.3×. Those are stated, not searched, which keeps the multiplicity
  honest — but a null on this definition is not a null on every base pattern.
- **Daily bars.** The ambiguous-bar convention books the loss, which is the
  conservative choice and biases the hit rate down by a small amount.
- **119 monthly clusters.** Setups cluster in breakout waves, so month-clustered
  errors are the honest choice and they cost real power.
- **The stacked result in §4 is post-hoc**, and the vault figure there is a
  second use of the vault. Neither is a registered result.

## 7. Two bugs found

- **The breakeven arithmetic was wrong for a quarter of the sample.** S1
  originally compared the *unconditional* hit rate against a 1/3 breakeven that
  is only valid when every trade ends at a barrier — and 26% time out. The test
  was guaranteed to fail whatever the setup did. Amended before the full run to
  use P(target | resolved), with the resolution rate reported alongside.
- **A helper named `test_conditioners` was collected by pytest as a broken test**
  in every module that imported it. Renamed `conditioner_report`. Trivial, and
  the kind of thing that quietly turns a green suite red for the wrong reason.
