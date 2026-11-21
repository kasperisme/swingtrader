# Drawdown Recon: spec v0.3 (2026-11-21)

Status: **DRAFT.** Built so far: the point-in-time snapshot collector (§12, step 1).
Everything else is design.

Review history: v0.1 → one design review → v0.2 → council round 1 (quant
researcher, macro historian, swing trader, risk manager, ML evaluation; all VALID
WITH CHANGES) → v0.3 after council round 2 (all VALID WITH CHANGES again).

v0.2 settled the shape:
- the proof comes from history (§9.1); the live ledger is out-of-sample only
- the output is trade plans in a risk-capped book, not ranked lists
- the regime check separates flush from bust
- resilient leaders unlock first and beaten-down quality names enter on repair
- bucket D is dropped as a long
- labels are judged on accuracy against blind gold labels
- one labelling model, not a cascade

v0.3 fixes what round 2 found in the numbers:

1. **The history test passes only on excess return vs a matched control, with episodes as units.**
   No episode is excluded; survivorship gets bounds instead (§9.1).
2. **The regime has two axes.** *Stress* (credit, VIX, yen) sets systemic/deleveraging
   and sizing. *Damage* (revisions, capex, epicenter trend, real yields) decides
   flush vs bust. A single score scored April 2025 as a bust and 2022 as a flush (§5).
3. **Downgrades bind the book.** Positions are cut to the new cap. There is an episode
   loss breaker, and stage 3 is capped at 55% until the bear switch is ruled out (§6).
4. **B gets a growth gate, a real base definition and volume-confirmed entries.**
   Without them B fills with low-beta defensives (§7.1).
5. **Sizing is min(risk size, per-name cap, remaining gross)**, with an open-risk cap,
   a fill model, a time stop and an earnings-hold rule (§8).
6. **The label test uses human-only gold on ~150 names** and runs only after A passes
   the history test (§9.2).
7. **The collector fails closed** (run manifest, non-zero exit, US/Eastern date, no
   back-dating, falling names stay tracked). Built (§12).

## 1. Why

2026-11-20 close: SPY −11.5% from its high (689.81), QQQ −19.9%, IWM −9.7%, RSP
−7.1%. Friday alone: SPY −3.6%, QQQ −5.7%. SPY/RSP drawdown ratio 1.62 → a
**concentrated** unwind (mega-cap / AI / semis).

Question: where are the buying opportunities now and in the recovery, and how do
we know the method works?

Non-goals: calling the bottom; placing orders; social creatives.

**What v1 can and cannot show.** One episode gives an effective N of about 5
independent bets. The live minimum detectable effect is about 10–13% excess per
20 sessions, against a plausible edge of 2–5%. The live ledger can falsify an idea
or come back inconclusive; it cannot prove an edge. Proof comes from §9.1.

## 2. Design principles

1. **Deterministic first.** Code computes; a model labels text and never does arithmetic.
2. **Point-in-time or labelled as not.** Every input carries an as-of timestamp ≤
   the call time. Anything that cannot be rewound is marked `not_backtestable`.
3. **Fail closed.** Stale or missing inputs remove names or block the snapshot. They
   never fall through to defaults (§10).
4. **Seal before the outcome, grade from the next open.**
5. **Research, not advice.** Publication is gated on evidence (§11).

## 3. Data inventory (verified 2026-11-21)

| Source | Use | Freshness | Status |
|---|---|---|---|
| FMP EOD prices | drawdowns, breadth, RS, sector/epicenter ETFs | live | OK |
| FMP analyst estimates | revisions (flush vs bust, damage ex-post check) | current only | **snapshotted daily from 2026-11-21** (`drawdown_estimate_snapshots`) |
| FRED: HY OAS, DFII10, DGS2, DGS10, NFCI, DTWEXBGS, VIXCLS; FMP USDJPY | macro regime | live | **snapshotted daily** (`drawdown_macro_snapshots`) |
| FMP earnings + economic calendar | earnings blackout, FOMC | live | to wire |
| `news_articles` + `news_impact_heads` | label evidence | ~510/day | OK; filter `has_analysis IS NOT FALSE`; use ingest time for as-of |
| `ticker_sentiment_heads` | descriptive sentiment change | live | OK; scores sector articles too, so not used as an own-news proxy |
| `ticker_relationship_edges` | epicenter exposure (avoid flag) | daily | OK; edges are news co-mentions, not disclosed customer links |
| `market_screening_result_rows` | stage-2 / fundamentals / insider boards | 2026-11-20 | OK; history only from 2026-05 |
| `research_priced_in` | bucket C (`median_gap`) | batch bug fixed 2026-11-21 | confirm rows land before use |
| `ticker_pair_stats` | pairs | calibrated 2026-06-15 | out of v1 |
| `company_vectors` | — | 2026-04-29 | do not use |
| Short interest | squeeze risk | — | missing; flagged, not screened |
| FMP `historical-sp500-constituent` (change log) | point-in-time S&P 500 membership for the historical study | live | available; membership rebuilt by walking the log backwards |
| Delisted names' price history | survivorship | — | **gap:** the plan page-caps the delisted feed (~57 names) and returns no bars for e.g. LEH. Measured per episode, see §9.1 |

