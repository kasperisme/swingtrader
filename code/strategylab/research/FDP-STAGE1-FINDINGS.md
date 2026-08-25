# FDP Stage 1 — Flow-Discriminated Pairs, the news axis

**Verdict: the discriminator works. The thing it discriminates does not exist.**

> **Updated after Step 1 (2026-08-20).** The original conclusion was "the
> discriminator works, the substrate does not pay." Step 1 — re-anchoring, §8 —
> settles the stronger question. Under a frozen anchor these spreads converge
> *below* a driftless random walk; under a rolling anchor they converge exactly
> as often as random walks pushed through the same rolling anchor (excess
> −0.0pp, t = −0.03). There is no daily-frequency mean reversion here to
> condition on. **Per the pre-registered rule, the reversion line is closed.**

Divergences with no earnings announcement on either leg converge materially more
often than divergences with one — +4.97 percentage points on dev (t = 3.69,
clears Bonferroni), and +8.02pp on the sealed 2024-2026 vault (t = 6.25). Both
falsification tests are null. That is a clean EGJ replication on the news axis
and it is the positive control the flow-inertia Stage 1 never had.

The pre-registered verdict still reads **NOT REPLICATED**, because P0 — the
sanity gate requiring the unconditional convergence rate to exceed 50% — failed
at 28.3%. The threshold was a guess written before the data was touched and it
has not been moved. What matters is *why* it failed, and that turns out to be
the finding: **the mean reversion these pairs are selected for does not survive
the formation boundary.** The formation OU fits implied 89.4% convergence within
60 days; 29.0% was realised, a −60.4pp gap at t = −36.

So the taxonomy is real and the substrate is not. Conditioning on news improves
the sort of a book whose base rate has decayed to roughly zero after costs.

Run: 20 non-overlapping 6-month trading windows (2014-01 → 2023-12), 4,776
cointegrated pairs over 1,152 names, 5,260 divergence events at |z| > 2; vault
2024-01 → 2026-06, 1,497 pairs, 1,675 events.
Artifacts: `output/pairs/h1/{h1.json, h1.md, preregistration.json, events_dev.csv.gz, events_vault.csv.gz, pairs_dev.csv.gz, charts/}`
Reproduce: `.venv/bin/python -m strategylab.pairs.cli h1` (~17 s).

---

## 1. The result, in one table

Every number is a difference of window-level means across 20 windows, clustered
on the trading window. Bonferroni divisor 9 → the one-sided bar is p < 0.00556.

| pre-registered test | L (no news) | N (news) | diff | t | p | |
|---|---|---|---|---|---|---|
| H1a convergence rate (z crosses 0 ≤ 60d) | 29.74% | 24.77% | **+4.97pp** | +3.69 | 0.0008 | **PASS** |
| H1a_soft reversion halfway (\|z\| < 1 ≤ 60d) | 54.43% | 46.18% | **+8.24pp** | +4.58 | 0.0001 | **PASS** |
| H1b net return per event | +0.11% | −0.19% | +0.30% | +1.34 | 0.098 | fail |
| H1c restricted mean time to converge | 51.4d | 53.0d | **−1.60d** | +3.82 | 0.0006 | **PASS** |
| H1d break rate (unconverged at 60d) | 70.26% | 75.23% | **+4.97pp** | +3.69 | 0.0008 | **PASS** |
| F1 placebo labels (must be null) | 28.01% | 29.39% | −1.38pp | −1.07 | 0.298 | **PASS** |
| F2 stale announcements (must be null) | 27.47% | 29.34% | −1.87pp | −1.38 | 0.184 | **PASS** |
| F3 common news behaves like L | 28.19% | 23.99% | +4.20pp | +1.13 | 0.136 | pass (dir.) |

**H1d is not independent evidence.** The break rate is 1 − convergence rate, so
it is H1a restated; it is reported because it was registered, and it should be
read as one result, not two.

**The vault confirms.** Run once, after the dev verdict was fixed, never allowed
to overturn it: H1a diff **+8.02pp, t = +6.25** over five windows. Direction and
magnitude both hold on data the design never saw.

---

## 2. Why P0 failed — the substrate, not the discriminator

Two diagnostics were registered before the run precisely so that a P0 failure
could be diagnosed instead of argued about.

**D1 — the formation fits contradicted themselves out of sample.** Each pair
arrives with a formation-estimated half-life, which pins an OU process with
κ = ln2/h and unit stationary variance. Simulating that process forward from
each event's own entry z gives the convergence rate the fit implied:

| | implied by the formation fit | realised |
|---|---|---|
| all divergences | 89.4% | 29.0% |
| L bucket | 89.5% | 30.4% |
| N bucket | 89.2% | 25.2% |

