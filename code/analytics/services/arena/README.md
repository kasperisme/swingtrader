# services/arena

Nine AI agents, $100,000 each, one market — competing on **different ways of
reading the same data**, published live at `/arena`.

Every agent gets the same model, the same broker, the same risk limits, the same
starting cash and the same universe. What differs is **which slice of the
platform's data it can see** and the thesis it is told to trade on. That is the
whole experiment: if one wins, the difference in tools and prompt is the only
thing it can be attributed to.

Two of the nine are not intelligent at all, and they are the most important two.

---

## The roster

| Agent | Trades on | Tools |
|---|---|---|
| **The Headline Hunter** | LLM-scored news impact | `get_top_articles`, `get_ticker_news`, `get_ticker_sentiment`, `search_news`, `get_cluster_trends` |
| **The Skeptic** | the priced-in decomposition — only buys what the price does *not* contain | `get_priced_in*`, `search_priced_in_drivers`, `get_top_articles`, `get_ticker_news` |
| **The Breakout Rider** | the published screening boards (NIS Momentum et al.) | `get_screening_results`, `list_screenings`, sentiment/news, **+ FMP** |
| **The Accountant** | fundamentals only — **no access to the news layer at all** | `get_company_vectors`, **+ FMP** |
| **The Second-Order Thinker** | the 38k-edge relationship graph; never buys the name in the headline | `get_ticker_relationships`, `get_top_articles`, news/sentiment |
| **The Arbitrageur** | cointegrated pair z-scores, market-neutral, **the only agent allowed to short** | `get_pair_signals`, `get_ticker_news`, `get_ticker_relationships` |
| **The Crowd** | attention acceleration — news volume vs a ticker's own baseline | `get_trending_tickers`, sentiment, news, `get_dimension_trends` |
| **The Index** *(control)* | buys SPY on day one, holds forever | none — deterministic Python |
| **The Coinflip** *(control)* | uniformly random picks, weekly, seeded | none — deterministic Python |

**Why the controls exist.** A leaderboard of seven strategies with nothing to
beat is a ranking, not a result — and the loudest, most confident-sounding
narrative would win the marketing even if it lost the money. `the-index` is the
hurdle (anyone can buy SPY in one click). `the-coinflip` is the null hypothesis:
with nine competitors, somebody finishes first by luck alone, and this is how you
tell that apart from skill. Both run through the *identical* broker — same open
fills, same slippage, same marks — so their numbers are comparable rather than
merely adjacent. The coinflip's randomness is seeded on `(slug, session)`, so a
re-run reproduces the same draw and it cannot be quietly re-rolled until it looks
bad.

---

## The one rule that makes this credible

**An LLM's only write is an order intent.** It calls `place_order`; that is the
entire surface. Cash, positions, fills, realised P&L and NAV are computed by
`broker.py` — deterministic Python — from the tables.

A model therefore cannot mark its own book, cannot spend cash it does not have,
and cannot revise a fill once the outcome is known. The database enforces that
last one too: `arena_orders` carries a trigger making a settled order immutable,
the same lesson as `research_predictions`.

Rejections are **stored, not discarded**. "The agent tried to put 80% of the book
in one name" is a finding about the approach, and it is published.

```
roster.py     WHO competes: one AgentSpec per approach (prompt, tools, risk)
decide.py     the LLM half: tool loop -> order INTENTS, nothing else
controls.py   the non-LLM half: index / coinflip baselines
    │
    ▼  (an intent is only ever a request)
broker.py     the deterministic half: validates, fills, marks, books P&L
store.py      persistence for both halves
marks.py      prices (session opens for fills, closes for marks)
scheduler.py  the daily clock
```

---

## The daily clock

Three passes, in this order, each idempotent per `(agent, session)`:

| Pass | When | What |
|---|---|---|
| `fill` | after the open | yesterday's queued orders execute at **today's open** + 5bp slippage |
| `mark` | after the close | positions marked to today's close; one NAV row appended |
| `decide` | after the close | each agent reads the closed session and queues for the **next** one |

Order matters. Marking before filling would value a book that does not exist
yet; deciding before marking would show an agent a stale NAV. `run-day` runs all
three in step, which is why cron calls that rather than the three separately.

**Fills happen at the next open, never the decision session's close.** An agent
decides on Monday's information and fills at Tuesday's open. Filling at Monday's
close would hand every agent a free overnight gap — the single easiest way to
manufacture a fake edge.

Sessions come from SPY's own bars: if the benchmark printed a bar, the market was
open. No holiday calendar to drift out of date, and it fails safe — no bar means
no session means no trading.

---

## Commands

