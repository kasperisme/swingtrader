---
name: nis-breakout-alert
description: >-
  Hourly in-session breakout poster. Checks the breakout-screening agent's latest
  result; when NIS Momentum tickers have just CONFIRMED price+volume breakouts, it
  renders ONE roundup reel — a live board of all the breakouts with the single most
  significant one highlighted and featured — and posts it immediately to Instagram +
  TikTok via Zernio. Built to run on a loop (`/loop 1h`). Use when the user wants to
  "auto-post breakouts", "alert on breakouts every hour", "run the breakout poster",
  or post whatever just broke out. The breakouts are LIVE (happening now) — the whole
  point is speed and urgency/FOMO, not a coiled-setup watch.
---

# NIS Breakout Alert (hourly roundup auto-poster)

A confirmed breakout is a **perishable, happening-now** event — the opposite of the
coiled "watch the pivot" setups that `nis-stock-breakdown` handles. This skill turns
the breakout-screening agent's live triggers into **one roundup reel per hour** — a
board of *every* ticker breaking out, with the single most significant one highlighted
and then featured in full — and ships it **immediately**, because the only edge is
being first while the moves are on the tape.

Each invocation = **one hourly check**. Run it via `/loop 1h` (the harness handles the
cadence; this skill does a single iteration). It is safe to run any time: outside
market hours the agent returns `skipped` and this skill quietly no-ops.

It **reuses** the `nis-stock-breakdown` render scripts and the `social_publishing`
publisher; it adds the trigger-read, the live-breakout framing, the board renderer,
and dedup.

---

## Step 1 — Read the latest triggers (and decide whether to act)

```bash
cd code/analytics
mkdir -p output/breakout_alert
.venv/bin/python ../../.claude/skills/nis-breakout-alert/scripts/breakout_pick.py \
    > output/breakout_alert/board.json
cat output/breakout_alert/board.json
```

`breakout_pick.py` reads the most recent `user_screening_results` row for the breakout
screening (`screening_id a884970e-dc2f-45c8-8e91-9d0504bebf12`) and prints JSON:

- **`{"action":"none", ...}`** — nothing to do. Happens when the run is `skipped`
  (market closed), `triggered=False`, or the headline ticker was already alerted within
  the dedup window. **Report the one-line reason and STOP.** This is the common path —
  do not render or post.
- **`{"action":"post", "featured":{...}, "board":[...], "summary":..., "triggered_count":N}`**
  — breakouts to post. `board` is *every* triggered ticker, ranked (dual-timeframe
  `daily+1h` > daily-confirmed > highest volume); `featured` is `board[0]`, the single
  most significant breakout (the headline). Each entry carries `ticker`, `confirmed_on`,
  `daily`/`1h` (`price`,`entry`,`vol`×), `max_vol`.

Keep `board.json` — Steps 2–3 read it. Let `TICKER` = `featured.ticker`,
`RESULT_ID` = `result_id`.

---

### The LIVE-breakout hook (urgency + FOMO is the whole game)

The featured ticker's reel opens on a present-tense, live, FOMO hook (`--hook-text`
below). There the move is *imminent* in `nis-stock-breakdown`; **here it is HAPPENING**.
The volume multiple is the scroll-stopper. Under 15 words · present tense · lead with
"now/just/live" + the `N`× volume · no hedging.

| Pattern | Example (from the trigger facts) |
|---|---|
| Live + volume number | "$<TICKER> is breaking out **right now** — on `N`× normal volume." |
| Just-triggered + FOMO | "$<TICKER> **just triggered** — most watchlists won't catch it until it's too late." |
| Dual-timeframe proof | "Breakout **happening live** — $<TICKER>, both timeframes, volume exploding." |

Use "both timeframes" only when `featured.confirmed_on == "daily+1h"`. Never say "watch
the pivot" or "coiled" — it already broke.

---