−60.4pp, t = −36.0 across windows. Roughly two thirds of the estimated mean
reversion is gone the moment the formation window closes. Note the gap is
slightly *wider* in the N bucket, which is the direction H1 predicts.

**D2 — and it is not an estimation problem.** If the cointegrating relationship
still held and only the hedge ratio were mismeasured, the algebra is exact:

    E_T[s] − E_F[s] = (β* − β) · (E_T[x_B] − E_F[x_B])

The level drift would then have to scale with how far leg B travelled between
the two windows. Measured across 4,776 pairs, mean |drift| is 1.62z and its
correlation with leg-B travel is **+0.030**. The mechanism is ruled out. The
relationship itself breaks; no better estimator recovers it.

**The selection is also thin.** Across dev, 116,215 within-industry candidate
pairs yielded 14,260 rejections of the unit-root null at α = 0.05, against 5,811
expected by chance — a 2.45× enrichment. Real, but it means roughly 41% of the
"cointegrated" book is expected to be spurious before any trading begins. That
is an inherent property of screening ~6,000 pairs per window and it depresses
the convergence rate directly.

**Where the base rate does behave.** Sorting on the formation half-life — a
formation-only quantity — is monotone and sensible: fast-reverting pairs
converge 33.2%, mid 30.2%, slow 23.4%. The estimates carry information. They
just carry much less of it than they claim.

---

## 3. Does the L bucket trade?

The spec's consolation prize is that "even in failure you have a working
L-bucket pairs book." Tested directly, one-sample, clustered on windows:

| L bucket alone | per event | t | 95% CI |
|---|---|---|---|
| gross return | **+0.373%** | +2.55 | [+0.10%, +0.64%] |
| net return | +0.113% | 0.77 | [−0.16%, +0.38%] |
| convergence rate | 29.74% | 19.7 | [27.1%, 32.8%] |
| events per year | 381 | | |

**Gross-positive, net-indistinguishable-from-zero.** The edge is 37bp per event
and the round trip costs 26bp — commission, slippage and half-spread on both
legs, in and out, at the same rates the equity book is charged. Costs eat
roughly 70% of it.

Read `charts/bucket_pnl.png` with the numbers above, not off the axis. That
curve pools every event, which upweights the windows that generated the most of
them — and on this panel those are also the better windows, so the pooled mean
(+0.239% per event) is roughly double the window-clustered one (+0.113%). The
clustered figure is the one inference uses and the one quoted here.

The N bucket is +0.07% gross and −0.19% net: correctly identified as the bucket
not to trade, but skipping it does not rescue the book, because the L bucket was
not paying enough either.

On the vault the unconditional book is outright negative (−0.24% gross, −0.50%
net per event) while H1a's *discrimination* is at its strongest. The two facts
are not in tension — the sort works while the level decays, which is exactly
what Do & Faff report for unconditional pairs.

**Not modelled, and it matters:** borrow. The short leg of a crowded divergence
is often hard to borrow at hundreds of bps. Every net number here is an upper
bound. The L−N *difference* is far less exposed, since both buckets short.

---

## 4. What the mechanism looks like

`widening_by_regime` measures how much further the spread stretched after the
divergence before it turned:

| | mean further widening | mean max adverse z |
|---|---|---|
| L | 1.66z | 3.89 |
| N | 1.57z | 3.97 |

Essentially identical. **N-regime divergences do not widen more — they simply do
not come back.** That is the "new equilibrium μ′" branch of the spec's §3 table
and not the continued-pressure branch, which is the right shape: continued
pressure is the *flow* prediction (H3), and no flow was measured here.

F3 points the same way. News on **both** legs (common information) converges at
28.2%, close to the L bucket's 29.7%; news on **one** leg (idiosyncratic
information) converges at 24.0%. Only 331 both-leg events, so t = 1.13 and it is
directional evidence at best — but it is the sign EGJ's story requires, and a
mechanism check that came out backwards would have been damaging.

---

## 5. Three bugs found, all pinned

**A single Saturday bar cost an entire vault window.** The panel's date index is
the union of every symbol's dates, so one vendor bar for BEP on 2025-11-08 (a
Saturday) made all 2,105 other names NaN on that row. Pair formation needs a
jointly complete price matrix, so every formation window containing that row
returned **zero** candidate pairs from 1,476 eligible names — silently, as a
plausible-looking empty book. `drop_non_sessions()` now filters weekday-and-
density, logs what it dropped, and
`tests/test_pairs.py::test_non_session_row_empties_formation_without_the_filter`
reproduces the failure and the fix.

**Inverting an OLS hedge ratio is wrong, and that is why both directions are
fitted.** Regressing B on A returns the forward slope attenuated by R², so
1/β_BA ≠ β_AB whenever the spread carries real variance. This first showed up as
a failing test whose *assertion* was wrong, not whose code was. Engle-Granger is
direction-dependent for the same reason, which is why `form_pairs` fits both
orientations and keeps the stronger.

