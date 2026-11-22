---
name: drawdown-picks
description: >-
  Produce the top 10 longs and top 10 shorts for the 1-3 months after the
  2026-11 correction, agent-driven in this local Claude Code session. Starts
  from the panel-reviewed correction stress test (runs correction-review first
  if today has none). The session, acting as portfolio manager, chooses which
  candidates deserve research; a DEEP PANEL of specialist subagents (narrative,
  earnings, news, market — with web research on guidance, takeovers, short
  interest, catalysts) reports on each candidate and a verdict-analyst passes
  pick / watch / kill with a trade plan; the PM builds a sized, beta-neutral
  book; a pick-skeptic attacks it; the final 20 are sealed into an append-only
  ledger and graded later with stops honoured and beta-adjusted alpha. Use when
  the user asks for "top 10 longs and shorts", "what to long/short in this
  correction", "the drawdown picks", or to grade earlier picks. NOT the
  stress-test review itself (correction-review), and NOT the OpenClaw screening
  agents or the Arena.
---

# Drawdown picks

**Who does what.** You, the session, are the portfolio manager: you choose what
to research and build the book. Agents research and judge each name. Python only
supplies data, enforces book rules and keeps the ledger. It never ranks or
chooses.

| Step | Who | Writes (under `output/drawdown/picks/<date>/`) |
|---|---|---|
| Reviewed stress test | `correction-review` skill | `../../judged/<date>/scorecard.json` |
| Candidate pool | Python `picks pool` | `pool.json`: every candidate, with tape, alphabetical; illiquid shorts out |
| Choose what to research | **you** | `research_queue.json` |
| Evidence | Python `picks dossiers` | `dossiers/<T>.json` |
| Deep batches | Python `picks deep` | `deep/deep_NN.json` (one side, ≤ 8 names) |
| Specialists | `narrative-` `earnings-` `news-` `market-analyst`, mode deep | `deep/deep_NN.<role>.json` |
| Verdict per ticker | `verdict-analyst`, mode deep | `deep/deep_NN.verdict.json` |
| Build the book | **you** | `picks_draft.json` |
| Attack it | `pick-skeptic` | `skeptic.json` |
| Seal, then grade | Python `picks seal` / `picks grade` | `picks_sealed.json`, `grade_<date>.json`, ledger |

All commands run from `code/analytics`.

**What this is.** A research book sealed so it can be graded. It is not a
backtested strategy and not investment advice. Neither the stress test nor the
panel has been graded, and this project's own walk-forward found that
price-implied growth alone does not predict returns. Say so when presenting.

## 1. Make sure today is reviewed

`ls output/drawdown/judged/$(date +%F)/scorecard.json`. If it is missing, run
`correction-review` first. `picks pool` refuses a rule-only scorecard.

## 2. Pool, then choose (you)

```bash
.venv/bin/python -m services.drawdown.cli picks pool
```

The pool shows, per name:
- the panel's group, cushion and cut
- `sector_pct`: where its cushion sits within its sector
- trend, 3-month return, beta, quality, exposure

Choose about **15 longs and 15 shorts**, and write `research_queue.json` as
`{"long": [{"ticker", "why"}], "short": [...]}`.

Choose for a book, not a list. The council's main finding was that the raw
stress test is long high-beta laggards and short low-beta leaders: one factor
bet. So:

- **Rank within sectors.** Prefer longs with high `sector_pct` and shorts with
  low `sector_pct`, so each side has a sector-matched counterpart where possible.
- **Look for a turn, not a level.** A long in a `down` trend with no basing is
  early. A short in a strong `up` trend with nothing coming is a squeeze waiting.
- **Mix exposure.** At most about 4 high-exposure names per side in the queue
  (the book allows 3).
- **Look for pairs:** a long and a short in the same industry that share a driver.

## 3. Dossiers, deep batches, panel

```bash
.venv/bin/python -m services.drawdown.cli picks dossiers --tickers <all queued, comma-separated>
.venv/bin/python -m services.drawdown.cli picks deep --file output/drawdown/picks/<date>/research_queue.json
```

