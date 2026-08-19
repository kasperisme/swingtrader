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