**A null that was not matched to the thing it was the null for.** In Step 1 the
rolling-β anchor (A2) was initially scored against the fixed-β null, because the
null builder anchored a spread it had already constructed with a static hedge
ratio. That reported A2 at −35pp when the honest comparison had not been made.
It happened to point the same way once fixed, which is exactly why it was
dangerous — a mismatched control that flatters or damns by accident is
indistinguishable from a result until someone checks.
`test_rolling_beta_null_is_matched_to_the_rolling_beta_anchor` asserts the two
nulls differ.

A fourth property is worth stating even though it is not a bug: at 504
observations the hedge ratio carries visible sampling error (sd ≈ 0.12 on a true
1.75 in simulation — a 7% typical miss). D2 shows this is *not* what drove the drift here, but it is
pinned as a test so that if the estimator ever tightens, the attribution gets
revisited.

---

## 6. What was NOT tested

The spec's build order runs 1 → 5. This covers steps 1 and 2 only.

| hypothesis | status |
|---|---|
| H1 news axis | **tested** — discriminator replicates; P0 substrate fails |
| H2 flow axis (ρ_φ, deceleration entry) | **not tested** — needs 13F breadth differentials or reconstitution dates; neither is wired up |
| H3 inertia timing (widening ∝ ρ_φ) | **not tested** — same dependency. §4 records the baseline widening it would have to beat |
| H4 ownership-overlap prior | **not tested properly** — see below |

**Regime F was never identified.** Every event here is L or N. A three-way split
was not run and is not claimed.

**H4's buildable half points the right way but cannot be believed.** Sorting
events by ETF-ownership overlap between the legs gives convergence 27.9% / 28.0%
/ 31.5% / 33.1% across quartiles — monotone in the last three, in the direction
Anton-Polk implies. But `etf-stock-exposure` is a **current** snapshot, not
historical, so this sort carries look-ahead and is reported for direction only.
It is not evidence.

**The EGJ "puke rule" was not tested cleanly.** Net return by time-to-
convergence is flat (+7.5% at 0-5 days, +7.7% at 40-61 days), but that is
conditional on having converged and so is a selected sample; it says nothing
about whether abandoning slow spreads helps.

---

## 7. Limitations that bear on this result specifically

- **Survivorship, and it is worse here than for a long-only book.** The FMP plan
  page-caps the delisted feed at ~57 tickers against 5,762 live listings. The
  classic pair-breaking event is a **merger** — an acquired leg is exactly a
  name that leaves the panel, and it is also exactly an N-regime event. Those
  events are largely absent, which almost certainly *understates* the L−N gap.
  Safe direction, but the magnitude is not trustworthy.
- **Earnings ⊂ news.** The discriminator uses scheduled announcements only.
  Analyst days, supplier news, guidance and M&A rumour land in the L bucket.
  Again the safe direction: leakage makes L look more like N.
- **Announcement coverage is 100%** of the 1,152 traded names, enforced by
  `require_earnings_coverage`. Partial coverage would have manufactured H1 —
  names with no data can only ever land in L.
- **Sector/industry labels are current, not point-in-time**, so pair formation
  has a mild look-ahead in *which* names are candidates for each other.
- **Daily bars, opens for fills.** Signals on the close of t, fills at the open
  of t+1, both legs, no forward-filling of missing prices.
- **20 clusters.** Window-level inference is the honest choice given that pairs
  overlap heavily by construction, and it costs a lot of nominal power. H1b's
  failure at t = 1.34 is as likely to be power as absence.

---

## 8. Step 1 — re-anchoring, and the close-out

D2 said the spread's *level* moves and that it is not hedge-ratio error. The
obvious repair is to stop anchoring on a mean frozen for six months and
re-anchor continuously — which is the real difference between 1990s pairs
trading and modern statistical arbitrage, more so than the choice of hedge.

**The repair is also a trap, and it is the Stage-1 trap wearing a new hat.**
Subtracting a trailing mean makes anything oscillate around zero. A pure random
walk, demeaned on a rolling 60-day window, crosses zero constantly. So every
anchor is scored against random walks pushed through *that same anchor* and the
same cointegration and half-life screens. Only the excess counts.

Reproduce: `.venv/bin/python -m strategylab.pairs.cli anchor` (~27 s).
Artifacts: `output/pairs/anchor/{anchor.json, preregistration.json, events_*.csv.gz}`.

**G0, the validity check.** For the frozen anchor the simulated null (31.6%) and
the analytic driftless first-passage rate (32.9%) agree. Two completely
different routes to the same number, so the simulation that scores every other
anchor is not itself broken.

