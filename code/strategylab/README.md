# strategylab

An LLM-in-the-loop reinforcement search that evolves a swing-trading strategy
until it is either deployable or provably not.

```
       ┌──────────────── policy ─────────────────┐
       │  Claude proposes experiments from       │
       │  diagnostics + history (hypothesis-led) │
       │  TPE exploits the observed surface      │
       │  bandit-picked mutations refine locally │
       │  a random draw prevents collapse        │
       └───────────────────┬─────────────────────┘
                           │ genomes
                    ┌──────▼───────┐   rung 0: one fold, capped universe
                    │  BACKTEST    │   rung 1: full purged walk-forward
                    │ environment  │   costs, slippage, ADV capacity
                    └──────┬───────┘
             ┌─────────────┴──────────────┐
             ▼                            ▼
      ┌────────────┐              ┌──────────────┐
      │  REWARD    │              │ INVESTIGATE  │  exit efficiency, stop
      │ median OOS │              │   critic     │  calibration, rank
      │ fold Sharpe│              │              │  information, regime
      │  − penalties│             │  findings +  │  attribution, capacity,
      └─────┬──────┘              │  directions  │  concentration
            │                     └──────┬───────┘
            └──────────► LEDGER ◄────────┘   every trial, incl. failures
                           │
                           ▼
                   GATE → sealed VAULT → deploy/
```

## The idea

Strategy research is a noisy black-box optimisation problem. The objective is
expensive, non-differentiable, partly categorical, and — crucially — the metric
you are maximising is the thing most likely to fool you. This project treats it
as reinforcement learning with the honesty machinery built in:

| RL concept | Here |
|---|---|
| Environment | Purged walk-forward backtest, real frictions, capacity limits |
| State | The ledger: every genome tried, its metrics, its diagnostics |
| Action | A genome mutation — rules, thresholds, universe, data, exits, sizing |
| Reward | Median out-of-sample fold Sharpe, minus explicit penalties |
| Policy | Claude (hypotheses) + TPE (exploitation) + bandit mutations + random |
| Credit assignment | UCB1 over operators, scored on improvement over the *parent* |
| Terminal state | A genome that clears every gate on data the search never saw |

## Quick start

```bash
cd code/strategylab
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # or rely on the fallback to ../analytics/.env

.venv/bin/python -m strategylab.cli data sync --source liquid_mid_large
.venv/bin/python -m strategylab.cli baseline                 # score the incumbent
.venv/bin/python -m strategylab.cli search --iterations 20   # run the loop
.venv/bin/python -m strategylab.cli finalize                 # gate → vault → export
.venv/bin/python -m strategylab.cli signals                  # today's orders
```

`--no-llm` runs the whole loop on the deterministic samplers if you'd rather not
spend tokens; the search is slower to find structural changes but everything
else is identical.

**Sizing the run.** `--limit N` takes the N most liquid names (not the
alphabetical head). Cost is roughly linear in symbols × sessions: 800 symbols
over 2013-2026 is ~1 GB resident and ~60 s per 8-proposal iteration on a
laptop. The feature cache is LRU-bounded and the per-genome signal cache holds
10 entries, so memory is flat across a long run rather than growing with the
trial count.

## What it found

Over 110 configurations on the 800 most liquid US names, 2014-2023, after
modelled costs:

| | Sharpe | CAGR | max DD | total |
|---|---|---|---|---|
| **SPY buy-and-hold** | **0.738** | **12.1%** | 33.7% | **+211%** |
| best evolved genome | 0.464 | 6.8% | 16.2% | +93% |
| incumbent NIS Momentum | ~0 | ~0% | — | — |

The search did real work — it took the incumbent from roughly zero to 0.464 and
cut turnover from 13x to 4.2x a year — and **the winner still loses to holding
the index**, on return and on risk-adjusted return alike (information ratio
−0.36). It wins only on drawdown, which is what being 43% invested buys.

The gate refused it: Sharpe 0.464 (needs 1.00), deflated Sharpe 0.557 (needs
0.95), alpha t-stat 1.03 (needs 1.50), PBO 0.59 (needs ≤ 0.35). **The vault was
never opened.**

**Read the PBO number.** At 41 configurations it was 0.255 — selecting on
backtest performance carried real information. At 110 it was **0.59**: the
in-sample winner lands in the bottom half out of sample more often than not.
The search did not merely stop improving, it began fitting noise, and every
further trial made its own winner less credible. That is the argument for
stopping a search when the reward curve flattens, and it is visible in
`output/runs/evolve2/charts/`.

