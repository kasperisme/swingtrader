# NRP Stage 1 — news repricing, traded directionally

**Verdict: the mechanism replicates. The trade has decayed to nothing.**

The pairs study established that announcements stop a spread converging — the
price moves to a new level and stays. Read the other way that is
post-earnings-announcement drift, so this tests whether the same repricing pays
directionally, on a construction that shares no code path with the pairs work.

Two findings, and they point opposite ways.

**The mechanism is confirmed, independently.** In the liquid tiers the
*control* — a large abnormal move with no announcement anywhere near it —
reverts hard, with decile slopes of −0.81 (mid) and −0.93 (large). Real
announcements do not revert. That is exactly the FDP taxonomy in single-name
directional returns: transient shocks decay, information repricings do not.
The asymmetry is +1.69pp over 21 days on dev (t = +3.01) and +3.10pp in
1998-2013 (t = +4.14).

**The trade is gone.** Post-announcement drift is monotone across every
liquidity tier before 2014 (Spearman +0.69 to +0.77, whole-panel +0.806) and
absent after it (whole-panel −0.030 on 2014-2023, +0.006 on the 2024-2026
vault). Nothing survives costs, in any tier, in either recent era.

Run: 146,722 announcements and 143,946 day- and tier-matched pseudo-events over
2,130 names, 1997-2026; dev 63,618 events.
Artifacts: `output/news/nrp/{nrp.json, preregistration.json, events.csv.gz, pseudo_events.csv.gz}`
Reproduce: `.venv/bin/python -m strategylab.news.cli nrp` (~24 s).

---

## 1. The registered result

Surprise is the abnormal return over [D−1, D+1], standardised by the stock's own
pre-event volatility; the outcome starts at D+2 and is filled at the open.
Deciles are cut from a **trailing** 12 months of announcements, recut monthly,
so an event is never sorted against announcements that had not happened yet.
Inference is clustered on calendar month. Bonferroni divisor 18.

| test | dev 2014-2023 | t | pass |
|---|---|---|---|
| P1 drift monotone in the surprise | Spearman −0.030 | — | no |
| P2 top-minus-bottom spread, gross | −0.175% | −0.66 | no |
| — same spread on pseudo-events | −0.713% | −2.55 | — |
| N1 **excess** over pseudo-events | +0.494% | +1.46 | no |
| N2 shuffled labels (must be null) | +0.092% | +0.42 | **yes** |
| E1 spread net of costs | −0.695% | −2.62 | no |
| E2 long-only top decile, net | −0.144% | −0.60 | no |

The whole-panel P2 is robust to how thin months are handled: −0.19% at
`min_per_cell` 1, −0.05% at 10, −0.07% clustering by quarter instead of month.
There is no version of the statistic in which it is positive.

## 2. The decay, which is the actual result

Whole-panel decile monotonicity, same code, three eras:

| era | events | Spearman | gross spread | excess over control |
|---|---|---|---|---|
| **1998-2013** | 65,379 | **+0.806** | +0.53% (t +1.87) | **+1.80% (t +4.79)** |
| 2014-2023 (dev) | 63,618 | −0.030 | −0.18% (t −0.66) | +0.49% (t +1.46) |
| 2024-2026 (vault) | 17,725 | +0.006 | +0.53% (t +1.22) | +0.36% (t +0.56) |

By tier, the collapse is total everywhere the money could actually go:

| tier | 1998-2013 Spearman | 2014-2023 Spearman | dev events |
|---|---|---|---|
| T1 micro, ADV < $1M | +0.709 | **+0.867** | 2,873 |
| T2 small, $1-10M | +0.758 | −0.430 | 13,417 |
| T3 mid, $10-100M | +0.770 | −0.345 | 31,325 |
| T4 large, > $100M | +0.685 | +0.394 | 16,000 |

PEAD survives in exactly one place: names trading under $1M a day, where a
26bp round trip is optimistic by an order of magnitude and 2,873 events over a
decade cannot carry a strategy. This is the textbook decay — the anomaly was
documented in 1968, published widely through the 1990s, and is now visible only
where it cannot be harvested.

Note the hypothesis this refutes. The premise for running the study at all was
"go where the friction is small relative to the move." The friction *is* small
relative to a multi-percent announcement move — and the move is no longer
predictable, which is a different problem and not one costs can fix.

## 3. The mechanism, which replicated

The pre-registered N1 test asks whether announcements beat their own control.
It fails on dev. But the reason it fails is worth more than a pass would have
been: **the control is not zero, it is strongly negative.**

Decile means of the 21-day market-hedged return, dev 2014-2023:

| tier | real announcements | pseudo-events (control) |
|---|---|---|
| T3 mid $10-100M | Spearman −0.345 | **−0.806** |
| T4 large > $100M | Spearman +0.394 | **−0.927** |

A large abnormal move with no announcement within ±20 sessions reverts, cleanly
and monotonically. The same-sized move *with* an announcement does not. That is
the FDP result — regime L decays, regime N reprices — arrived at through an
entirely different construction, on single names rather than spreads, using
returns rather than convergence.

Two independent programmes, same taxonomy. That is the most durable thing this
project has produced.

## 4. The post-hoc trade, and why it is not one

Fading the extreme mover only when no announcement is near it, long the bottom
decile and short the top, 21 days, market-hedged:

| era | tier | fade no-news | fade news | asymmetry | t | net of 52bp |
|---|---|---|---|---|---|---|
| 1998-2013 | T4 large | +1.68% | −1.42% | +3.10% | +4.14 | +1.16% |
| 1998-2013 | T3 mid | +0.78% | −0.30% | +1.08% | +2.56 | +0.26% |
| dev 2014-2023 | T4 large | +1.34% | −0.35% | +1.69% | +3.01 | +0.82% |
| dev 2014-2023 | T3 mid | +0.72% | +0.07% | +0.65% | +1.58 | +0.20% |
| **vault 2024-2026** | T4 large | +0.41% | −0.13% | **+0.55%** | **+0.58** | −0.11% |
| **vault 2024-2026** | T3 mid | −0.06% | −0.18% | +0.12% | +0.18 | −0.58% |

**This was NOT pre-registered.** It was found by looking at a control, which is
the exact situation that manufactures false discoveries, and it is reported as
a hypothesis with numbers rather than as a result. Three things keep it from
being a strategy:

1. **The vault does not confirm it.** t drops from +3.01 to +0.58.
2. **Only 51% of dev months are positive** on the net series. A +0.82% mean with
   coin-flip hit rate is a handful of large months, not an edge.
3. It is short-term reversal, one of the most heavily traded anomalies in
   existence, and the decay from t = +4.14 (1998-2013) to +3.01 (2014-2023) to
   +0.58 (2024-2026) is what being arbitraged away looks like.

Also recorded: this is a **second use of the sealed vault**, the first being the
registered era report. A holdout tested repeatedly is a training set, and the
next use of it should be treated as the last.

## 5. Two bugs found, both pinned

**One unadjusted corporate action moved a decile mean by 6.6 percentage
points.** The first full run reported decile 4 at +6.37% against ~0.3%
elsewhere, and a pseudo-event spread of +13.9%. The cause was 59 observations
with |21-day return| above 200% — QUBT at +39,900%, WSE with five separate 100x
moves — which are broken adjustment factors, not prices. Returns are now
winsorised at 1%/99% with thresholds cut on the **pooled** real-plus-pseudo
sample, so the control can never be trimmed differently from the thing it
controls for. `test_winsorisation_is_symmetric_and_tames_a_corporate_action`
reproduces it.

**Thin months flipped the sign of the headline statistic.** Earnings cluster
into four seasons, so off-season months carried one or two announcements per
decile, and a "decile mean" from one observation produced spreads of ±17%.
Month-equal-weighting then reported −0.30% where the pooled figure was +0.49%,
decided by three months holding one or two events apiece. Months now need five
announcements in each extreme decile, matching the rule the pairs study already
applied, and the sensitivity to that threshold is reported rather than chosen.

## 6. What was NOT tested

- **SUE.** The surprise here is the announcement-window return, not
  standardised unexpected earnings. Brandt et al. (2008) find the return
  measure predicts drift better, but they are not the same variable and only
  one was tested.
- **The proprietary NIS news scores.** They start in 2025 — long enough for the
  vault window, nowhere near long enough for the dev test. That is the obvious
  next discriminator and it is data-blocked, not idea-blocked.
- **Non-earnings news.** Guidance, M&A, analyst days, 8-Ks. The FDP study found
  the same limitation; the announcement flag is a strict subset of "news".
- **Short-leg feasibility.** E2 exists because a retail account often cannot
  short the bottom decile at all. It fails on its own, so the question of
  whether the short leg is borrowable never arose.

## 7. Limitations

- **Survivorship, and it cuts toward optimism here.** The delisted feed is
  page-capped at ~57 tickers against 5,762 live listings. Firms that announced
  badly and then failed are largely absent, which flatters the bottom decile and
  therefore *understates* the long-short spread. The direction is safe; the
  magnitude is not trustworthy.
- **Announcement timing is inferred, not known.** FMP gives a date, not whether
  the release was before the open or after the close. The [D−1, D+1] window
  contains the reaction either way, which is why it is used, but it also means
  the surprise absorbs one extra session of unrelated return.
- **Deciles are cut on a pooled cross-section**, so a micro-cap's 2σ surprise
  and a mega-cap's 2σ surprise land in the same bucket. The tier table exists
  because of this, not despite it.
- **Costs are a flat 13bp per side.** Realistic for T4, optimistic for T3, and
  fantasy for T1 — which is precisely the tier where the effect survives.
- **117 monthly clusters** on dev. The clustered standard errors are the honest
  choice given events overlap heavily in earnings season, and they cost real
  power.

## 8. What this changes

The programme now has three consecutive negatives — flow inertia, pairs
convergence, announcement drift — and one finding that has replicated twice
across unrelated constructions: **news-driven moves reprice, non-news moves
revert.**

That asymmetry is not tradeable at retail cost on daily bars in liquid US
equities. Every version of it measured here decays across eras and dies in the
2024-2026 vault. What it is good for is **conditioning**: it is a veto, worth
having as one input among many, and it is exactly the shape of thing that adds
value inside a blend and none at all standing alone.

The honest read on where to go next is that the constraint is no longer
methodology. The harness is now good enough to kill an idea in a day — three
pre-registered studies, matched nulls, sealed vaults, and it has caught a
manufactured-reversion artefact, two data-quality contaminations and a
look-ahead in pair formation. What it lacks is an input with genuine
information advantage. The NIS news pipeline is the only candidate in this
project, and it does not have enough history yet to test. Waiting for that data
to accumulate is a more sensible use of the next year than a fourth statistical
anomaly.
