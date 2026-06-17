---
name: ticker-pair-divergence
description: >-
  Produce a viral reel about a PAIR of tickers and the non-obvious relationship
  that makes them track each other — then how they've diverged into a
  mean-reversion (pairs) trade setup. Use when the user wants to "show a ticker
  pair", "how two stocks follow each other", "pairs trade", "cointegration /
  spread / z-score reel", "which stocks move together", or names two tickers and
  wants the relationship visualized. Pulls the relationship + stats from
  swingtrader.ticker_pair_stats (hedge ratio, cointegration p-value, OU
  half-life, live z-score) and the news-derived link type from
  ticker_pair_candidates_v, animates both as normalized line charts with each
  company's LOGO riding the right end of its line, walks the stats as the graph
  evolves, flags the divergence + the forming trade, and voices it like the
  nis-stock-breakdown reels. Always frames the relationship as something few
  people know. Trigger on "pairs reel for KO and PEP", "show how AMD and NVDA
  move together", "divergence trade on …".
---

# Ticker Pair Divergence

Turn a pair of tickers into a viral reel that reveals a relationship few people
connect, shows the two prices tracking each other (then pulling apart), and lays
out the mean-reversion trade that divergence sets up. Built on the same insights
as `nis-stock-breakdown`: lead with the weird/overlooked fact, walk the stats on
the evolving graph, point out the divergence + setup, voice it as a secret reveal.

The relationship is the hook. The cointegration is the proof. The divergence is
the trade. Every number is real — pulled from the pairs layer, never invented.

---

## Step 1 — Pick the pair

- **A pair is given** ("KO and PEP", "AMD/NVDA"): use it. It must already exist in
  `swingtrader.ticker_pair_stats` (calibrated). If not, calibrate first via
  `services/pairs/calibrate_cli.py`.
- **No pair given**: `--auto` picks the most-diverged *cointegrated* pair (highest
  `|current_zscore|` where `is_cointegrated`), so the mean-reversion thesis is honest.

Prefer pairs where the relationship is **non-obvious** (a supplier/customer/partner
link, not two mega-caps everyone pairs) and the stats support it
(`is_cointegrated = true`, a sane `half_life_days`, `|z|` stretching toward 2).

## Step 2 — Gather the data

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/ticker-pair-divergence/scripts/pair_data.py --pair DNUT/MCD
# or:  --auto
```

Writes `output/setups/pairs/<A>_<B>/pair.json` (+ downloads each logo PNG). It pulls:
- **ticker_pair_stats** — `hedge_ratio`, `coint_pvalue`, `is_cointegrated`,
  `half_life_days`, `spread_mean/std`, `current_zscore`, `n_obs`, `window_days`.
- **ticker_pair_candidates_v** — `rel_types` (the news-derived economic link:
  supplier / customer / partner / competitor / acquirer) + `article_count`.
- **FMP** — both adjusted-close series + company profile (name, sector, logo).

It then builds the normalized series (both indexed to 100), the **evolving z-score**,
the **divergence index** (where the spread starts stretching), and the
**mean-reversion trade** (long the cheap leg / short the rich leg → target z=0).

Read `references/pairs-framework.md` for how to read every field honestly.

## Step 3 — Animate the relationship

```bash
.venv/bin/python ../../.claude/skills/ticker-pair-divergence/scripts/animate_pair.py --pair DNUT/MCD
```

→ `pair_story.mp4` (+ `.gif`). The hero visual:
- **Hook card** — "NOBODY CONNECTS THESE TWO" + both logos + the non-obvious link.
- **Evolving line chart** — both prices normalized to 100, drawing left→right, with
  each **company logo riding the right end of its line** at the latest point.
- **Stats fill in** as the graph evolves: cointegration p-value → half-life → news links.
- **Divergence** — once the lines pull apart, the gap shades amber and is flagged;
  a "SETUP FORMING / LIVE: Long X · Short Y · Nσ apart" banner appears.
- **Outro** — the trade (long / short / target = the mean / ≈ half-life days) + CTA.

## Step 4 — Voice the reel

```bash
.venv/bin/python ../../.claude/skills/ticker-pair-divergence/scripts/build_pair_reel.py --pair DNUT/MCD
```

→ `reel.mp4`. ElevenLabs narrates the **secret-reveal** arc, time-stretched to the
animation so the commentary tracks the visuals:
1. the hook — "a pair almost nobody connects … and they trade like a tethered pair",
2. the proof — cointegrated, ~N-day half-life,
3. the divergence + setup — "stretched to Nσ — long X, short Y, betting the gap snaps back",
4. the takeaway — "few people watch these relationships. The screener does."
Then a **disclaimer card** (cointegration breaks; a spread can keep stretching).

Uses `$ELEVENLABS_PRIMARY_VOICE_ID` (override `--voice-id`).

## Step 5 — Write the caption

Save `output/setups/pairs/<A>_<B>/caption.txt`. First line = the hook (the
non-obvious relationship). Body: the link → cointegration + half-life → the
divergence and the long/short trade → the honest caveat (it can keep diverging) →
CTA + disclaimer + hashtags (#pairstrading #statarb + the two tickers).

## Honesty rules (non-negotiable)
- **Only call it "cointegrated" when `is_cointegrated` is true** (p < 0.05). Otherwise
  say "they've tracked each other / they tend to mean-revert" — not "cointegrated".
- **A divergence is a *setup*, not a certainty.** Say "forming" until `|z| ≥ 2`, and
  always note the spread can keep stretching (the disclaimer card does this).
- **Don't invent the relationship.** Use the real `rel_types`; let the copy explain
  the specific economic link (e.g. Krispy Kreme supplies McDonald's) only when true.
- **Direction follows the z-score**: z > 0 → spread rich → short A / long B (the
  data layer computes `long`/`short` for you).

## What makes a pairs reel good vs. generic
- The relationship genuinely surprises ("these two? really?") and is real.
- The chart *shows* the tracking-then-diverging — the logos make it instantly legible.
- The stats are the proof, delivered as the graph evolves, not dumped.
- The trade is concrete (long/short/target/half-life) and honestly hedged.