| anchor | events | realised | matched null | excess | t | windows + |
|---|---|---|---|---|---|---|
| A0 frozen | 5,259 | 28.7% | 31.6% | **−3.5pp** | −2.35 | 4/20 |
| **A1 rolling 60d** (primary) | 12,163 | 81.8% | 81.3% | **−0.0pp** | **−0.03** | 11/20 |
| A2 rolling 60d + rolling β | 8,646 | 45.5% | 80.1% | −35.3pp | −33.93 | 0/20 |
| A3 rolling 120d | 7,866 | 56.0% | 56.8% | −1.2pp | −1.11 | 9/20 |

**Read the A1 row.** A rolling anchor reports 81.8% convergence — nearly three
times the frozen design's 28.7%, and it would have looked like a spectacular
repair. It manufactures **81.3% of it out of pure random walks.** The excess is
zero to two decimal places. Every anchor is at or below its own null.

A2 is worth a line: re-estimating β on a trailing window makes things
dramatically *worse*, not better. Its own matched null is 80.1% and it delivers
45.5%. Rolling hedge-ratio noise injects level shifts that a 60-day demeaning
cannot keep up with — consistent with D2, which had already ruled out
hedge-ratio error as the *cause* of the drift.

**A power note against myself.** A 400-name smoke run showed A1 at +3.0pp,
t = +2.47 — enough to look like a result. The full 1,988-name panel put it at
−0.0pp. The smoke number was noise, and it is recorded here because it is
exactly the kind of number that gets reported when a study stops at the first
encouraging run.

**The loophole, closed.** Real pairs carry stronger in-sample cointegration
evidence than the null's marginal survivors (median ADF −3.82 vs −3.58), and
convergence does rise with ADF strength in the real book (+5.9pp strongest over
weakest). That looks like surviving edge. It is not: the same gradient is
*larger* in the null (+8.6pp), because selecting on a more negative in-sample
ADF selects spread paths that happened to oscillate, and that persists briefly
even for random walks. Post-hoc, frozen anchor:

| in-sample cointegration | real | null | excess |
|---|---|---|---|
| Q1 strongest (ADF −4.52) | 32.3% | 35.3% | −3.1pp |
| Q2 | 29.0% | 32.2% | −3.1pp |
| Q3 | 27.3% | 29.8% | −2.5pp |
| Q4 weakest (ADF −3.43) | 26.3% | 29.2% | −2.8pp |

Flat, and negative everywhere. There is no sub-population that escapes. (This
check was **not** pre-registered; it was run to see whether a loophole rescued
the result. It cannot manufacture a null, only fail to overturn one.)

**And the discriminator still separates.** Under A1 the news split survives at
L 81.8% vs N 80.0%, t = +2.56 — real, and now clearly measuring which
divergences are *less unlike* a random walk. It sorts a distribution with no
edge in it.

---

## 9. What this changes

The pre-registered recommendation, generated by the decision rule, is *do not
build the flow axis*. Read literally that is driven by P0, and P0 failed on a
guessed threshold. The defensible reading is narrower and more useful:

**The discrimination machinery is validated and the pairs substrate is not.** A
flow-axis study built on this panel would inherit a base asset that is
gross-flat, net-negative, and whose estimated mean reversion evaporates at the
formation boundary. H2 could be *measured* on it — the forward-control structure
is sound and the L/N result proves the design can detect a real effect — but a
positive H2 would be a sort improvement on a book with nothing to sort.

Two things would change that, in order of cost:

1. **Fix the substrate before adding the axis.** The convergence base rate is
   set by pair quality, and D2 says the binding constraint is relationship
   stability, not estimation. Shorter formation windows with more frequent
   refitting, a stability screen across sub-periods, or a stricter α would all
   attack it directly and are cheap to test with the machinery now in place.
2. **Get the delisted feed.** M&A is the dominant pair-breaking event and it is
   missing. That is the single largest identified distortion in this result.

**Step 1 answered the question it was built to answer, and the answer was no.**
The pre-registration named the conclusion in advance: if the primary anchor
fails, close the line rather than try a further anchor. It failed at t = −0.03.
Both remaining routes are now unattractive for the same reason — a factor-
residual book (Step 2) would cut spread volatility ~18% and halve hedge costs by
netting across positions, but it operates on the same universe at the same
frequency, and there is nothing here for those improvements to improve. The
gross edge was 37bp against a 26bp round trip *before* the null showed the
convergence itself was not real.

What this leaves behind is worth more than the strategy would have been: a
validated discriminator, a simulated-null harness that catches manufactured
mean reversion, three pinned bugs, and a negative result that is general rather
than specific — it holds for a frozen anchor against an analytic benchmark, for
rolling anchors against their own matched nulls, and across every quartile of
cointegration strength. Stage 1's null left nothing behind. This one leaves the
machinery to kill the next idea faster.