## 4. Architecture

```
FMP / FRED ──► snapshots.py (daily, BUILT) ──► Supabase snapshot tables
                                                 │
FMP + Supabase ──► Phase 0 regime ──► Phase 1 features ──► code prefilter (~200)
                       │                                        │
                       │                              labeller (1 model, 3 samples)
                       │                              + Jev shadow + code-only arm
                       ▼                                        ▼
                 stage machine ◄────────────────────── buckets (B family, A, C later)
                       │                                        │
                       └──────► trade plans + portfolio risk block
                                        │
                          health gate (status=complete) ──► snapshot.json/md
                                        │                          │
                                  seal (drawdown_calls)     Opus memo (Claude Code skill)
                                        │
                                  grade (trades, R, MAE)
Historical study (strategylab PIT backtester, code-only rules) ──► go/no-go for publication
```

Layout: `services/drawdown/{cli,config,snapshots,regime,features,label,buckets,
stages,plans,risk,health,seal,grade,history}.py`. Reuse
`screener/technical.py` (`get_market_direction`, `_compute_buy_point`, ADR,
`vol_contracting_in_base`, `get_change_prices` for universe-wide RS) and the
trend-radar `GENERIC_TAGS` list. Do not re-implement them.

## 5. Phase 0: regime

**Inputs:** SPY, QQQ, IWM, RSP, DIA, SMH, the 11 sector SPDRs, the epicenter
basket, breadth over the liquid universe, and the macro snapshots.

**Epicenter** = the sector, ETF or tag cluster whose share of SPY's drawdown most
exceeds its index weight (contribution ÷ weight). This is used because
mega-cap tech is ~35–40% of SPY and would "contribute 40%" in almost any selloff.
The basket is that group's 20 largest names. Tags exclude `GENERIC_TAGS` and
`securities_litigation` / `class_action` / `investor_rights`.

**Two axes, scored separately in code.**

| Axis | Components (each −1 / 0 / +1) | Sets |
|---|---|---|
| **Stress** | credit spread 20d change (HY OAS live; BAA10Y in history, see §9.1) · VIX level · USDJPY 10d change | `systemic` / `deleveraging` labels, stage-0 sizing |
| **Damage** | epicenter FY+1 EPS revision breadth over 20 sessions (snapshots) · hyperscaler capex guidance (manual, logged) · epicenter below a falling 200d for ≥ 20 sessions · 10y real yield +75bp over 60 sessions | `flush` (damage ≥ +1) / `bust` (≤ −1) / `undetermined` |

Panic alone (wide spreads, high VIX, a yen squeeze) can no longer read as a bust.
A bust needs evidence that the epicenter's earnings or valuation regime is breaking.
The price arm (below a falling 200d) means the damage axis cannot lag price for
long in a real bust (2000, 2022).

**Primary label**, with precedence deleveraging > systemic > concentrated > rotation:

| Label | Rule |
|---|---|
| `deleveraging` | USDJPY 10d ≤ −4%, or VIX intraday ≥ 45, or VIX close ≥ 35 with the credit 5d change ≥ +50bp. Aug 2024 closed at 38.6 and spiked intraday to the 60s |
| `systemic` | stress ≤ −2 AND RSP dd ≥ 0.8 × SPY dd |
| `concentrated` | SPY dd / RSP dd ≥ 1.4, or epicenter contribution ÷ weight ≥ 1.5 |
| `rotation` | SPY dd < 8% while the epicenter dd ≥ 15% |

Labels may migrate (Oct→Dec 2018, 2000→2001). Every change is logged.