**Absolute numbers here are universe-sensitive.** The same incumbent scores
Sharpe 0.25 on the top 600 names and roughly 0 on the top 800 — less liquid
momentum does not survive costs. Every run records its universe size so two runs
can be compared at all; `finalize` refuses to score a genome against a universe
the search never used.

## The short sleeve

Off by default, so the incumbent baseline stays comparable — and it costs about
**15 active parameters** of complexity when switched on, which the reward makes
the search earn back before it counts as an improvement.

The case for it is structural: in a bear fold a long-only book can only stand
aside, and standing aside earns nothing. The case against is that borrow is a
real daily cost, losses are unbounded, and covering into a rally is how short
books give back a year in a fortnight.

The simulator handles both directions on one code path, not two that drift
apart, using three identities:

```
profit per share      =  side * (price - entry)
stop                  =  entry - side * risk_per_share
"stop has been hit"   =  side * (price - stop) <= 0
```

A short is a long with `side = -1`; nothing else in the loop changes. What it
models: borrow charged to cash **daily** (floored at 25bps annual — the genome
will not let a search discover costless shorting), a stricter price and
liquidity floor than the long side, a crowding guard, and `short.cover_on_regime`
to force covering when the market turns back up.

What it does **not** model, and matters: true short interest (turnover stands in
for it), hard-to-borrow fees that can run to hundreds of bps and move daily,
recall risk, and locate availability. Treat any short result as an upper bound.

`tests/test_short_sleeve.py` pins the mechanics against hand-computed
arithmetic — long/short P&L mirror exactly on the same path, stops sit above
entry and trail downward, short proceeds credit cash while creating a liability,
and equity survives a 4x squeeze.

## What is being optimised

The starting genome **is** the production NIS Momentum screen — Minervini trend
template, RS ≥ 80, volume confirmation, ADR band — expressed as 73 tunable
dimensions and traded with an ATR stop. That is the baseline every experiment is
measured against, so "we improved it" is a claim with a number attached.

The search may change all of it: which listings are eligible, the liquidity
floor, every gate and threshold, whether the point-in-time fundamentals or the
news-impact overlay are used at all, the entry trigger, the ranking composite,
the stop construction, the trailing and target logic, position sizing, and the
portfolio constraints. `strategylab space` prints the full space.

## Why the results are trustworthy (or, where they aren't)

Most of this codebase is not the strategy — it's the machinery that stops the
strategy from lying.

**Look-ahead.** Signals are computed on the close of day *t*; every fill happens
at the open of *t+1*. `tests/test_backtest.py::test_no_lookahead_future_prices_cannot_change_past_trades`
runs the same strategy over two panels identical up to day K and arbitrary after
it, and asserts every trade closed before K is byte-identical. Fundamentals are
keyed on SEC *filing* dates, not period ends. News is attributed to the session
it could first have been traded on, not the UTC calendar day.

**Costs and capacity.** Spread, slippage, commission and participation-scaled
market impact on every side. Orders above 5% of the name's 20-day ADV are
truncated, so the search cannot find "alpha" in names it could not have bought.

**Selection bias.** Every trial is logged, including failures, because the
Deflated Sharpe Ratio is a function of how many configurations were tried. A
result found after 400 experiments has to clear a materially higher bar than one
found after 20. PBO (via combinatorially symmetric cross-validation) reports the
share of splits where the in-sample winner lands in the bottom half out of
sample — near 0.5 means selection carries no information at all.

**The vault.** `2024-01-01 → 2026-06-30` is sealed. The search never sees it. It
is opened once, for one finalist, and the ledger records the event.

**Reward shaping.** The objective is the *median* fold Sharpe minus one-sided
penalties for fold dispersion, drawdown over budget, turnover over budget,
active-parameter count, left-tail heaviness, and beta reliance. Optimising raw
Sharpe with a few hundred trials reliably produces a fragile, over-traded curve
fitted to one regime.

### Known limitations — read before believing any number

- **Survivorship.** Delisted names are included, but this FMP plan page-caps the
  delisted feed at ~57 tickers against 5,762 live listings, so the universe is
  still largely survivorship-biased. `strategylab data status` says so out loud.
  Absolute returns are an upper bound; comparisons *between* genomes stay valid
  because every genome sees the same universe.
- **Index membership** is not historical on this plan, so `universe.source=sp500`
  is additionally biased. Prefer `nyse_nasdaq`.
- **Daily bars.** When one bar spans both the stop and the target, the simulator
  books the loss. It cannot know the sequence.
- **News coverage starts in 2025**, so that overlay is a late-window experiment,
  not a core rule.
- **Sector labels are current**, not point-in-time.