## Step 2 — Build the roundup reel (one self-contained command)

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-breakout-alert/scripts/build_breakout_reel.py \
    --board output/breakout_alert/board.json \
    --hook-text "<live-breakout hook>" \
    --out output/breakout_alert/reel_breakout.mp4
```

`build_breakout_reel.py` renders the **whole** reel itself — no `build_setup_chart` /
`build_chart_reel` needed. Three movements, 1080×1920, faststart:

1. **Animated hero** — radial-vignette + parallax ticker chips + glow + count-up of how
   many broke out.
2. **Live breakout board** — depth-card leaderboard with volume bars, the headline
   (`featured`) highlighted with a ★ ribbon, staggered reveal.
3. **The headline's 1-HOUR breakout** — it fetches the featured ticker's intraday
   1-hour candles (FMP) and animates the move: candles draw in, then **support &
   resistance lines wipe in** (labels slide, the broken resistance flashes), with the
   surge volume bars amber and a breakout arrow at the bar that tagged the level. This
   is the *intraday* event, NOT the daily breakdown.

It reads the headline + its breakout facts (level, `N`× volume, timeframe) straight from
`board.json`. If the featured ticker's 1-hour fetch fails, re-run pointing `board.json`
at the next entry, or no-op this hour.

---

## Step 3 — Write the roundup caption (`output/breakout_alert/caption.txt`)

First 125 chars = the live headline (the featured ticker + its `N`× volume). Then: how
many broke out (`triggered_count`), name a few of the board's standouts (from `summary`),
then the headline's level + the `N`× volume, one
invalidation line, CTA to `newsimpactscreener.com`, disclaimer, 8–14 hashtags (no
emojis). Anchor every number in `board.json` / `setup.json`. Lead with urgency — the
breakouts are the news.

---

## Step 4 — Publish immediately (no scheduling — it's live)

A live breakout cannot be scheduled for later. Publish the roundup file directly (ad-hoc
mode — it lives outside the per-ticker dirs):

```bash
cd code/analytics
.venv/bin/python -m services.social_publishing.cli publish \
    --ticker breakout-<TICKER> \
    --media output/breakout_alert/reel_breakout.mp4 \
    --caption-file output/breakout_alert/caption.txt \
    --platforms instagram,tiktok
```

The publisher polls each platform to a real `published`/`failed` and prints the live
URLs. (Faststart is baked in, so Instagram lands first try.)

---

## Step 5 — Record the alert (dedup) and report

```bash
.venv/bin/python ../../.claude/skills/nis-breakout-alert/scripts/breakout_pick.py \
    --mark-posted <TICKER> --result-id <RESULT_ID>
```

This stamps the **headline** ticker in `output/breakout_alert/posted.json`, so the next
hourly run won't re-post until a *different* ticker becomes the most significant breakout
(or `DEDUP_HOURS` = 18h elapses). Then report: how many broke out, the headline + its
facts, the hook used, and the two live post URLs.

---

## Operating rules (fast, honest, non-spammy)

- **One roundup reel per hour, max.** The board holds all breakouts; only `board[0]` is
  featured. Never fan out into multiple reels.
- **Dedup on the headline.** Always `--mark-posted <TICKER>` after a successful post. The
  board reshuffles hour to hour; you only re-post when the #1 breakout *changes*, so the
  feed isn't spammed with near-identical reels.
- **No-op is the normal outcome.** Skipped / not-triggered / headline-unchanged → stop
  cheaply. Don't manufacture a post when there's no fresh breakout.
- **Honesty still applies.** Only claim what the triggers show (`N`× volume, confirmed
  timeframe, board count). Don't invent earnings/levels. If the headline is a weak name
  (sub-$20, ugly chart) and a stronger board entry exists, feature the stronger one —
  the same reel-ability judgment as `nis-stock-breakdown`, applied fast.
- **Live = publish now.** This skill never schedules; the value is immediacy.
```