**Bear switch.** It fires when either of these holds for 3 consecutive closes, and
turns off after 10 consecutive closes without either:
- epicenter index (QQQ or SMH) dd ≤ −20% AND damage ≤ 0
- SPY dd ≤ −20%

The Tier-3 memo narrates this block and cannot change any label.

## 6. Stage machine

| Stage | Eligible | Max gross | Enter when |
|---|---|---|---|
| 0 observe | B-family pilots | 5% (any regime) | default |
| 1 | B family | 25% | T1 |
| 2 | B family + A on repair | 55% | stage 1 for ≥ 3 sessions AND (T2 or ≥ 15 B-emerging breakouts) AND < 4 distribution days in the last 25 sessions |
| 3 | + C (`flush` only) | 90%; **55% until damage > 0 for 20 sessions** | stage 2 for ≥ 5 sessions AND T3 AND epicenter repair (QQQ/SMH above a flat-or-rising 50d, epicenter RS vs RSP rising 10d) |

**Downgrades bind the book.** They are immediate: positions are cut pro rata to the
new cap within one session, weakest RS first. Blocking new entries alone would not
reduce exposure. Downgrade triggers:

- T6 → stage 0.
- ≥ 4 distribution days within 25 sessions → down one stage.
- 2 of the first 3 pilots after a T1 stopped out → stage 0.
- Bear switch on → at most stage 1 at 10% gross, held there while the switch stays on.
- **Episode breaker:** book −5% from its episode peak → stage 0 for 10 sessions.
- After T6, no new T1 counts for 5 sessions.

**Triggers:**

- **T1 follow-through day.** Day ≥ 4 of a rally attempt (day 1 = the first up close
  after the lowest close). SPY or QQQ closes +1.25% on higher volume than the prior
  session. Volume is measured on the ETF and on consolidated NYSE+NASDAQ volume, and
  both must rise. RSP is not used (thin ETF volume). `holiday_thin` (the week of
  2026-11-26) needs a second confirming T1 within 5 sessions. Historical reliability
  is about 55%.
- **Distribution day.** SPY or QQQ closes ≤ −0.2% on higher volume than the prior
  session, counted over a rolling 25-session window.
- **T2 breadth thrust.** % of the universe above its 20d rises ≥ 35 points from
  its drawdown low within 10 sessions, AND IWM confirms (above its 20d). This rule
  is **uncalibrated**: it is used only after §9.1 fits it.
- **T3 Stage-2 rebuild.** Computed from point-in-time prices, not the board
  (board history starts 2026-05). The count of universe names passing the stage-2
  template must reach ≥ max(2× its drawdown low, 150).
- **T6 failure.** SPY or QQQ undercuts the rally attempt's day-1 low.

Sentiment inflection and VIX calming are reported, not gated.

## 7. Buckets

Every bucket is computed by code. LLM labels only gate A (§7.4).

### 7.1 B family: resilient leaders (core list)

Every B name must pass a **growth gate**, or B fills with low-beta defensives that
"held up" because nobody owns them for growth. The gate requires either:
- the latest two quarters' EPS growth and sales growth both positive and accelerating, or
- membership of the `nis-fundamentals` board.

RS is the universe-wide 6- and 12-month RS rank, computed in code, with both in the
top 20% and the higher one in the top 10%. Drawdown resilience alone is not enough.

- **B-hold.** Growth gate + RS + `dd_from_high` ≥ −10% from the ticker's own peak in
  the 60 sessions before the SPY peak, above a rising 50d. Entry is a pullback to
  the 21-EMA or the 50d that holds (pattern `ema21_reclaim` / `ma50_reclaim`).
- **B-base.** Growth gate + RS + a base: ≥ 5 weeks long, depth ≤ 20%, weekly ranges
  contracting over the last 3 weeks, volume below its 50d average in the last 2
  weeks. The pivot is the base's high, not the 50-session high.
- **B-emerging.** Sessions 1–15 after T1: breaks a base pivot on volume ≥ 1.4× its
  50d average, with the RS line within 2% of a new high.
- **B-gap.** A post-earnings gap ≥ 4% on ≥ 2.5× volume that holds above the gap
  day's low for 3 sessions while its sector ETF is flat or down. Relative to the
  sector, so it is not limited to sessions when SPY is down.