## The flow-inertia investigation (`strategylab/flow/`)

A separate research programme sharing the same data layer and the same
discipline: is momentum the *output* of a persistent flow process, so that
conditioning on flow beats conditioning on price?

```bash
.venv/bin/python -m strategylab.flow.cli stage1        # panel evidence — the gate
.venv/bin/python -m strategylab.flow.cli tier2 --sync  # mechanical ETF flow
```

Stage 1 runs a **pre-registered** set of Fama-MacBeth models plus a falsification
battery, then states a verdict. The pre-registration is written to disk before
the data is touched, and the verdict applies a Bonferroni haircut over the
registered variant count — because a t-stat of 2 after 30 variants is noise.

Its result so far is negative and instructive; see `research/STAGE1-FINDINGS.md`.
Two findings are worth carrying into any similar work:

- **An EMA manufactures the persistence you are trying to measure.** The spec's
  ρ estimator, applied to white noise, returns ≈0.6. On real data it returns
  1.19 — above the 1.0 an AR(1) coefficient can validly take. Pinned as a test.
- **A flow proxy built from `sign(return)` cannot establish an impact law.** The
  contemporaneous fit looks textbook (Y = 0.567, R² = 0.83) and is an accounting
  identity; the same fit on the *next* window's move gives Y = 0.001, p = 0.92.

| Module | Role |
|---|---|
| `flow/signals.py` | Tier-1 estimators: f, Φ, ρ, T_half, ILLIQ, Q_break, F, gap |
| `flow/universe.py` | The FIM screener: cap band, ADV, ETF-ownership floor, earnings blackout |
| `flow/panel.py` | Fama-MacBeth with Newey-West, quantile sorts, long-short spreads |
| `flow/stage1.py` | Pre-registration, the falsification battery, the verdict |
| `flow/etf_flow.py` | Tier 2: ETF creations/redemptions → arbitrage-induced trading |
| `flow/charts.py` | ρ distributions, impact law + control, event-time drift |

## The flow-discriminated pairs investigation (`strategylab/pairs/`)

The successor to Stage 1, and a direct answer to why it died. Stage 1's Tier-1
quantities were functions of the return signs they were meant to explain. The
pairs framing removes that: the discriminator is measured on the divergence
window and every outcome strictly after it, so the forward control is structural
rather than bolted on.

```bash
.venv/bin/python -m strategylab.pairs.cli h1     # the EGJ replication — the gate
.venv/bin/python -m strategylab.pairs.cli null   # simulated cointegration critical values
.venv/bin/python -m strategylab.pairs.cli form --window 0   # inspect one pair book
```

The question: when a cointegrated spread diverges, does *what caused the
divergence* predict whether it converges? H1 is the news axis (the half
Engelberg-Gao-Jagannathan already established, used here as a positive control);
H2-H4 are the flow axis and are **not** tested — they need 13F breadth
differentials or index reconstitution dates, and neither is wired up.

**Closed out 2026-08-20.** Step 1 asked whether the missing mean reversion was
an artefact of a stale anchor. It is not. Under a frozen anchor these spreads
converge *below* a driftless random walk; under a rolling 60-day anchor they
converge 81.8% against a null of 81.3% built by pushing random walks through the
same anchor — excess −0.0pp, t = −0.03. The pre-registered rule named the
conclusion in advance and it has been applied: the reversion line is closed.

The original H1 result is split, and the split is the point. **The discriminator replicates**
— divergences with no earnings announcement on either leg converge 4.97pp more
often than those with one (t = 3.69, clears Bonferroni), confirmed at +8.02pp
on the sealed vault (t = 6.25), with both falsification tests null. **The
substrate does not pay** — the formation OU fits implied 89.4% convergence
within 60 days and delivered 29.0%, and the L-bucket book is +37bp gross per
event against a 26bp round trip. See `research/FDP-STAGE1-FINDINGS.md`.

```bash
.venv/bin/python -m strategylab.pairs.cli anchor   # Step 1 — anchors vs matched nulls
```

Three things are worth carrying into any similar work:

- **One vendor bar on a Saturday emptied an entire pair book, silently.** The
  panel date index is a union, so a single spurious row NaNs every other name
  and joint completeness then fails for all of them. Pinned as a test.
- **A simulated null beats a remembered table.** Engle-Granger residual ADF
  statistics do not follow the Dickey-Fuller tables. Simulating the null with
  the *same* estimator reproduces MacKinnon's published values to within 0.12
  and yields the expected spurious-pair count for free — 41% of this book.
