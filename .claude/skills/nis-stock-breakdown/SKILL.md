---
name: nis-stock-breakdown
description: >-
  Produce an Instagram-ready breakdown of a single stock from a swing-trading
  perspective, anchored on the NIS Momentum setup. Use this whenever the user
  wants to "break down", "review", "make a post about", "do a setup on", or
  "analyze" a stock/ticker for swing trading — even if they don't say
  "Instagram". Renders an annotated technical chart (candles + volume highlights
  + entry/stop/target levels), surfaces the fundamentals that matter, and lays
  out a concrete proposed trade (entry, stop, target, R:R) derived from the NIS
  Momentum signals, then assembles a carousel + caption. Trigger on phrases like
  "break down NVDA", "swing setup for $TSLA", "make a post about this stock",
  "what's the NIS momentum read on X", or when a ticker is shared for a
  trade-idea breakdown.
---

# NIS Stock Breakdown

Turn one ticker into an Instagram-ready breakdown that shows *the setup, the chart,
the fundamentals, and the trade* — read the way the **NIS Momentum** screen reads a
stock. The deliverable is a carousel (slides + caption) plus a narrated reel built
around an annotated technical chart.

The audience is retail swing traders: smart, time-poor, allergic to hype. The
breakdown has to be **sharp, specific, and grounded in real numbers** — not "this
stock looks bullish". Every claim ties to a value the screener produced. The thesis
is the chart; fundamentals are the permission slip; the trade is concrete and honest
(including whether it's actionable today or just a watch).

---

## Step 1 — Pick the stock

Two ways in:

- **A ticker is given** ("break down NVDA"): use it directly, but still run it through
  the reel-ability gate below and *tell the user* if it's a weak reel candidate.
- **No ticker / "what's on the NIS Momentum board"**: run the screening and pick a
  name. The screen lives at
  `code/analytics/services/market_screenings/scripts/nis_momentum.py`; run it via
  the market-screenings runner/CLI, or pull the latest stored results the
  `/screenings` UI reads. Each row carries `symbol`, `RS_Rank`, `sector`,
  `within_buy_range`, `extended`, `accumulation`, `PASSED_FUNDAMENTALS`. Note its real
  `RS_Rank` to pass along in Step 2.

### The reel-ability gate — pick for *views*, not just for the screen

> **The biggest lesson from past reels: passing the screen ≠ making a watchable reel.**
> The two best-performing reels (ENVA 345 views, NWPX 219) were clean, higher-priced
> momentum names whose chart was visibly *launching* and whose data let the narration
> stay 100% confident. The two worst (RLJ 49, HOFT 29) passed the same screen but were
> hard to pitch without hedging — and the hedge killed the scroll.

The gate has **two layers**. Layer A is pure NIS Momentum methodology, expressed in the
screen's own fields and thresholds (see `references/nis-momentum-framework.md`) — a name
that's weak *here* is a weak NIS setup, not just a weak reel. Layer B is an editorial
overlay for *views* that sits on top — explicitly **not** part of NIS, so never present
it as the screen's verdict.

#### Layer A — NIS-methodology quality (use the screen's own constants)

Every board name already cleared `RS > 80`, the full Minervini stack, near-highs, and
`PASSED_FUNDAMENTALS`. For a reel, verify *where in the setup it is* and *whether volume
confirms*, in methodology terms:

- **Position in the buy range.** Prefer `within_buy_range` (pivot → +5%) or `below_pivot`
  but **coiled** — small negative `extension_pct` (roughly ≥ −5%) with
  `vol_contracting_in_base` true (the classic pre-breakout coil). **Avoid `extended`**
  (>5% above pivot — the framework says *don't chase*; a chase reel ages badly) and
  deep-below-pivot watches (e.g. HOFT at `extension_pct` −7% — a legitimate NIS *watch*,
  but the breakout isn't imminent, so there's no urgency to film).
- **Volume conviction — NIS's "conviction tell".** Require `accumulation` true
  (`up_down_vol_ratio ≥ 1.25`). **If the name is `within_buy_range`** (you're calling a
  live breakout), it also needs `vol_ratio_today ≥ 1.4` — the framework's
  institutional-interest bar. *This is the methodology-correct reason RLJ was weak:* it
  was in the buy range but printed `vol_ratio_today` ≈ 0.4× — a breakout on
  **below-average volume is an unconfirmed breakout by NIS's own rule**, so the pitch is
  forced to hedge. (For a `below_pivot` coil, low `vol_ratio_today` is *expected* and
  fine — but then narrate it as a watch, not a confirmed move.)
- **ADR in the swing band.** `adr_pct` 3–15% is the framework's sweet spot — **6% is
  fine** (HOFT's ADR was never the problem), and a 4–8% stop is just the methodology's
  own `1.5×ADR` clamp, not a flaw. Only flag `adr_pct` <2% (too slow — a flat-looking
  chart) or >15% (too wild).
- **Leadership signal (best hooks are the truest).** A real `RS_Rank` near the top
  (IBD 1–99, **higher = stronger**, so top-decile ≈ ≥ 90) and/or `rs_line_new_high` true
  (leadership confirmed before price) are the most methodology-honest scroll-stoppers —
  prefer names that have them. (Both are auto-fetched from the latest NIS Momentum
  screening in Step 2 — see the RS caveat.)

#### Layer B — reel-ability overlay (editorial, NOT NIS — for views only)

1. **Chart shape (most important).** The reel lives on `chart.png`: you want a *visibly
   accelerating uptrend* with recent candles pushing into the pivot (ENVA, NWPX).
   **Reject** choppy/range-bound charts or a red/falling last candle (HOFT). This is the
   visual expression of Layer A's "coiled near the pivot, volume confirming" — if Layer A
   is clean, the chart usually looks the part.
2. **Price legitimacy.** Prefer **price ≥ ~$30**. NIS has *no* price floor (RLJ $11 and
   HOFT $15 passed it fairly), but sub-$20 names read as "cheap" to this audience — the
   two losers were the two cheapest. An editorial preference, not a screen rule.
3. **Hook-able fundamentals.** A clean positive P/E with a clear positive earnings story
   photographs better than a turnaround. NIS *legitimately* passes a loss→profit
   turnaround (it can satisfy `increasing_eps` + `beat_estimate`), and the framework
   treats fundamentals as *supporting cast* — but a turnaround makes a weak hook (it
   admits the company was broken). Prefer clean names; this is a reel choice, not a
   fundamental gate.

If a *user-given* ticker fails the gate, build it if they insist — but say plainly which
layer/criterion it failed (and whether that's a NIS weakness or just a reel weakness). If
you're **picking** from the board, take the name that's strongest on Layer A *and* clears
Layer B — not merely the most "actionable" one.

---

## Step 2 — Gather the data + render the chart

One command does both — it runs the production screener and writes the chart plus a
`setup.json` you'll write every slide from:

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_setup_chart.py \
    --ticker NVDA --display-days 180 --rs-rank <rank from the screen>
```

Outputs under `code/analytics/output/setups/<TICKER>/`:
- `chart.png` — 1080×1350 annotated chart: candlesticks, SMA50/150/200, volume bars
  (amber where volume ≥ 1.4× its 50-day avg), the buy-range band, and entry/stop/
  target lines.
- `setup.json` — `price`, `technical` (RS, SMA stack, `pivot`, `extension_pct`,
  `within_buy_range`/`extended`, `adr_pct`, `vol_ratio_today`, `up_down_vol_ratio`,
  `accumulation`, `rs_line_new_high`, SMA values), `fundamentals`
  (`increasing_eps`, `beat_estimate`, `PASSED_FUNDAMENTALS`), and the derived
  `trade_setup` (entry / stop / target_2r / target_3r / risk_pct / R:R / status).

**RS caveat:** RS rank is universe-relative and can't be computed for one ticker, so
`build_setup_chart.py` **auto-fetches the latest stored NIS Momentum screening** for the
ticker (Supabase `market_screening_result_rows` → `market_screenings.script_key =
'nis_momentum'`) and fills `RS_Rank` (IBD 1–99, higher = stronger), `RSOver70`, and
`rs_line_new_high`. `setup.json.rs_rank_source` records the scan date. Pass `--rs-rank`
only to override with a fresh value. If no stored screening exists, the rank is marked
unknown — don't state one.

For richer fundamentals (margins, growth, valuation) or a CEO/company profile, pull
from `code/analytics/services/viral_reels/data_sources.py` (`company_profile`,
`fmp_quote`, `news_pulse`). Keep it tight — two or three numbers.

---

## Step 3 — Read the framework

Read `references/nis-momentum-framework.md`. It explains exactly how to interpret
every field in `setup.json` across the four aspects (setup / chart / fundamentals /
trade) and how the trade is derived. Anchor the whole breakdown in those values —
where the stock is *in the setup right now* (basing, in the buy range, or extended)
drives what the post tells the reader.

---

## Step 3.5 — The narrative spine: the Hot Take Arc (non-negotiable)

> **The single structural lesson from past reels.** The winners (ENVA, NWPX) and
> losers (RLJ, HOFT) *all opened a loop* in their hook. The difference: the winners
> **closed the loop with a conviction pivot**, while the losers opened the loop and
> then **deflated it with caveats** ("one honest caveat: today's volume came in
> light…", "two honest caveats…"). A deflated pivot betrays the promise the hook
> made, and the scroll dies. HOFT had one of the *best* hooks of the four and still
> flopped — because the body retracted it.

Every caption **and** every reel VO is written on the **Hot Take Arc**:

```
HOOK   → Contradict what they expect + open a loop + a clock (no hedging, < 12 words spoken)
BUILD  → Steel-man the obvious read (earn trust)         (1–3 lines)
PIVOT  → Reveal the mechanism that makes it real         (concrete numbers — volume, beats)
CLOSE  → Resolve the loop: the trade, stated with conviction
CTA    → Direct address — speak to the viewer's situation
```

**The one hard rule: NO HEDGING IN THE PIVOT OR CLOSE.** The PIVOT must resolve
*toward conviction* — "this is real, and here's the mechanism" (volume confirms,
earnings back it). Never argue against your own thesis in the persuasive spine.

**Urgency is built into the HOOK — non-negotiable.** A coiled NIS Momentum name is a
*perishable* setup: it breaks (or fails) within a short window — days, not months — so
the hook must carry a **clock**. The viewer has to feel that the move is imminent and
that watching later means watching from the sidelines. This is *why we gate out
extended and deep-below-pivot names in Step 1* — only a setup that's genuinely about to
move can carry an honest time-pressing hook. Make the urgency real, not manufactured:
the stock is **coiled at the pivot right now**, so the breakout is the next thing that
happens, not someday. Lead with that compression and that countdown — "still basing,
but not for long", "one volume day from the breakout", "the watchlists haven't caught
this yet — they will by [next catalyst]". Never invent a deadline the data doesn't
support; the truth (coiled at the pivot, volume building) *is* the urgency.

- Risk and what-invalidates-it have exactly **one home**: the invalidation slide
  (Slide 7) and one closing line. Never let "but it's not confirmed", "honest caveat",
  "size smaller because…" leak into the hook, pivot, or close.
- If the data *forces* a hedge into the pivot (volume below average, far below pivot,
  negative earnings), **the ticker failed the Step 1 conviction-pivot gate — go back
  and pick another name.** The arc structurally cannot close on a weak setup; that is
  the real reason RLJ and HOFT lost, not just their charts.

This arc drives Step 4 (carousel + caption) and Step 7A (reel script) identically.

---

## Step 4 — Write the carousel

Call `get_carousel_style_guide()` (the carousel MCP) first and follow its voice +
cover-hook rules. Output **6–8 slides** plus a caption, laid out on the **Hot Take
Arc** from Step 3.5. Adapt the count, but this is the spine:

```
SLIDE 1 — Cover / HOOK            [arc: HOOK]
  Contradict what they expect + open a loop + put a clock on it. A specific,
  stakes-driven line, not a label. Lead with the single most surprising number or an
  expectation-flip, and make the breakout feel *imminent* — the setup is coiled at the
  pivot now and resolves in days, not months. The reader should feel they're early but
  about to be late.
  e.g. "NVDA just cleared its pivot on 1.4x volume — and most watchlists missed it."
  e.g. "This base is days from breaking. RS 96, coiled at the pivot — and nobody's watching yet."

SLIDE 2 — The setup (why it screened)   [arc: BUILD]
  Steel-man the obvious read, then the NIS Momentum tell: RS rank, stacked MAs,
  near highs, beats.
  e.g. "RS rank 96. Stacked above the 50/150/200. Three straight earnings beats."

SLIDE 3 — The chart (price + volume)  ← chart.png lives here   [arc: PIVOT]
  Narrate the mechanism: the base, the pivot, the volume signature.
  Point at the amber volume bars and the accumulation read.

SLIDE 4 — Volume & price detail    [arc: PIVOT]
  The conviction tell. vol_ratio_today, up_down_vol_ratio, adr_pct — in plain words.
  This must resolve *toward* conviction (it does, because Step 1 gated out weak volume).

SLIDE 5 — Fundamentals that matter
  2–3 numbers only. Rising EPS, the beats, the sector it's leading. Positive only —
  if the numbers aren't clean, the ticker should not have passed the Step 1 gate.

SLIDE 6 — The trade               [arc: CLOSE]
  Entry / stop / target / R:R from trade_setup, stated with conviction. Add the
  position-size reminder. (Status is "watch" vs "actionable" — but frame it as the
  plan, not a hedge.)

SLIDE 7 — The risk / what invalidates it   ← the ONLY place caveats live
  "Loses the 50-day on volume, the setup's done." One clean rule. Keep every hedge
  here; never let it bleed into the hook, pivot, or close.

LAST — CTA                        [arc: CTA — direct address]
  Speak to the viewer's situation, then drive to newsimpactscreener.com. Not "follow
  for more". e.g. "If you're still waiting for a setup to look 'obvious', you already
  missed this one. The screener flags them here → newsimpactscreener.com".
```

Then a **caption** written on the same arc (see the style guide's Caption section):

- **HOOK** — first 125 chars. Self-contained, scroll-stopping, no hedging. This is the
  feed preview before "more".
- **BUILD → PIVOT → CLOSE** — 4–6 short paragraphs that ADD context beyond the slides.
  The pivot paragraph delivers the mechanism (volume + earnings confirm); the close
  states the trade with conviction.
- **One** caveat/invalidation line — and only one. If you find yourself writing "one
  honest caveat" or "two honest caveats", stop: the ticker failed the conviction gate.
- **CTA** — direct-address "you" line, then `newsimpactscreener.com` + disclaimer.
- 8–14 hashtags mixing broad (#swingtrading #stocks), niche (#$NVDA, the sector), and
  method (#relativestrength #breakout). No emojis.

---

## Step 5 — Render the carousel graphics

Two render paths — pick by what the user wants:

**A) Premium editorial deck (default for a polished post).** Use
`scripts/build_breakdown_slides.mjs`. It hand-authors 8 SVG slides (dark midnight,
ONE amber accent, green/red reserved for price/volume semantics, Outfit type, no
emoji, asymmetric/editorial per the `taste-skill`), embeds the real chart, and writes
them to `<dir>/slides/`. Slides: cover → setup (Minervini gate checklist) →
chart → volume detail → fundamentals (earnings-beat bars) → trade (price ladder) →
invalidation → CTA.

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_setup_chart.py \
    --ticker ENVA --bare --height 880 --chart-name chart_bare.png
node ../../.claude/skills/nis-stock-breakdown/scripts/build_breakdown_slides.mjs \
    output/setups/ENVA
cd output/setups/ENVA/slides && for f in slide-*.svg; do rsvg-convert -w 1080 -h 1350 "$f" -o "${f%.svg}.png"; done
```

**B) Handwritten "napkin" deck (fast, voice-matched).** Call the carousel MCP
`get_carousel_style_guide()` then `render_carousel(slides, topic, handle, caption,
out_dir)`. Ship `chart.png` as its own image in the sequence.

---

## Step 6 — Render the breakout-validation animation

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/animate_breakout.py --ticker ENVA
```

`--mode combo` (default) renders ONE MP4: hook → real breakout (validated on volume)
→ fake-out anti-pattern → CTA outro. Use `--mode validated` or `--mode fake` for
single-scenario clips.

**The opening hook is ticker-specific.** `standout()` scans the data for the single
weird, probably-overlooked tell — an outsized earnings surprise that *held*, an
extreme up/down-volume ratio, volume drying up at new highs, a long beat streak, a
top RS rank — and frames it as something the viewer missed ("WHAT EVERYONE MISSED",
"HIDING IN THE TAPE"). The **visual** hook is built on that same fact (a
beat-vs-estimate bar gap, up-vs-down volume bars, a streak row, an RS-rank scale, …)
via `draw_hook_viz()`. So no two tickers open the same way. It only claims what the
data supports (e.g. negative EPS growth / negative P/E are never shown as an edge).

---

## Step 7 — Assemble the high-value reel

This is the highest-leverage step. A reel lives or dies in the first 3 seconds —
not in the production quality, but in the *hook*. The narration architecture below
is non-negotiable: write it before passing anything to ElevenLabs.

### 7A — Write the reel script using the Hook-Value-Trade arc

The reel has three zones, and the VO across them follows the **Hot Take Arc** from
Step 3.5 — HOOK (Zone 1) → BUILD+PIVOT (Zone 2 + chart/volume scenes) → CLOSE (trade
scene) → CTA (outro):

```
ZONE 1: HOOK          (0–3s)   Stop the scroll. One verbal + one visual statement.
ZONE 2: VALUE DUMP    (3–25s)  Give the whole trade upfront. No withholding.
ZONE 3: PROOF LAYER   (25–70s) Earn the value you already gave. Chart → volume → setup → breakout.
```

This structure is the opposite of most trading content, which builds to a reveal.
**NIS reels lead with the reveal, then explain it.** The viewer gets the trade in the
first 25 seconds. That's the retention mechanic.

**The no-hedge rule applies to the VO exactly as it does to the caption.** The hook
opens a loop; the pivot (chart + volume scenes) and close (trade scene) must resolve
it *toward conviction*. The ONLY place a caveat is spoken is Scene G (invalidation)
and the disclaimer — never in the hook, the walkthrough, or the trade close. If the
data forces "but it's not confirmed" earlier than Scene G, the ticker failed the
Step 1 gate; pick another. (Past losers RLJ/HOFT voiced their caveats mid-pitch and
the retention collapsed.)

---

#### ZONE 1: HOOK (0–3 seconds)

Write TWO parallel hooks — one verbal (what Hans says), one visual (what appears on screen).
They must reinforce each other but not duplicate each other.

**Verbal hook — use one of these types (ranked by *measured* effectiveness for this
audience).** The proven 🥇 winners did two things: they named what the viewer was
*missing right now* and they made the move feel *imminent*. ENVA's 345-view reel ran
Direct address + FOMO with a built-in clock ("one breakout away from a run — most
watchlists don't have it yet"); NWPX's 219-view reel ran a Specific number drop ("beat
by 59% — and held the move"). The strongest hooks **fuse imminence with FOMO** — a
specific number *and* a countdown ("RS 96, coiled at the pivot, days from breaking").
The bottom-tier hooks below are what the *losers* leaned on — prefer the top of this
list, pair it with a clean expectation-flip, and always put a clock on it:

| Type | Tier | Pattern | Example |
|---|---|---|---|
| Imminence / countdown | 🥇 proven | Put a clock on the setup — it breaks in days, not months | "This base is days from breaking — and the watchlists haven't caught it yet." |
| Direct address + FOMO | 🥇 proven | Name what they're missing RIGHT NOW | "If ENVA isn't on your watchlist, you're about to watch it from the sidelines." |
| Specific number drop | 🥇 proven | Lead with the most surprising number from setup.json | "Beat earnings by 59% last quarter — and held every point of it." |
| Stakes contradiction | 🥈 strong | "[What traders expect]. [What the chart shows instead]." | "Most traders are watching the wrong level on ENVA. Here's the one that matters." |
| Confession-flip | 🥈 strong | A belief the audience holds → what the data shows instead | "You probably think this kind of setup is rare. It screened clean on all 7 criteria." |
| Hard question | 🥉 ok | A question they're already asking themselves | "Is this a real breakout or a fake? Here's how to tell before it happens." |
| Abstract technical stat | ⚠️ weak | An isolated indicator value with no stakes | "2.9-to-1 up/down volume." (RLJ — flopped; it's a real NIS accumulation tell, but too abstract to *open* on — use it in the walkthrough, don't lead with it) |
| Turnaround / loss-to-profit | ⚠️ weak | "They were losing money, now they're not" | "Wall Street modeled a loss — it posted a profit." (HOFT — flopped; abstract + invites doubt) |

**Avoid the ⚠️ tier.** They correlate with the lowest-view reels: an abstract stat
gives a scroller nothing to feel, and a turnaround hook quietly admits the company was
broken, which invites skepticism instead of FOMO. If the only honest hook for a ticker
is a ⚠️ one, that's a signal the ticker failed the Step 1 conviction gate.

**Rules for the verbal hook:**
- Under 15 words
- No hedging: not "might", "could", "potentially"
- Contains either a specific number OR a named consequence
- **Carries a clock — the breakout is imminent.** The hook must make the viewer feel
  the setup resolves in *days, not months*: coiled at the pivot, one volume day from
  breaking, watchlists about to catch it. "Days from breaking", "before it moves", "by
  next week", "you're early — but not for long". The urgency must be true (the name was
  gated in Step 1 precisely because it's about to move); never fabricate a deadline.
- Written for spoken delivery — rhythm beats grammar
- Hans's voice: calm authority, not hype. He states facts like they're obvious.

**Visual hook — what appears on screen in the first 3 seconds:**

Do NOT open on the chart. The chart is mid-reel material. Open on ONE of:

| Visual hook type | What to show | Why it works |
|---|---|---|
| **Number card** | Single large number from setup.json (e.g. `RS 94` or `+127% EPS`) on a dark background | Stops scroll; number demands context |
| **The moment** | A tight crop of the pivot candle with volume bar highlighted in amber — NO axes, NO labels | Ambiguity creates curiosity before the explanation |
| **The trade card** | Entry / Stop / Target / R:R on a single card — full trade visible in 3 seconds | Front-loads the value; viewer knows what they're getting |
| **Split screen** | Real breakout candle left / fake-out candle right, no caption | Creates instant question: "which one is this?" |

The visual hook plays for 2–3 seconds before the value card appears.
The verbal hook plays simultaneously — it is NOT a description of the visual.

Generate **3 ranked verbal hook options** with hook type labeled. The agent picks the
best fit for the specific ticker's strongest signal.

---

#### ZONE 2: RAPID WALKTHROUGH (3–20 seconds)

Don't hold one dense card. **Walk the setup as a burst of one-fact cards that hard-cut
every ~1.5 seconds** — a single big number/label per card, a terse VO line per card.
This is still leading with value (the trade levels are in the burst); it's just paced
for retention. `build_reel.py::walkthrough()` builds these from `setup.json`; each is
its own scene. Typical order (cards drop when the data isn't there):

```
[TICKER] · WATCH        "Northwest Pipe — a watch."
50·150·200 · stacked    "Trend: stacked and rising."
52-WK · pressing high   "Pressing its highs."
RS [rank]               "Relative strength rank [rank]."        (only if known)
[N]× · earnings beats   "[N] straight earnings beats."
+[g]% · EPS growth      "Earnings up [g] percent."
[udr]× · up/down vol    "Volume says accumulation."
$[entry] · ENTRY        "Entry, a break through [entry]."
$[stop] · STOP [risk]%  "Stop, [stop]."
$[target] · TARGET 2:1  "Target, [target]. Two to one."
```

Each card is a clean stat card (big value + short label), one idea, no clutter. The
viewer gets the whole trade in the first ~15 seconds — as a rhythm, not a wall.

---

#### ZONE 3: PROOF LAYER (25–70 seconds)

Each scene has a narration line written FIRST, then the visual is chosen to match.
One line per scene. Hard cuts between scenes.

Scene order and narration guide:

**Scene A — Setup** (~5s)
Visual: Setup checklist graphic (Minervini gates, each line checking green)
VO: "Seven criteria. [TICKER] passed all of them. RS [rank], stacked MAs, [N] straight beats."
*If RS rank unknown: "RS rank from the latest screen — in the top decile of the universe."*

**Scene B — The chart** (~8s)
Visual: `chart_bare.png` — full candlestick chart with SMA lines and buy range band.
Apply a slow Ken-Burns push into the pivot area. Highlight the base with an amber
overlay during narration.
VO: "[N] weeks basing. [N] tight closes. Pivot at [pivot]. That coil is compressed energy."

**Scene C — Volume** (~7s)
Visual: Zoom into the volume bars section of the chart. Flash amber on bars where
volume ≥ 1.4× the 50-day avg.
VO: "[vol_ratio_today]x volume on the up days. [up_down_vol_ratio] up/down ratio.
Institutions are loading, not dumping."

**Scene D — Fundamentals** (~5s)
Visual: Earnings-beat bar chart from the slide deck (slide 5).
VO: "[N] straight earnings beats. EPS up [growth]% year-over-year. The business
is accelerating — the price just confirmed it."

**Scene E — The trade (exact levels)** (~8s)
Visual: Price ladder graphic — entry, stop, and target as horizontal lines on a
simplified chart. Animate the price moving from entry to target.
VO: "Buy on a confirmed close above [pivot] on volume. Stop below [stop].
Target [target_2r]. That's [R:R] on your risk. Size accordingly."

**Scene F — Breakout animation** (~20s, from animate_breakout.py)
Visual: The full real-vs-fake breakout animation rendered in Step 6.
VO during real breakout: "This is what a validated breakout looks like. Close above
the pivot. Volume confirms. The setup is live."
VO during fake-out: "This is the fake. Same pivot, light volume, closes back under.
That's your cue to stay out — or exit."

**Scene G — Invalidation** (~5s)
Visual: Simple text card on dark bg: "Setup fails if: [trigger 1] / [trigger 2]"
VO: "One rule: if it loses the [SMA50] on volume, the setup is done. No questions.
Exit the trade."

**Scene H — Disclaimer + CTA** (~5s)
Visual: Static dark card. Text: "Not financial advice. For education only."
Below: "newsimpactscreener.com"
VO: "Not financial advice. If you want the full screener that found this —
newsimpactscreener.com. Link in bio."

---

#### 7B — Hook selection checklist

Before finalising the verbal hook, check:
- [ ] Under 15 words?
- [ ] Contains a specific number OR a named consequence?
- [ ] **Carries a clock — does it make the breakout feel imminent (days, not months)?**
      If the hook would read the same whether the move were tomorrow or next quarter,
      it has no urgency — add the countdown.
- [ ] No hedging language?
- [ ] Does it work as a spoken line — not just as text?
- [ ] Would someone who's mid-scroll stop at this line?
- [ ] Is it true to what `setup.json` actually shows?
- [ ] Is it a 🥇/🥈 hook type (FOMO, number-drop, contradiction) — **not** an abstract
      stat or a turnaround? If it's ⚠️-tier, the ticker probably failed the Step 1 gate.
- [ ] Does the loop it opens get **closed with conviction** later — with no "honest
      caveat" between the hook and the trade? (Caveats live only in Scene G.)

If any box is unchecked, revise before passing to ElevenLabs.

---

#### 7C — ElevenLabs render

**Default: the evolving-chart reel (`build_chart_reel.py`).** This is the
stacked-curiosity format — ONE full-frame **1080×1920** price chart that *animates as it
expands* across the entire reel: candles draw in one-per-data-point with **both axes
growing** (newest candle pinned to the right, earlier ones compressing left; the y-range
expanding as new highs/lows arrive), exactly like the viral_reels `PriceChart`. It grows
through the real display window, then projects the validated breakout to the 2R target.
The Hot-Take-Arc copy rides on top as **floating semi-transparent cards that cut in/out**.
Two things are always moving — the chart growing *and* the cards changing — so the eye
never rests (the retention trick the multi-element meme reels use, except the "background
motion" is the actual trade developing). There is **no play-head line** — the live price
tag on the leading candle is the moving edge.

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_chart_reel.py \
    --ticker ENVA \
    --hook-text "[chosen verbal hook]"
# → output/setups/ENVA/reel_chart.mp4   (1080×1920)
```

`build_chart_reel.py` conventions:
- **1080×1920** full vertical (Reels / TikTok / Shorts). Cards float in the top band so
  the chart stays readable below and behind them.
- Uses `$ELEVENLABS_PRIMARY_VOICE_ID` (Hans). Override with `--voice-id`. `--tempo 1.08`.
- ONE chart for the whole reel: real display window (`--display-days`, default 126 ≈ half a year) +
  appended **validated** breakout projection (reuses `animate_breakout.project()`), so
  the on-chart Entry/Stop/Target and the spoken levels come from a single live snapshot
  and can't drift apart. (Climax is the *validated* breakout only — no fake-out here.)
- Growth timing is data-driven: the hook + rapid one-fact walkthrough grow the chart
  through the real candles; the **climax scene draws in the projection** (price clears the
  pivot on volume, runs to target); the invalidation + CTA cards hold the finished chart.
- Real vs. future is made unmistakable: during the real phase the chart is just solid
  candles + SMAs (no entry/stop/target — those aren't history). The moment the projection
  begins, a blue **NOW** divider drops, the future region tints blue with a vertical
  **PROJECTED** label, the projected candles + volume render **hollow + dashed**, and the
  entry/stop/target/buy-band appear **only across the future region** (the plan, not the
  tape). SMAs never extend past NOW.
- As the projection starts, the camera **snap-zooms in** (eased push to the last
  ~`ZOOM_BARS` real bars + the future, tightening both axes) over ~`ZOOM_SECS` (≈1s) — fast,
  not a slow crawl — then holds while the breakout candles draw in. The real phase stays
  full-frame.
- All cards (hook / one-fact stat cards / breakout / invalidation / CTA) are generated
  from `setup.json` + the live load — no per-ticker hand-editing. Each card fades in,
  holds for its VO line, then hard-cuts.
- The visual hook is the hook *card* over the quietly-building chart — you are NOT
  opening on a full static chart (it starts mostly hidden and draws in), so the
  "don't open on the chart" rule from Zone 1 still holds in spirit.
- Requires only `setup.json` + FMP/ElevenLabs creds. Does **not** need `breakout_story.mp4`
  or the slide deck (it draws its own chart), so Step 6 is optional for this path.

Target length: 40–70 seconds (it runs shorter than the legacy reel because the proof
lives in the one continuous chart, not in separate scenes).

**Legacy: the stacked-card reel (`build_reel.py`).** The earlier format — a sequence of
full-frame 1080×1350 scenes (hook visual → rapid stat cards → breakout animation →
proof tail). Use it when you specifically want the standalone real-vs-fake breakout
animation as the climax, or a 4:5 feed crop.

```bash
.venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_reel.py \
    --ticker ENVA --hook-text "[hook]" --hook-visual [number_card|moment_crop|trade_card|split_screen]
# → output/setups/ENVA/reel.mp4   (1080×1350); needs chart_bare.png + breakout_story.mp4 from Steps 5–6
```

---

## Step 8 — Write the post caption

Every reel ships with a caption. Save as `output/setups/<TICKER>/caption.txt`.

**Caption rules:**
- **First 125 chars = the verbal hook from Zone 1.** It must be self-contained and
  scroll-stopping as text alone — this is what appears in the feed before "more".
- Body (3–5 short paragraphs): the setup in plain words → the trade (entry / stop /
  target, R:R) → the real-vs-fake breakout warning → watch/swipe prompt.
- Exact numbers are fine in the caption.
- Close with `newsimpactscreener.com` and a disclaimer line.
- Hashtags on the last line: 8–14. Mix broad (#swingtrading #stocks), the ticker
  (#ENVA), and method (#breakout #relativestrength #momentum). No emojis.
- Anchor every claim in `setup.json`. Never invent a level, a beat, or an RS rank.

---

## Step 9 — Publish to Sanity as a blog post (optional)

Only do this when asked. Always write both `body` and `cavemanBody` (project rule).

- **Type:** `post`. Fields: `title`, `slug`, `author` (ref), `mainImage`,
  `categories`, `publishedAt`, `body`, `cavemanBody`.
- **Field map:** cover hook → title + intro; each slide → `h2` + paragraph; chart →
  `mainImage` + inline in chart section; trade → its own section with levels; caption
  → closing CTA.
- Default to draft for human review. Use Sanity MCP for the document. Images upload
  via assets API with `SANITY_TOKEN`. Confirm dataset/attribution before writing.

---

## Output format for the script (Step 7A)

Deliver the reel script in this shape before rendering:

```
# 🎬 Reel Script: [TICKER] — [one-line read]

**Status:** [actionable / watch / extended]
**Hook type:** [chosen type]
**Visual hook:** [number_card / moment_crop / trade_card / split_screen]

---

### HOOK VARIANTS (ranked)

🥇 [Verbal hook text]
Type: [type] — [why it works for this ticker specifically]

🥈 [Verbal hook text]
Type: [type] — [why it works]

🥉 [Verbal hook text]
Type: [type] — [why it works]

**Selected hook:** 🥇 (or justify if choosing lower)

---

### ZONE 1: VISUAL HOOK
[Describe exactly what appears on screen for 2–3s]

### ZONE 1: VERBAL HOOK (VO)
[Full narration line — the selected hook]

### ZONE 2: VALUE CARD (VO)
[Full narration line]

### ZONE 3: SCENE-BY-SCENE

**A — Setup** [~5s]
VO: [line]
Visual: [what's on screen]

**B — Chart** [~8s]
VO: [line]
Visual: [what's on screen]

**C — Volume** [~7s]
VO: [line]
Visual: [what's on screen]

**D — Fundamentals** [~5s]
VO: [line]
Visual: [what's on screen]

**E — Trade levels** [~8s]
VO: [line]
Visual: [what's on screen]

**F — Breakout animation** [~20s]
VO (real): [line]
VO (fake): [line]

**G — Invalidation** [~5s]
VO: [line]
Visual: [card text]

**H — CTA** [~5s]
VO: [line]
Visual: [card text]

---

**Estimated total:** [Ns]
```

---

## What makes a reel good vs. generic

**Hook:**
- Specific number or named consequence in the first sentence
- Visual hook does not match the verbal hook (they reinforce, not duplicate)
- Opens a loop the viewer must close by watching

**Value delivery:**
- The full trade is on screen within 25 seconds
- Viewer gets something real whether they watch 5 seconds or 90 seconds

**Proof layer:**
- Each scene has ONE idea
- Numbers, not adjectives ("1.6x up/down volume" not "strong accumulation")
- The breakout animation earns its 20 seconds — it shows both outcomes, not just the win

**Narration:**
- Hans speaks like he already knows you know the basics — no explaining what a pivot is
- Short lines, hard cuts, no "and then", no "so basically"
- The disclaimer is not an apology — it's stated flatly and the CTA follows immediately

**What to never do:**
- Build to a reveal that the audience has to wait for (front-load instead)
- State the trade only in the caption and not the reel
- Open on the full chart (save it for Scene B)
- Use "potentially", "might", or "could be" in Hans's narration
- Invent an RS rank, price target, or fundamental you don't have in setup.json to create better content