**Pre-registered contrast.** The repo's own strategylab result is that a breakout
trigger underperformed a non-breakout control (31.3% vs 34.3% hit rate, t = −2.06)
while RS rank helped (+9.7pp). So §9.1 tests B-hold (RS-ranked, pullback entry)
against B-base/B-emerging (breakout entry) as an explicit comparison.

Known risk: a momentum crash in the first weeks of a junk rally (Daniel & Moskowitz).
Stages 1–2 cap gross at 25–55%, and B is graded factor-adjusted with momentum in
the model.

### 7.2 A: quality bystanders (watchlist, entry on repair)

Watchlist rule: in the latest `nis-fundamentals` board, OR it passes the quality gate
computed in code (ROIC ≥ 12%, FCF positive in ≥ 3 of the last 4 years, net
debt/EBITDA ≤ 2) to widen the 80-name board; `excess_dd` ≤ −5%; no strong
epicenter link (§7.3); label `drop_cause ∈ {sympathy, macro}` and `damage = none`.

Entry only on technical repair: reclaims its 50d and holds 3 sessions, or an
undercut-and-rally of a prior low. Never on drawdown depth alone. Evidence: Chan
(2003) finds no-news drops reverse and news drops drift, and Nagel (2012) finds
reversal pays most when the VIX is high. Expected to trail a beta-matched loser
basket early in the rebound (quality lags junk). That is graded, not hidden.

### 7.3 D is dropped as a long and becomes the `linked_exposure` avoid flag

Names with a strong edge (strength and mention count over floors) to an epicenter
ticker that is down ≥ 20% get `linked_exposure = true`. Linked stocks drift with
the news (Cohen & Frazzini 2008). The flag excludes them from A and adds a warning
on B. The rebound hypothesis is tested only in §9.1, with its own pre-registered rule.

### 7.4 Labels (A only)

**Codebook** (frozen before any model is scored; 8 worked examples in `label.py`):

- `drop_cause`, priority order on ties: `own_news` > `sector` > `macro` >
  `sympathy`. `unclear` only when no headline is about the ticker or its industry.
- `damage`: `none` (sentiment only) · `estimates_at_risk` · `impaired`.

**State.** Code-built, as-of: headlines whose ingest time is ≤ the call time,
prices up to the decision close, drawdown and excess-dd numbers. **No**
`news_impact_heads` scores or reasoning.

**Labeller.** One model, 3 samples at temperature 0.7 (at temperature 0 the
samples are near-identical and self-agreement measures nothing). The label is the
majority answer. Structured output through tool use. Uncertainty = self-agreement,
not verbalised confidence. Model = the cheapest that passes §9.2, tested in a fixed order (gemma4:31b-cloud,
Haiku 4.5, Sonnet) with a Holm correction. There is no Sonnet re-label stage: with
~10 errors in a test split, its catch rate cannot be measured. A missing or invalid label
removes the name; there are no defaults.

**Jev (TypeSafe)** answers the same codebook in shadow: logged and scored, never
used. **Code-only arm**: a proxy for every label, with thresholds fit on the dev split.
- `own_news` ⇐ an idiosyncratic shock since the peak: a daily residual return ≥ 3σ on
  ≥ 2× volume. σ comes from the 120 sessions before the peak. The residual is taken
  against an **equal-weight peer basket excluding the stock itself**, because NVDA or
  AAPL dominate their own sector ETF and would mechanically shrink their residual.
  The proxy cannot see `sector` causes, so its errors are reported by class.
- `damage` ⇐ FY+1 EPS revision ≤ −5% **live only**: the snapshots start
  2026-11-21, so the revision is measured from that date. In §9.1 there is no
  estimate history, so the history-tested A rule uses `own_news` + quality only,
  and the damage gate is explicitly absent there.

If a model ever replaces the proxy live, the live A is a variant §9.1 never
tested, and it is labelled `A_model` on every page and in the ledger.

### 7.5 C: epicenter overshoot (deferred)

Off until priced-in rows land. Then: `flush` only, stage 3, `median_gap` shows the
price below the analyst median, AND a new base of ≥ 6 weeks above a flattening
200d. Never a first bounce off the 200d in a name down ≥ 30%.

### 7.6 E: pairs (out of v1)

Insider clusters (≥ 3 distinct buyers, `cluster_buy` from the insider board) are a
flag on any bucket, not a bucket.

## 8. Trade plans and portfolio risk