- **Any detrending filter manufactures the reversion you are looking for.** A
  rolling 60-day anchor produces 81.3% "convergence" from pure random walks.
  This is the flow study's EMA artefact in a new guise, and the only defence is
  to score every transformation against random walks pushed through the same
  transformation and the same selection screens.

| Module | Role |
|---|---|
| `pairs/formation.py` | Vectorised Engle-Granger, OU half-life, simulated null, diversification caps |
| `pairs/events.py` | Divergence detection, convergence outcomes, costed pair returns |
| `pairs/discriminate.py` | The announcement discriminator plus its two placebos |
| `pairs/study.py` | Pre-registration, clustered inference, the D1/D2 diagnostics, the verdict |
| `pairs/anchor.py` | Anchoring schemes and the matched synthetic null for each |
| `pairs/anchor_study.py` | Step 1: pre-registration, excess-over-null, the close-out verdict |
| `pairs/charts.py` | Convergence survival, per-window stability, bucket P&L, the null |

## What is priced in (`strategylab/social/`)

Where the social-arbitrage line ended up. `SOCIAL-ARB-1` assumed consumer
attention could be found *before* the market had it; it failed on its pivotal
link, and the reason generalises into the governing assumption of this module:
**anything in our news database is already priced in.** That makes the corpus
useless as a source of edge and valuable as a map of the baseline.

```bash
.venv/bin/python -m strategylab.social.cli cases CROX       # the pipeline, one ticker
.venv/bin/python -m strategylab.social.cli control CROX     # calibrate the corpus veto
.venv/bin/python -m strategylab.social.cli universe seed    # build the NYSE+NASDAQ working set
.venv/bin/python -m strategylab.social.cli universe check   # who has enough analyst coverage
.venv/bin/python -m strategylab.social.cli batch --dry-run  # what a scheduled pass would take
.venv/bin/python -m strategylab.social.cli batch --limit 25 # one scheduled pass
```

The unit of work is a **rejected published model**, not a generated idea. Asked
to invent counterfactuals the model produced twelve and all twelve were already
written up — it cannot be original because its priors *are* consensus. A bank's
rejected price target is a real model the market has seen and declined, and it
arrives with its author's own question to management attached.

| Module | Role |
|---|---|
| `social/narrative.py` | The null: typed peers + circulating claims, market-wrap filtered |
| `social/implied.py` | Reverse DCF — the revenue path the price requires |
| `social/analyst.py` | Target dispersion + earnings-call Q&A: the sell-side *argument* |
| `social/vote.py` | Where the price sits among published models: endorsed vs rejected |
| `social/decompose.py` | Per driver: how much is priced in, and what it is worth |
| `social/case.py` | Each **driver**, investigated: the scored coverage on it (how *known* it is, hence how priced), what the passages assert either way, and the non-news series wired for its observable — or the stated gap |
| `social/entail.py` | The corpus veto — retrieve with embeddings, judge by reading |
| `social/pit.py` | Point-in-time reconstruction; `leakage.py` measures model contamination |
| `social/investigate.py` | The crux, investigated with NON-news tools: pre-registered checks, then an adversarial refutation pass in its own context |
| `social/tools.py` | The evidence surface — everything except news, and it reports what it cannot measure |
| `social/predict.py` | Tier 3 — locked forward predictions, mechanical resolvers, Brier vs base rate |
| `social/persist.py` | Mirrors the record to `research_priced_in` / `research_predictions` |
| `social/llm.py` | One JSON completion, two backends. Ollama (`glm-5.1:cloud`) or Anthropic — same prompts, same schemas, only the wire changes |
| `social/ledger.py` | The sealed prediction ledger, with Supabase as the source of truth and the immutability trigger enforcing it server-side |
| `social/universe.py` | Which of the 5,810 NYSE + NASDAQ names this can actually be run on. Coverage is the only gate — 1,110 clear the mention floor, and of those the ones with the ≥5 published models the grounded tier needs qualify. Size is recorded, never tested: whether the sell-side and the press care is the question, and a $200m company they both cover qualifies over a $3tn one they do not |
| `social/batch.py` | The scheduled pass — resumable, isolated per ticker, and the **publish gate** that decides what goes live |
| `scripts/run_priced_in.sh` | The Mac Mini crontab wrapper: `resolve` daily, `batch` nightly, `universe` weekly |

Read the output in three tiers — grounded (arithmetic on published models),
assumption-sensitive (the DCF path), and judged (per-driver percentages, which
are **unvalidated**). Two things have been tested against outcomes and both
failed: implied CAGR as a signal (negative, 188 observations), and
`priced_in_pct` against event reactions (a parameter artefact — the correlation
changes sign across knob settings, sits inside its placebo null at p = 0.16, and
reverses between decomposition variants). **Tier 3 is open**: 65 locked forward
predictions over 13 tickers registered 2026-08-25, resolving 2026-12-23, scored
by Brier against the base rate. Predictions are hashed at creation and a
prediction that no wired resolver can settle cannot be registered at all.