That makes about 4 deep batches. **In one message**, spawn the four specialists
for every batch, about 16 agents:

```
mode: deep
side: <side>
dossiers: <the batch's dossier paths>
out: <deep_NN.<role>.json>
Today is <date>. Research every name as your instructions describe (deep mode) and reply with the summary.
```

When a batch's four reports are in, spawn its `verdict-analyst`:

```
mode: deep
batch: <deep_NN.json>
reports: narrative=<…> earnings=<…> news=<…> market=<…>
dossiers: <dir>
out: <deep_NN.verdict.json>
Today is <date>. Pass pick / watch / kill per name with a trade plan and pass `picks deep-check`.
```

Do not research the names yourself while they run.

## 4. Build the book (you)

Take `pick` verdicts first. Use a `watch` only if you can say why its concern
does not bite within the horizon. Never use a `kill`.

`picks seal` enforces these rules:
- 10 per side, and no name on both sides
- per side: at most 3 per sector, and at most 3 high-exposure or
  epicenter-linked names (`exposure: "high"` or `epicenter_linked: true`)
- every pick carries:
  - `ticker, sector, thesis, evidence[], catalyst, invalidation, risk, conviction (1-3)`
  - `entry {type, level, expires}`, `stop {price, basis}`, `target`
  - `size_pct` (% of NAV, at most 20)
  - `earnings_date`, `pre_earnings_action` (hold / halve / wait)
- gross per side is 80–120% of NAV
- **beta-weighted net within ±10% of NAV.** Seal stamps each beta from the tape
  first, so size the sides with the betas in `pool.json`.
- shorts carry `short_interest_pct_float` (≤ 15) and `days_to_cover` (≤ 5). Null
  is refused.

Size so that each position risks about 0.5–1% of NAV to its stop. Write
`picks_draft.json`:

```json
{"horizon_days": 63, "scorecard_seal": "<pool.json scorecard_seal>",
 "long": [{…pick fields…, "exposure": "medium"}], "short": [...],
 "notes": "how the book is balanced: factors, beta, pairs"}
```

## 5. The skeptic

Spawn one `pick-skeptic` with `draft`, `deep` (the deep dir), `dossiers`, `pool`,
and `out: skeptic.json`. Then:
- Act on every `replace`, using a researched name or a new deep batch.
- Act on every `downgrade`, or say why not.
- Rebalance for each book-level risk, or accept it in `notes`.

Every disagreement goes in `notes`. Copy the skeptic's top three risks into
`skeptic_summary`.

## 6. Seal, then present

```bash
cp output/drawdown/picks/<date>/picks_draft.json output/drawdown/picks/<date>/picks.json
.venv/bin/python -m services.drawdown.cli picks seal --file output/drawdown/picks/<date>/picks.json
```

Seal:
- validates the book
- stamps betas and the reference closes
- hashes the **full** payload, theses included
- records that the entry is the **next session's open**
- appends to the ledger

A sealed day is never rewritten. Change your mind before sealing, not after.

Then, still before the next open, seal the counterfactual:

```bash
.venv/bin/python -m services.drawdown.cli picks control --date <date>
```

It draws 10 longs and 10 shorts at random from the pool, stratified by sector and
seeded from the scorecard seal. It records the research queue and the whole pool
as cohorts too, and hashes every specialist report into the ledger. `picks grade`
then reports the book against `picks_unmanaged` (the same names, no stops),
`queue`, `control` and `pool`. Without it, a graded book cannot say whether the
panel, your selection or the trade plans added anything over the rule. Never
skip it.

Write `report.md`. Present two tables (long and short). Each row shows:
- ticker, size, beta
- a one-line thesis
- the catalyst with its date
- entry, stop and target
- conviction

After the tables:
- the book's beta-weighted net and gross
- the factor notes and the three biggest risks
- the seal hash
- grading: `picks grade --date <date>` at 1 and 3 months. It honours stops,
  stops at the sealed horizon, reports sized P&L and beta-adjusted alpha, and
  counts names with no later price as stopped, not dropped.

Offer to publish the report as an artifact. Do not post it anywhere yourself.