**Per name** (`plans.py`):

- **Pattern and pivot:**

  | Pattern | Pivot |
  |---|---|
  | `base_breakout` | the base high |
  | `ema21_reclaim` / `ma50_reclaim` | the reclaim day's high |
  | `undercut_rally` | the high of the day that reclaims the undercut low |
  | `earnings_gap` | the gap day's high |

- **Entry and fill.** Entry is a buy-stop at the pivot, valid 5 sessions, re-armed if
  the pivot changes. Fill model (also used by the grader):
  - triggers when the session's high ≥ pivot AND volume pace ≥ 1.4× the 50d average
  - fills at max(open, pivot) plus slippage
  - cancelled if the open is > pivot × 1.05 (too extended)
- **Stop.** The tighter of the pattern low and entry − 1.5 × ADR, but never tighter than
  max(1 × ADR, 3%) and never wider than 8%.
- **Size.** min(0.5% account risk ÷ stop distance, **10% per name**, remaining gross
  under the stage cap). **Total open risk** (sum of distance-to-stop × size) ≤ 3% of
  the account; a new entry that would breach it is skipped.
- **Earnings.**
  - No new entry within 5 sessions of a report.
  - A held name reporting within 3 sessions is halved, unless it is ≥ +2R, in which
    case it is held with the stop at breakeven.
- **Exits.**
  - Stop moves to breakeven at +1.5R.
  - Partial (one third) at 2.5R.
  - Trail on a 21-EMA close (B) or a 50d close (A).
  - Time stop: exit if not +1R after 15 sessions.
  - RS-line break: the RS line vs SPY closes below its 21-session low while SPY is
    above its 21-EMA.
- **Flags:** `linked_exposure`, `tax_loss_window` (market cap < $2B and YTD ≤ −30%,
  until Dec 31; these names are excluded from A, not only flagged),
  `insider_cluster`, `squeeze_risk_unknown`, `litigation_headlines` (the name is
  excluded from A while plaintiff-firm headlines are its only news since the peak).
- **Hard rules:** never add below the entry, so a re-seal of a held name is not an
  add; no entries on rally days 1–3.

**Per list and for the union** (`risk.py`):
- **Reported:** sector weights; beta to SPY, QQQ and SMH; average pairwise 60d
  correlation; effective N (inverse Herfindahl of risk contributions). Names in more
  than one bucket are deduped.
- **Hard caps:**
  - ≤ 3 names and ≤ 25% per sector per bucket
  - union QQQ beta ≤ 1.0
  - effective N ≥ 5 once gross exceeds 25% (otherwise the weakest-RS names in the
    most crowded sector are trimmed)
  - gross ≤ the stage cap

## 9. Evaluation

### 9.1 Primary: historical study (decides publication)

**What it can show.** About 12–16 usable, non-overlapping episodes. With
episode-level SD of 20-session excess return ≈ 5%, the MDE is ≈ 4.5% (≈ 0.35R).
Power against a plausible 2–4% (0.1–0.2R) edge is ~20–45%. So the study can falsify
a large effect or confirm a very large one, and a modest real edge will usually come
back inconclusive. The exact MDE is computed and committed before the first run.

**Episodes.**
- Since 1995, the first close where SPY is ≥ 8% below its high OR the epicenter
  index is ≥ 15% below its high. The lower bar includes the July 2024 and
  September 2020 flushes.
- Each episode is a fixed 120-session window from that close.
- No new episode starts until SPY makes a new high or 120 sessions pass, so the
  2000–02 and 2007–09 bears contribute non-overlapping legs, not near-duplicates.
- Concentrated episodes are a pre-registered subgroup, reported but not separately
  tested.

**Universe and survivorship.**
- Point-in-time S&P 500 membership rebuilt from FMP's constituent change log,
  audited to 500 ± 5 names on every date (episodes failing the audit are marked).
- Names with no price history are **kept** with an assumed delisting return.
  Results are reported at −30% (central) and −100% (worst case).
- **No episode is excluded.** Excluding high-`missing_share` episodes would drop
  2000–02 and 2008, the busts, and validate on flushes.
- Sector labels are current (marked).
- Before Dec 1998 (no sector SPDRs), peer baskets are equal-weight industry groups
  from the universe.