The grounded tier renders on `/quote/<symbol>`. The judged tier is shown as
ordinal colour bands rather than decimals — the percentages have failed
validation twice, and a decimal beside a real share price asserts more than the
number carries.

The most useful field turned out to be the **crux**: the single question the
published disagreement reduces to. Tesla's whole $370-$500 spread is one
variable at different dates (robotaxi timing), and 13 of 14 targets call the
stock too cheap. That gives `investigate.py` a question it did not invent —
which matters, because every attempt to make the model *generate* an idea failed:
asked for counterfactuals it produced twelve, all twelve already written up,
because its priors are consensus.

Five things worth carrying out of it:

- **Similarity cannot do entailment.** Cosine ruled a school-dress-code thesis
  already covered by a sandals article at 0.75. Embeddings retrieve; a model
  reads; a claim of coverage must carry a verbatim quote.
- **`max` over N grows with N.** The same order-statistic bias appeared in three
  separate comparisons before it was pinned.
- **Presence is a conclusion, absence is a non-answer.** The corpus is a sample.
- **The binding constraint is measurement, not reasoning.** Two companies
  investigated independently both converged on third-party panel data we do not
  have.
- **An adversarial pass in its own context earns its keep.** On Tesla it moved
  the probability 0.35 -> 0.17 and caught the programme's signature error:
  *"You do not get to write the falsifier, watch it fire, and then relabel the
  instrument as a proxy."* See `research/PRICED-IN-FINDINGS.md`.

## The news-repricing investigation (`strategylab/news/`)

Where the pairs work pointed. FDP established that announcements stop a spread
converging — the price reprices and stays. Read the other way that is
post-earnings-announcement drift, so this tests whether the same effect pays
directionally, on 146,722 announcements over 1997-2026.

```bash
.venv/bin/python -m strategylab.news.cli nrp        # drift vs its own control
```

**The mechanism replicated; the trade has decayed.** Post-announcement drift is
monotone across every liquidity tier before 2014 (Spearman +0.81 whole-panel)
and gone after it (−0.03 on 2014-2023, +0.01 on the sealed vault). It survives
only in names trading under $1M a day, where the modelled costs are optimistic
by an order of magnitude.

But the **control** carried the finding. A large abnormal move with *no*
announcement near it reverts hard (decile slope −0.93 in large caps); the same
move *with* an announcement does not. That is the FDP taxonomy — transient
shocks decay, information repricings do not — reproduced on single-name
directional returns, sharing no code path with the pairs study. Two programmes,
same taxonomy. See `research/NRP-STAGE1-FINDINGS.md`.

Two things worth carrying into any similar work:

- **A control has to be matched on the calendar, not just the null.** The first
  version drew pseudo-events from random days in each name's history. Real
  announcements cluster into four seasons a year, so the two samples barely
  shared months and most of the comparison evaporated. Same day, same liquidity
  tier, different name — one variable left moving.
- **One unadjusted corporate action can be larger than the effect.** A single
  +39,900% "return" moved a decile mean of ~6,000 events by 6.6 percentage
  points. Winsorisation thresholds are cut on the pooled real-plus-control
  sample so the control can never be trimmed differently from the treatment.

| Module | Role |
|---|---|
| `news/eventstudy.py` | Rolling-beta abnormal returns, announcement windows, day-matched pseudo-events, winsorisation |
| `news/overlay.py` | Sentiment/attention signals on the panel, coverage, and the power floor |

**Does the news overlay add anything?** `cli.py impact` says: **not resolvable**.
The pipeline starts 2025-04-10, giving 306 usable sessions entirely inside the
vault period, with median **147 universe names/day (38% of the cross-section)**.
Overlapping returns leave **4.8–8.7 effective observations at H21**, so the
smallest resolvable IC is 0.056–0.111 against real signals of 0.02–0.05 — the
test could not have found a normal-strength effect. Nothing clears the floor.
What the sample *can* say: **attention is positive in all four of its cells**
(IC 0.007–0.034) while **sentiment — the signal the product is built on — is the
only one that flips sign** between halves. The NIS impact scores cover just 4.5
months and were not testable.