```bash
cd code/analytics

# One-time: write roster.py into the DB and open the $100k accounts
.venv/bin/python -m services.arena.cli sync-roster

# The nightly job — this is what cron runs
.venv/bin/python -m services.arena.cli run-day

# Individual passes (debugging / backfill)
.venv/bin/python -m services.arena.cli fill   --session 2026-09-03
.venv/bin/python -m services.arena.cli mark   --session 2026-09-03
.venv/bin/python -m services.arena.cli decide --only the-skeptic [--dry-run]

# Inspect
.venv/bin/python -m services.arena.cli standings
.venv/bin/python -m services.arena.cli show the-skeptic
.venv/bin/python -m services.arena.cli orders --slug the-crowd

# Wipe one agent's trading history back to cash (keeps its definition)
.venv/bin/python -m services.arena.cli reset --slug the-coinflip --yes
```

`--dry-run` on `decide` prints the model, the exact tool list and the prompt
without calling the LLM or touching an order. Use it after editing a spec.

---

## Editing the roster

`roster.py` is the source of truth for prompts, tool access and risk limits;
`arena_agents` is a projection of it. Edit a spec, then:

```bash
.venv/bin/python -m services.arena.cli sync-roster
```

This updates definition columns only. Cash, positions and history belong to the
broker and are never touched, so **re-syncing after a prompt edit cannot reset a
running experiment**. Funding is likewise skipped for any agent that already has
an account.

Changing the **model** mid-competition invalidates the comparison — that is why
it is one env var (`ARENA_MODEL`) for the whole roster rather than a per-agent
default, so it has to be a deliberate act.

---

## Configuration

| Env var | Meaning |
|---|---|
| `ARENA_MODEL` | Model for every LLM agent. Falls back to `OLLAMA_NARRATIVE_MODEL`, then `OLLAMA_BLOG_MODEL`, then `glm-5.1:cloud`. |
| `OLLAMA_BASE_URL` | Default `http://localhost:11434`. |
| `APIKEY` / `FMP_API_KEY` | FMP prices (required — no prices, no fills) and the FMP MCP tools. |
| `SUPABASE_*` | As everywhere else in `analytics/`. |

Agents run **sequentially**, not concurrently: they share one Ollama backend and
one FMP key, and a stampede of nine tool-calling loops produces timeouts rather
than speed. A full roster pass is roughly 10-20 minutes.

---

## Schema

`supabase/migrations/20260903120000_arena_paper_trading.sql`

| Table | Holds |
|---|---|
| `arena_agents` | the competitors + their broker-enforced risk limits |
| `arena_accounts` | the single mutable cash row per agent |
| `arena_positions` | current book, one row per `(agent, ticker)`, **signed** quantity (`< 0` = short) |
| `arena_orders` | every intent, its fill or its rejection reason, and realised P&L on closes |
| `arena_decisions` | one row per agent per day: the published narrative + the machine trace |
| `arena_nav_history` | the append-only daily NAV curve |

Public views (`arena_*_public_v`, `arena_leaderboard_v`) filter on `is_published`
**in the view**, not in the page, so a forgotten `.eq()` in the UI cannot leak an
agent that is still being tuned. The Next.js side reads only those.

`realized_pnl` is set **only on the portion of a fill that closes exposure**;
opening fills carry NULL, so win-rate is computed over closes only.

---

## Tests

```bash
.venv/bin/python -m pytest tests/test_arena_broker.py -q
```

21 tests over the broker's accounting and risk gates, fully in-memory (no
Supabase, no FMP, no LLM). They cover the things that must be exactly right:
slippage direction, weighted average cost, realised P&L on partial closes and on
shorts, short proceeds crediting cash, NAV falling when a short moves against the
agent, drawdown against the running peak, and every rejection path.

If cash, average cost or realised P&L drift, every number on the public
leaderboard is wrong and no amount of good agent reasoning rescues it. Change the
broker, run these.

---

## Known limitations

- **No intraday risk management.** Agents cannot set resting stops; a position is
  only exited on the next daily run. `stop_price` on an order is recorded as the
  agent's stated invalidation level, not as a live order. Swing-trading horizon
  makes this defensible, but it is a real difference from live trading.
- **No dividends, no corporate actions.** Marks use unadjusted daily closes, so a
  dividend shows as a small drop in NAV that a real account would not take. Over
  months this biases every agent's return slightly low, equally.
- **Shorts have no borrow cost or margin requirement.** Only `the-arbitrageur`
  can short, and its gross-exposure cap is the only constraint.
- **Slippage is a flat 5bp** regardless of size or liquidity — optimistic for
  small caps, roughly right for large. The universe floor limits the damage.
- **A stale mark keeps the previous price** and is named in
  `arena_nav_history.positions.stale_marks` rather than being valued at zero.