**Macro in history.** FRED's ICE HY OAS series now starts 2023-11-21 (verified).
History uses **BAA10Y** (1986+) for the credit component, pre-registered, with
DFII10 from 2003 and the 10y nominal yield before that. The damage axis in history
has the price arm and the yield arm only, marked `reduced`.

**Rules.** Code-only: the B family, A with the code proxies (`own_news` + quality;
no damage gate), the stage machine, plans, risk caps and the fill model of §8.

**Calibration vs test.**
- T2 and every proxy threshold are fit on episodes that start before 2010 and tested
  on 2010 onward.
- Leave-one-episode-out results are reported alongside.
- The flush/bust examples named in §5 come from hindsight, so they are not used to
  fit anything.

**Primary tests (exactly two, α = 0.025 each, pre-registered):**
1. B family: mean episode-level **excess** 20-session return of trades vs a control
   matched on sector × beta decile × 60d return decile with **the same entry
   geometry** (the same fill model applied to the control's own pivots), > 0.
2. The same test for A.

**Inference.**
- Episodes are the units: a t-test with G − 1 degrees of freedom, confirmed by a
  wild-cluster bootstrap. There are too few clusters for standard cluster-robust
  errors.
- Raw R expectancy, MAE/MFE, trigger rate, list-level max drawdown and factor-adjusted
  returns (market, size, momentum, quality) are reported as **secondary**.
  Raw R > 0 mostly measures beta, since every ≥ 10% drawdown since 1995 recovered.

Everything else (the four B sub-lists, the B-hold vs breakout contrast, stage
variants) is **exploratory**. Models are not used anywhere in §9.1.

### 9.2 Label evaluation (only after A passes §9.1 under the proxy)

1. **Sample.** ~190 code-prefiltered names over several weeks with frozen as-of
   states, so same-day headline clustering is diluted. Dev 40 / test ~150.
2. **Gold.**
   - The test split is **human-only gold**, labelled blind from the frozen state,
     with no model output and no prices after the call.
   - A second rater labels 20 names for inter-rater κ.
   - Pre-adjudication labels are kept; adjudication never shows model labels.
   - Opus labels are used on dev only, so Anthropic-family arms do not score well
     by sharing Opus's errors.
3. **Taxonomy gate.** Human–human κ on `drop_cause`, lower 95% bound ≥ 0.6. If it
   fails, the codebook is revised on **new** names, not the same ones.
4. **Headroom check first.** If the code proxy scores ≥ 85% balanced accuracy vs
   human gold, the labeller is not built.
5. **Primary metric.** Balanced accuracy of A-inclusion (most candidates are
   excluded, so raw accuracy rewards "exclude all"), with the false-include rate as
   the decision cost. McNemar vs the proxy on the disagreement set; margin ≥ 10pp,
   α = 0.1, Holm across the model arms. ~150 test names give ~80% power at a 25%
   disagreement rate.
6. **Damage, ex post.** The target is the **incremental** FY+1 revision from the call
   to t+30 and t+60, reported as a partial correlation controlling for the as-of
   revision. Revisions are autocorrelated, so a proxy built on them would otherwise
   predict itself.
7. **Drift.** 20 fresh blind names a week. The daily canary is 20 fixed names (10
   would trip on two flips). A new `model_served` resets the gate.

### 9.3 Live ledger (out-of-sample confirmation)

- `drawdown_calls`: append-only, with a seal-once trigger (the
  `research_predictions_immutable()` pattern). Sealed by 09:00 ET for the next open.
- Graded per first-entry event with the §8 fill model: trade-level R and MAE, plus
  list returns at 5/20/60 sessions as secondary, against the §9.1 controls.
- The MDE is reported next to every result.

## 10. Health gate and observability

**Freshness SLAs.** A breach blocks the snapshot (`status=blocked`, publish "no
list today"):

- bar coverage ≥ 95% of the universe at the decision close
- `ticker_sentiment_heads.scored_at` < 24h old
- the latest stage-2 / fundamentals `run_at` within the board's cadence
- the day's `drawdown_snapshot_runs` row exists with `status = complete` (row
  presence in the snapshot tables proves nothing: a partial day writes rows too)
- priced-in (when C is on): a row-delta check, since the batch once recorded zero rows silently

**Row-delta checks.** Today's count vs the trailing median for every input table; a
drop > 50% blocks.

**Atomic snapshot.** Built in a temp directory, renamed on `status=complete`.

**Per model call.** `model_requested`, `model_served`, input/output tokens, cost,
latency, sample index. `shared/llm.chat` must return token usage (a small change
there). Tier models are explicit environment variables that **fail if unset**; no
`resolve_model` fallback.

**Daily canary.** Re-label 10 fixed gold names. Alarm on agreement < 80% or a
≥ 15pp shift in the `sympathy` share.

**Cost.** About $3/day at Sonnet worst case; cap `DRAWDOWN_MAX_USD=5`. Over the cap,
labelling stops and A is skipped for the day.

## 11. Publication

- Until §9.1 passes: nothing public. Internal snapshot and memo only.
- After it passes: published as a **watchlist / research candidates**, never "buy".
  Nothing at stage 0. Every page shows the stage, the regime label, a data-health
  badge, the concentration warning from §8, the full sealed track record against
  controls (losers included) and a not-advice disclaimer.
- An arena agent consuming the list is limited to the stage exposure cap.

## 12. Build order

1. **DONE 2026-11-21.** `snapshots.py`: daily estimate and macro snapshots
   (JSONL + Supabase + run manifest).
   - **Fails closed:** error bodies count as failures, more than 5% failed symbols or
     any failed macro series = `partial` with a non-zero exit, and the manifest is
     written last.
   - **No back-dating:** US/Eastern date, no `--date` flag.
   - **No survivorship inside its own history:** names that fall through the
     liquidity floor stay tracked.
   - The first run covered 2,775 of 2,819 symbols; it is held in JSONL until the
     migration is applied.
   - Needs migration `20261121120000_drawdown_snapshots.sql`, then
     `cli load --date 2026-11-21`, then a Mac Mini cron entry (after the close, e.g.
     17:30 ET).
2. **Historical study.** Data audit for the survivorship-free universe (Q1), then
   `history.py` with code-only rules, pre-registered.
3. **Phase 0 regime + stage machine + Phase 1 features + B family + plans + risk +
   health gate.** All code. Produces the internal daily snapshot.
4. **Codebook + label evaluation (§9.2).** Build the labeller only if a model beats the proxy.
5. **Seal + grade + Opus memo skill + cron.** The live ledger starts.
6. C, once priced-in is confirmed and §9.1 has a C rule to test.

## 13. Snapshot contract (abridged)

```json
{
  "as_of": "2026-11-20", "spec_version": "0.2", "status": "complete",
  "regime": {"label": "concentrated", "sub": "undetermined", "bear_switch": false,
             "epicenter": {"index": "QQQ", "dd": -0.199, "tickers": []},
             "macro": {"hy_oas_20d_bp": 0, "real_10y_20d": 0, "usdjpy_10d": 0}},
  "stage": {"value": 0, "since": "2026-11-20", "triggers": {}, "distribution_days": 0},
  "lists": {"B_hold": [], "B_base": [], "B_emerging": [], "B_gap": [], "A": []},
  "plans": [{"ticker": "…", "bucket": "B_base", "pattern": "base_breakout", "pivot": 0,
             "stop": 0, "risk_pct": 0.005, "days_to_earnings": 0, "flags": []}],
  "risk": {"union": {"sector_weights": {}, "beta_qqq": 0, "avg_corr": 0, "effective_n": 0}},
  "health": {"checks": {}, "blocked_reasons": []},
  "labels": {"model": "…", "model_served": "…", "jev_shadow_agreement": null},
  "cost": {"usd": 0, "per_label": 0}
}
```

## 14. Open questions

- **Q1** Survivorship: on this FMP plan, point-in-time S&P 500 membership exists but
  delisted price history mostly does not (§9.1 measures the gap). Is a paid source
  for delisted bars (e.g. Norgate, CRSP via WRDS) worth it if `missing_share`
  turns out large in the 2000–02 and 2008 episodes?
- **Q2** Human blind labelling: about 60 names, about 2 hours. Who does it, and when?
- **Q3** Hyperscaler capex guidance: a manual input each earnings season, or parsed from transcripts?
- **Q4** Should the arena get a "drawdown" agent consuming this list, once §9.1 passes?

## References

Chan (2003, JFE), news vs no-news drops · Nagel (2012, RFS), reversal and VIX ·
Daniel & Moskowitz (2016, JFE), momentum crashes · Cohen & Frazzini (2008, JF),
economic links · Quantifiable Edges, follow-through day statistics · McClellan /
StockCharts, Zweig breadth thrust record.