`cli.py tilt` (momentum) then **tries it in the portfolio** — weighting the book
by each news signal, paired against the untilted book over the same window.
Rank-weighting by **surprise (+3.17%/yr, t = +1.88) and attention (+3.10%/yr)**
beat the untilted book; **sentiment subtracted (−1.13%, and −3.38% in its
strongest form)** — the same ordering the IC table gave independently. Fifteen
monthly observations, so nothing is tradeable on it. Two tilts turned out to be
no-ops (a median split of an integer count selects nothing) and are reported as
*not testable* rather than as nulls — `run_hold` now returns
`tilt_effective_share` and refuses anything below 50%.
See `research/NEWS-OVERLAY-FINDINGS.md`.
| `news/study.py` | Pre-registration, clustered inference, tier and era breakdowns, the verdict |

## The momentum universe (`strategylab/momentum/`)

**A standing decision: the Minervini trend template on NYSE + NASDAQ is the
universe, and strategies are built for it from here on.**

```bash
.venv/bin/python -m strategylab.momentum.cli pin     # build + fingerprint the universe
.venv/bin/python -m strategylab.momentum.cli ic      # IC + incremental IC, every signal
```

Median **206 names/day**, 2,006 ever qualified, 2004-2026. The universe is
*pinned*: a SHA-256 fingerprint over the spec, symbol list, dates and mask, and
`verify()` refuses to certify a run against a panel the pin was not built on.
That closes the drift hazard documented above, where the cached symbol set grew
from 800 to 2,357 underneath a `--limit` flag.

**Momentum is a mandatory control, and that is the load-bearing design choice.**
Conditioning post-earnings drift on the trend template tripled its raw spread —
and lifted the matched no-news control by more. The screen adds momentum, not
information. Since the universe *is* a momentum screen, every signal measured on
it is exposed to that confusion, so the reported number is the Fama-MacBeth
coefficient with the momentum controls in the same regression.

First measurement, 16 signals, dev 2014-2023, 21-day horizon: **nothing clears
the bar.** The multiplicity-corrected threshold is |t| > 2.96 and the largest
incremental t is 1.91. A naive t-stat would have overstated significance by
**3.2x** (a 21-day forward return sampled daily autocorrelates). And the
"breadth" is largely illusory — `residual_momentum` ↔ `mom_12_1` correlate at
+0.83. See `research/MOMENTUM-UNIVERSE.md`.

| Module | Role |
|---|---|
| `momentum/universe.py` | The pinned, fingerprinted trend-template universe |
| `momentum/signals.py` | Signal registry — one cross-sectional score per name per day |
| `momentum/ic.py` | IC, incremental IC after controls, multi-seed placebo, collinearity |
| `momentum/hold.py` | Portfolio over the screen: breadth-scaled sizing, signal tilts, concentration |

**"Hold only the best one and rotate"** (`cli.py rotate`) turns out to be
**leverage, not skill**. Beta rises monotonically with concentration — 0.69
holding everything, 1.62 holding one — while Sharpe does not move: the whole
spread across every concentration level is **1.1 standard errors**. What does
change is ruin risk: max drawdown goes from **−39.1% to −96.6%** and the worst
rolling year from −31.7% to **−88.4%**. The same market exposure is available by
levering the diversified book ~2.3x, with none of the 12.5x turnover and no path
to ruin.

**Does holding the whole screen beat the market? No — it matches it.** Equal
weight, monthly rebalance, 26bp round trip, 2005-2026: CAGR **+10.4% vs SPY's
+10.8%**, Sharpe **0.66 vs 0.65**, alpha t = 1.25. Across 2014-2023 it *lost* to
the index (+7.3% vs +11.9%, IR −0.36). What it buys is drawdown — scaling
exposure by the screen's own breadth (median 63 qualifying names in 2008 against
206 overall) cuts max drawdown from **−55.4% to −39.1%** at beta 0.69. Left
always-invested it draws down *worse* than the index.

And the caveat outweighs the result: **2,129 of 2,130 panel symbols still trade
at the panel end, and zero of the 2,006 names ever held stopped trading.** On a
panel with the losers removed, the screen still fails to beat the index.

## Setup timing (`strategylab/setups/`)

The Minervini trade, fixed rather than searched: breakout from a base, stop at
the support beneath it with risk capped, take profit at 2R.

```bash
.venv/bin/python -m strategylab.setups.cli timing
```

Fixing the trade makes the question binary, and the bar exact: **for a driftless
random walk the probability of touching +2R before −1R is 1/3**, so "does the
hit rate beat breakeven" is literally "do these setups drift up".

**The trigger is a negative signal.** Against a control of *buy a random
qualifying name from the same universe on the same day with the same geometry,
that did not break out*, the breakout hits 31.3% versus the control's 34.3%
(t = −2.06), and the vault agrees (28.8% vs 33.5%). Waiting for the base to
break costs about three points of hit rate against simply owning the screen.

