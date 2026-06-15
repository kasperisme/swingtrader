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

- **A ticker is given** ("break down NVDA"): use it directly.
- **No ticker / "what's on the NIS Momentum board"**: run the screening and pick a
  name. The screen lives at
  `code/analytics/services/market_screenings/scripts/nis_momentum.py`; run it via
  the market-screenings runner/CLI, or pull the latest stored results the
  `/screenings` UI reads. Each row carries `symbol`, `RS_Rank`, `sector`,
  `within_buy_range`, `extended`, `accumulation`, `PASSED_FUNDAMENTALS`. Prefer a
  name that's **in or near its buy range** with **accumulation** — it makes the most
  actionable post. Note its real `RS_Rank` to pass along in Step 2.

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

**RS caveat:** RS rank is universe-relative and can't be computed for one ticker. If
you don't pass `--rs-rank` from the screening run, `setup.json` marks it unknown —
don't state a rank you don't have.

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

## Step 4 — Write the carousel

Call `get_carousel_style_guide()` (the carousel MCP) first and follow its voice +
cover-hook rules. Output **6–8 slides** plus a caption. Adapt the count, but this is
the spine:

```
SLIDE 1 — Cover / hook
  A specific, stakes-driven line. Not a label.
  e.g. "NVDA just cleared its pivot on 1.4x volume. Here's the trade."

SLIDE 2 — The setup (why it screened)
  One line on the NIS Momentum read: RS rank, stacked MAs, near highs, beats.
  e.g. "RS rank 7. Stacked above the 50/150/200. Three straight earnings beats."

SLIDE 3 — The chart (price + volume)  ← chart.png lives here
  Narrate what the chart shows: the base, the pivot, the volume signature.
  Point at the amber volume bars and the accumulation read.

SLIDE 4 — Volume & price detail
  The conviction tell. vol_ratio_today, up_down_vol_ratio, adr_pct — in plain words.

SLIDE 5 — Fundamentals that matter
  2–3 numbers only. Rising EPS, the beats, the sector it's leading.

SLIDE 6 — The trade
  Entry / stop / target / R:R from trade_setup. State the status honestly
  (actionable now vs. watch vs. don't-chase). Add the position-size reminder.

(Optional SLIDE 7 — the risk / what invalidates it: "loses the 50-day, setup's done".)

LAST — CTA
  Drive to newsimpactscreener.com. Concrete next step, not "follow for more".
```

Then a **caption** (see the style guide's Caption section): first 125 chars hook,
4–7 short paragraphs that ADD context beyond the slides, a swipe prompt, the CTA,
and 8–14 hashtags mixing broad (#swingtrading #stocks), niche (#$NVDA, the sector),
and method (#relativestrength #breakout). No emojis.

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

The reel has three zones:

```
ZONE 1: HOOK          (0–3s)   Stop the scroll. One verbal + one visual statement.
ZONE 2: VALUE DUMP    (3–25s)  Give the whole trade upfront. No withholding.
ZONE 3: PROOF LAYER   (25–70s) Earn the value you already gave. Chart → volume → setup → breakout.
```

This structure is the opposite of most trading content, which builds to a reveal.
**NIS reels lead with the reveal, then explain it.** The viewer gets the trade in the
first 25 seconds. That's the retention mechanic.

---

#### ZONE 1: HOOK (0–3 seconds)

Write TWO parallel hooks — one verbal (what Hans says), one visual (what appears on screen).
They must reinforce each other but not duplicate each other.

**Verbal hook — use one of these types (ranked by effectiveness for this audience):**

| Type | Pattern | Example |
|---|---|---|
| Stakes contradiction | "[What traders expect]. [What the chart shows instead]." | "Most traders are watching the wrong level on ENVA. Here's the one that matters." |
| Specific number drop | Lead with the most surprising number from setup.json | "1.6x up/down volume. This stock has been under accumulation for 11 weeks." |
| Direct address + FOMO | Name what they're missing RIGHT NOW | "If ENVA isn't on your watchlist, you're about to watch it from the sidelines." |
| Confession-flip | A belief the audience holds → what the data shows instead | "You probably think this kind of setup is rare. It screened clean on all 7 criteria." |
| Hard question | A question they're already asking themselves | "Is this a real breakout or a fake? Here's how to tell before it happens." |

**Rules for the verbal hook:**
- Under 15 words
- No hedging: not "might", "could", "potentially"
- Contains either a specific number OR a named consequence
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
- [ ] No hedging language?
- [ ] Does it work as a spoken line — not just as text?
- [ ] Would someone who's mid-scroll stop at this line?
- [ ] Is it true to what `setup.json` actually shows?

If any box is unchecked, revise before passing to ElevenLabs.

---

#### 7C — ElevenLabs render

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_reel.py \
    --ticker ENVA \
    --hook-text "[chosen verbal hook]" \
    --hook-visual [number_card|moment_crop|trade_card|split_screen]
# → output/setups/ENVA/reel.mp4
```

`build_reel.py` conventions:
- Uses `$ELEVENLABS_PRIMARY_VOICE_ID` (Hans). Override with `--voice-id`.
- `--tempo 1.08` for snappier delivery.
- Scene flow: ZONE 1 hook visual → **ZONE 2 rapid one-fact stat cards (≈1.5s cuts)** →
  ZONE 3 proof tail (chart → breakout animation → invalidation → disclaimer). The
  setup / volume / fundamentals facts live in the Zone-2 burst, so the tail stays short.
- Stat cards + value/hook/disclaimer cards are generated by the script from
  `setup.json` (fundamentals included) — no per-ticker hand-editing.
- Each scene holds for its narration line then hard-cuts to the next.
- Breakout animation plays in full — never trimmed.
- Disclaimer card always closes.
- Requires `slides/…` (for the carousel) + `chart_bare.png` and `breakout_story.mp4`
  from Steps 5–6.

Target length: 70–90 seconds. If running long, trim Scene D (fundamentals) first —
the trade, chart, and breakout are the core. Fundamentals are supporting cast.

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
