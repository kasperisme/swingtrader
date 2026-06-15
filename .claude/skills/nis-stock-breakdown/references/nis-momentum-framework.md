# NIS Momentum — Swing-Trade Breakdown Framework

Use this to read a stock the way the **NIS Momentum** screening reads it, then turn
those signals into a breakdown a swing trader can act on. A good breakdown always
covers the same four aspects — *the setup, the chart (price + volume), the
fundamentals, the trade* — anchored in real numbers, never vibes.

The numbers come from `scripts/build_setup_chart.py`, which runs the production
screener (`services.screener.technical`) and writes a `setup.json` with every
field below plus the derived trade. Read that file first; write from it.

---

## What NIS Momentum is

NIS Momentum (`code/analytics/services/market_screenings/scripts/nis_momentum.py`)
is a long-only trend-continuation screen. A stock only surfaces if it clears
three layers:

1. **Relative strength pre-screen** — IBD RS percentile `RS > 80` (top fifth of
   the market by 3M/6M/1Y blended return).
2. **Minervini Trend Template** (all must be true):
   - `PriceOverSMA150And200` — price above both the 150- and 200-day MAs.
   - `SMA50AboveSMA150And200` — the moving averages are stacked bullishly.
   - `SMA200Slope` — the 200-day MA is rising (long-term uptrend intact).
   - `PriceAbove25Percent52WeekLow` — well off the lows.
   - `PriceWithin25Percent52WeekHigh` — near the highs, not mid-base.
   - `PriceOverSMA50` — the NIS add-on; drops deep pullbacks below the 50-day.
3. **Growth fundamentals** — `increasing_eps` (EPS trend rising) **and**
   `beat_estimate` (last 3 earnings beat) → `PASSED_FUNDAMENTALS`.

So every NIS Momentum name is, by construction: strong vs. the market, in a clean
stacked uptrend, near its highs, with rising and beating earnings. The breakdown's
job is to show *where in that setup it is right now* and *what the trade is*.

---

## Aspect 1 — The setup (why it screened)

Lead with the one-line reason it's on the radar. Pull from `setup.json.technical`:

| Field | Read it as |
|-------|-----------|
| `RS_Rank` (1–99, lower = stronger) | "Top X% relative strength." Only trustworthy when it came from the screening run — see the RS note below. |
| `Passed` | All Minervini gates green. |
| `PASSED_FUNDAMENTALS` | Earnings rising **and** beating. |
| `rs_line_new_high` | RS line at/near a new high — leadership confirmed by the breakout. |

**RS note:** RS rank is a percentile *across the whole screened universe*. The
chart script can't compute it for a single ticker, so pass the real value from the
NIS Momentum run with `--rs-rank`; otherwise `setup.json` marks it unknown and you
must not state a rank.

## Aspect 2 — The chart: price + volume

This is the visual centerpiece. `build_setup_chart.py` renders it; the slide copy
narrates it. Read these:

**Price structure**
| Field | Read it as |
|-------|-----------|
| `SMA50` / `SMA150` / `SMA200` | The stacked MAs. Price riding the 50-day = healthy trend. |
| `pivot` | The base high = the O'Neil buy point. The level that matters. |
| `extension_pct` | How far price is above the pivot (%). |
| `within_buy_range` | 0–5% above pivot — the actionable zone. |
| `extended` | >5% above pivot — chasing; wait for a pullback. |
| `below_pivot` | Hasn't broken out yet — it's a watch, entry on the breakout. |

**Volume (the conviction tell)**
| Field | Read it as |
|-------|-----------|
| `vol_ratio_today` | Today's volume ÷ 50-day avg. >1.4 = institutional interest. |
| `up_down_vol_ratio` | Up-day vol ÷ down-day vol over 50d. >1.25 = accumulation. |
| `accumulation` | True when `up_down_vol_ratio` ≥ 1.25 — big money is buying dips. |
| `vol_contracting_in_base` | Volume drying up in the base — classic pre-breakout coil. |
| `adr_pct` | Average daily range %. 3–15% is the swing sweet spot; <2% too slow, >15% too wild. |

On the chart, **amber volume bars** mark days where volume ≥ 1.4× its 50-day
average — point to them: that's where conviction showed up.

## Aspect 3 — The fundamentals that matter

NIS Momentum is technically-led, so keep fundamentals tight — they're the
*why it's allowed to run*, not the thesis:
- `increasing_eps` — earnings trend is up.
- `beat_estimate` — last three quarters beat the estimate.
- `sector` / `subSector` — context for rotation ("leading the [sector] move").

If you want richer fundamentals (margins, growth %, valuation) pull the FMP
profile/quote via `services/viral_reels/data_sources.py::company_profile` /
`fmp_quote`, or the deep NIS-quality flags (`get_nis_flags`) — but don't bury the
setup in a fundamentals essay. Two or three numbers, max.

## Aspect 4 — The proposed trade (generated from the setup)

`setup.json.trade_setup` is computed deterministically from the screen's own
fields — this is the "trade generated from the NIS Momentum setup". The rules:

- **Direction:** long (NIS Momentum is a trend-continuation long screen).
- **Entry / status:**
  - `within_buy_range` → entry = current price, *actionable now*.
  - `below_pivot` → entry = the pivot, *watch — triggers on a breakout*.
  - `extended` → entry = the pivot, *wait for a pullback* (don't chase >5%).
- **Buy range:** pivot → pivot × 1.05 (O'Neil: never chase past +5%).
- **Stop:** 1.5 × `adr_pct` below entry, clamped to a 4–8% max loss; tightened to
  just under the 50-day MA when that's a cleaner structural level.
- **Targets:** 2R and 3R (R = entry − stop), plus the O'Neil +20–25% trim zone.
- **Reward:risk:** stated to the 2R target (≥ 2:1 by construction).

Always present the trade as **entry / stop / target / R:R**, and state the status
honestly — a "watch" is not a "buy now". Add the position-sizing reminder: risk
per share = entry − stop; size so the stop costs ≤ 0.5–1% of the account.

---

## What separates a sharp breakdown from a generic one

- **Every claim ties to a number in `setup.json`.** "Volume confirms" is dead;
  "up/down volume 1.6 — buyers showing up on the dips" is alive.
- **Name where it is in the setup.** In the buy range, extended, or still basing —
  these imply completely different actions. Say which.
- **The trade is concrete and honest.** Entry, stop, target, R:R, and whether it's
  actionable today or a watch. If it's extended, say "don't chase".
- **Fundamentals stay supporting cast.** Two beats and rising EPS — that's the
  permission slip, not the thesis. The thesis is the chart.
- **No hype.** No price targets pulled from the air, no "to the moon". The edge is
  the discipline of the setup, and that's what makes it shareable.