Two conditioners do time it — `rs_rank` (+9.7pp, t = +4.15, ρ = +0.90) and
`reversal_5d` (+8.0pp, t = +3.34), the latter saying breakouts that fire
*without* a preceding run-up work better, which is Minervini's own
don't-buy-extended rule recovered from data. **But neither lifts expectancy**,
and stacking them matches their control to the decimal on dev. They select
better stocks, not better triggers — and the control gets the same stocks.

The reason hit rate and expectancy come apart is that R is not fixed: gaps
through the stop cost **1.31R**, not 1.00R (8% of trades), and 26% of trades
time out unresolved earning **+0.50R**, which is where a meaningful slice of the
profit lives. See `research/SETUP-TIMING-FINDINGS.md`.

| Module | Role |
|---|---|
| `setups/detect.py` | Base pivot, breakout trigger, support stop, 2R geometry, matched pseudo-setups |
| `setups/outcomes.py` | First-barrier resolution with gap fills and the ambiguous-bar rule |
| `setups/vcp.py` | Base structure: contraction sequence, volume through the base, pivot tests |
| `setups/portfolio.py` | The setup book: slot cap, risk-based sizing, gross cap, slot contention |
| `setups/study.py` | Pre-registration, breakeven arithmetic, conditioner timing tests |

`cli.py book` runs the setup strategy **as a portfolio with a position cap**.
Three findings per-trade statistics cannot show: the **cap and the risk per
trade are one knob** (at 1% risk with a 9% stop each position is ~11% of the
book, so 100% gross admits ~9 positions and caps above 10 are inert —
"20 names at 1% risk" does not exist); **capacity binds, not opportunity** (the
book can act on 1-9% of 25,257 setups); and **nothing beats holding the screen**
— the one cell above benchmark (Sharpe 0.79) reverses on dev, and RS-ranked slot
selection is no better than random.

`cli.py base` tests whether the **shape of the base** times the breakout — the
last place timing could live, since name-level conditioners were shown to lift
the control equally and 95% of setups already occur with the benchmark above its
200-day average (the screen is itself a regime filter). Twelve VCP features:
**nothing clears the bar**, the best is `final_tightness` at t = +1.95 against a
required ≈3.0, and a combined score flips sign between dev (ρ = −0.70) and vault
(ρ = +0.90).

`cli.py trail` runs the fixed 2R target head-to-head against converting to a
moving-average trail at the target, paired on identical setups. **SMA21 hurts**
(−0.033R/trade, t = −3.37); **SMA50 is free on the mean** (t = −0.02) and triples
the maximum win (36% → 185%). Same expectancy, far more skew — a sizing choice,
not a signal one.

## The discovery loop (`strategylab/discover/`)

Iteration — propose, test, learn, repeat — built so that **"no alpha" is a
finishable answer**. A loop told to run until it finds alpha will find alpha:
the maximum of N noise draws grows like `sqrt(2 ln N)`, so a fixed |t| > 2 is
breached 99%+ of the time once a search reaches N = 500 (pinned as a test).

```bash
.venv/bin/python -m strategylab.discover.cli run --iterations 40
.venv/bin/python -m strategylab.discover.cli status
```

Three properties are built in rather than bolted on:

- **The bar rises with the trial count** — `sqrt(2 ln N) + 0.5`, so 2.00 at one
  hypothesis, 3.53 at a hundred, 4.22 at a thousand. The deflated-Sharpe idea
  the genome search already uses, applied to t-statistics.
- **Failures count.** The registry is append-only and persists across restarts,
  recording every hypothesis executed including cheap rung-0 rejects. A run
  resumed tomorrow inherits today's trial count and today's higher bar.
- **The space is finite** — 440 hypotheses over `(primitive, transform, outcome,
  horizon)` — so "all of them tested, none cleared" is terminal. A generative
  proposer can always produce one more and therefore can never conclude.

To be **confirmed**, a hypothesis must clear the rising bar on dev with
Newey-West errors, have a clean shuffled-label placebo, beat its matched control
(incremental after the momentum controls, or the no-trigger book for setup
conditioners), and confirm on the vault with the same sign. Every vault use is
logged. See `research/DISCOVERY-LOOP.md`.

