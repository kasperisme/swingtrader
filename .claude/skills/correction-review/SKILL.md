---
name: correction-review
description: >-
  Run the drawdown correction stress test as an AGENT-PANEL review in this local
  Claude Code session. Refreshes the rule baseline (narrative stress test with
  per-company cost of equity, mid-cycle margins for cyclicals and earnings
  quality), builds BLIND sector batches with news and tape, and for each batch
  fans out four specialist subagents (narrative-analyst, earnings-analyst,
  news-analyst, market-analyst) whose reports a verdict-analyst weighs to pass
  the final verdict per ticker. The verdict is committed to an append-only
  ledger before the rule's answer is revealed, re-solved in Python and checked
  against its own numbers, then sealed into the reviewed scorecard that
  /correction and drawdown-picks read. Use when the user wants to "review the
  stress test", "run the correction review", "re-judge the correction list", or
  before drawdown-picks when today has no reviewed scorecard. NOT the trade list
  itself (drawdown-picks).
---

# Correction review

The stress test (`code/analytics/services/drawdown/narrative.py`) asks, for each
name with a priced-in reconstruction, whether the growth the share price requires
is still funded by analyst forecasts once this correction cuts them. Python does
the arithmetic. Judgement is done by a panel of agents per batch:

| Seat | Agent | Judges | Reads |
|---|---|---|---|
| Narrative | `narrative-analyst` | story credibility, cycle, the channel the correction reaches it through, suggested cut | valuation, narrative, links |
| Earnings | `earnings-analyst` | quality flags real or artefact, through-cycle margin | valuation, quality |
| News | `news-analyst` | what changed since the narrative, tone, event risk, short-side hazards | scored news, sentiment, links |
| Market | `market-analyst` | trend, whose drawdown, economic epicenter exposure, liquidity | tape (returns, MAs, ATR, vol, beta, ADV) |
| **Verdict** | `verdict-analyst` | **margin, cut, exposure, group, thesis — the final call** | the four reports + valuation |
| Arithmetic, audit | Python (`judge.py`, `ledger.py`) | re-solve, consistency, blind/commit gate, seal | — |

**What keeps it honest:**
- Batches are **blind**: no rule group, cushion or cut is in them.
- The verdict analyst **commits** its draft to `output/drawdown/ledger.jsonl`
  before `judge reveal` shows the rule.
- `judge check` rejects any of these unless the reason is written:
  - a verdict its own numbers do not support
  - a margin more than 25% from consensus
  - a `high` exposure with less than a bust cut
  - an on_top without a recovery case
  - a change from the draft
- Overrides are capped at 10% of a batch.
- The rule's group stays in `rule_grp`, so panel and rule can be graded against
  each other later.

All commands run from `code/analytics`.

## 1. Refresh the baseline

```bash
.venv/bin/python -m services.drawdown.cli snapshot --no-db   # only if today's snapshot is missing
.venv/bin/python -m services.drawdown.cli narrative --no-db  # rule baseline, ~4 min (statements cached 7 days)
.venv/bin/python -m services.drawdown.cli judge batches --size 80   # blind batches + per-role inputs, ~1 min
```

- `price_failed` in the narrative output should be empty. A run of failures is
  FMP rate limiting; rerun.
- `judge batches` prints the batches. `batches/index.json` holds every path:
  - `inputs.<role>`: the role's view of the batch
  - `panel.<role>`: where the role writes its report
  - `draft` and `out`
- With `--size 80` there are about 6–7 batches: 5 agents each, roughly 30–35
  agents in all. Tell the user the count before fanning out.

## 2. Specialists: all batches, all four roles, in one message

For every batch, spawn the four specialists **in a single message** so they all
run in parallel. Each prompt is only:

```
mode: review
input: <inputs.<role> path>
out:   <panel.<role> path>
Today is <date>. Report on every name as your instructions describe, then reply with the summary.
```

Do not paste file contents, and do not judge names yourself while they run. If
one fails, re-spawn that one.

## 3. Verdicts: one verdict-analyst per batch, in one message

Once a batch has all four reports, spawn its `verdict-analyst`:

```
mode: review
batch:  <path>
input:  <inputs.verdict path>
reports: narrative=<…> earnings=<…> news=<…> market=<…>
draft:  <draft path>
out:    <out path>
Today is <date>. Draft blind, commit, reveal, finalise and pass `judge check`, as your instructions describe.
```

## 4. Check, then read across batches

```bash
.venv/bin/python -m services.drawdown.cli judge check --batch <batch_NN.json>
```

- **A batch is not ok:** `SendMessage` its verdict analyst the issues. Never edit
  an agent's judgements yourself.
- **Read across batches.** You are the only one who sees all of them. Spot-check:
  - The epicenter names (NVDA, AVGO, AMD, TSM, ASML, MU, MSFT, GOOGL, AMZN,
    META, ORCL), which sit in different batches. Are their cuts and margins
    coherent with each other?
  - An AI supplier's cut against a utility's.
  - Peers in the same industry with different margins.

  Message both verdict analysts with the comparison and let them reconcile.
  Their changes need a `revision_reason`.

## 5. Manifest, then apply

Write `output/drawdown/judged/<date>/manifest.json`:

```json
{"reviewer": "claude-code panel: narrative/earnings/news/market -> verdict",
 "model": "<your model id>", "date": "<date>",
 "agents": {"batch_01": {"narrative": "<agent id>", "earnings": "…", "news": "…", "market": "…", "verdict": "…"}}}
```

```bash
.venv/bin/python -m services.drawdown.cli judge apply --manifest output/drawdown/judged/<date>/manifest.json
```

This writes the reviewed scorecard, an immutable copy under `runs/<time>/`, and a
ledger entry hashing the full judgements.

`--db` also publishes to Supabase, and so to the public `/correction` pages. Use
it only when the user asks to publish, and only after migration
`20261121180000_drawdown_narrative_scores.sql` is applied. The publication fixes
(label agent-written theses, show rule vs panel) must land first.

## 6. Report

Tell the user:
- group counts, panel vs rule (`groups` vs `rule_groups`), and `moved`
- the most consequential moves, with the panel's reason
- `overrides`, and any `not_valued` calls
- the seal and the ledger entry. If `prior_entries_today` > 0, this is a re-run
  and the first entry is the one that counts.
- the agent count

Say plainly that neither the rule nor the panel has been graded yet.