**First full run: 440 hypotheses, 0 cleared, 0 confirmed, space exhausted in ~5
minutes.** Max |t| was **3.72** against a theoretical noise maximum of
`sqrt(2 ln 2N)` = **3.68** — the single best result out of 440 is exactly the
size a search this wide produces from nothing. The best one of all also had its
shuffled-label placebo fire at +2.03 and was correctly rejected. The run exposed
a defect too: `negate` was an exact duplicate under a two-sided test (83 of 88
pairs mirrored), inflating the trial count; removed, leaving 352 hypotheses and
a bar of 3.92, against which the conclusion is unchanged.

The loop is validated in both directions: `test_loop_finds_a_planted_signal`
asserts it surfaces a genuine planted effect at |t| > 3, and
`test_loop_confirms_nothing_on_pure_noise` asserts it comes back empty on a
panel with nothing in it.

| Module | Role |
|---|---|
| `discover/hypothesis.py` | The finite, enumerable, hashable hypothesis grammar |
| `discover/registry.py` | Append-only record of every hypothesis — the thing that sets the bar |
| `discover/execute.py` | Two-rung evaluation against matched nulls and controls |
| `discover/loop.py` | The rising bar, the judge, and the stopping conditions |

## The middle layer (`strategylab/pipeline/`)

Working backwards: label every eligible name-day by whether it *did* beat SPY
over a swing horizon, then ask what perfect selection would earn and how much is
predictable. This is the first **multivariate** test in the project — every
earlier one was univariate and structurally blind to interactions.

**The prize is enormous and none of it is reachable.** Perfect selection of the
top decile earns **+11.6% excess every ten sessions**. A gradient-boosted model
over all 22 features, 302k training rows, tested on the sealed vault with a
21-day embargo, scores **AUC 0.494** — a coin flip — and its top decile
underperformed its bottom decile. Train AUC 0.58 against test 0.49 is the
signature: it fits, and none of what it fits generalises. Same answer at 5, 10
and 21 days; the shuffled-label control sits at 0.50 throughout.

Also worth noting: names passing the Minervini screen beat SPY **49.6%** of the
time. The screen selects strong trends and does not tilt the odds.

This explains the earlier nulls rather than adding to them — the univariate
tests were not failing to find the right signal; there is no signal in price and
volume to find. A middle layer needs **new information** (fundamentals, flow,
news), not a better model over the same information.
See `research/MIDDLE-LAYER.md`.

| Module | Role |
|---|---|
| `pipeline/attainability.py` | The oracle ceiling, and whether a joint model can reach any of it |

## Module map

| Module | Role |
|---|---|
| `genome.py` | The 95-dimension action space, bounds, repair invariants, hashing |
| `config.py` | The experiment protocol — dates, costs, folds, reward weights, gates |
| `data/prices.py` | Split+dividend-adjusted OHLCV, disk cache, aligned panel |
| `data/universe.py` | Membership (incl. delisted) vs. per-day eligibility |
| `data/fundamentals.py` | Filing-date-aligned PIT growth metrics |
| `data/news.py` | Session-aligned news-impact sentiment from Supabase |
| `features.py` | Memoised feature matrices — computed once, shared by every trial |
| `strategy.py` | Genome → eligibility, trigger, ranking, regime |
| `backtest.py` | Event-driven portfolio simulator |
| `metrics.py` | Performance stats + PSR / DSR / PBO |
| `validation.py` | Data context, purged folds, fidelity ladder, sealed vault |
| `reward.py` | Reward shaping and the acceptance gate |
| `investigate.py` | The critic: findings with evidence and genome directions |
| `search.py` | Mutation operators, UCB1 bandit, TPE surrogate |
| `policy.py` | Claude as experiment designer (structured patches + hypotheses) |
| `ledger.py` | SQLite replay buffer and audit trail |
| `loop.py` | The orchestrator |
| `deploy.py` | Frozen genome, strategy card, live signal generator, registry script |
| `charts.py` | Search progress and strategy performance, plus the HTML contact sheet |

## Output

Everything lands in `output/runs/<run_id>/`:

```
ledger.sqlite          every trial, its metrics, diagnostics and returns
report.md              leaderboard, what the winner changed, operator stats
deploy/
  strategy.json        frozen genome + the protocol it was validated under
  strategy_card.md     dev and vault numbers, gates, DSR/PBO, limitations
  signals.py           standalone daily order generator
  nis_evolved.py       drop-in script for the swingtrader screenings registry
```

`deploy/` is only written when the finalist clears every gate *including* the
vault. `--force-export` overrides that; the strategy card then says, in bold,
that the thing is not deployable.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

The ones that matter: no-look-ahead causality, costs strictly reduce returns,
stops are honoured through gaps, capacity truncation binds, the deflated Sharpe
tightens as the search widens, PBO ≈ 0.5 on pure noise and low on a real edge,
and no genome is ever evaluated twice at the same rung.
