---
name: nis-ad-image
description: >-
  Render ONE single-image ad (Meta + TikTok) from a Claude-authored spec — the clean,
  easy-to-debug replacement for the carousel. eToro pattern: brand mark → bold headline
  with one accent → subhead → green-check benefits → optional proof stat → CTA button,
  over a branded hero (generated financial motif or a real photo). Outputs 4:5, 9:16 and
  1:1 plus ad_copy.txt. Pairs with nis-trend-radar (topic → lead-magnet deep-link) and
  nis-ad-launch (creates the single-image PAUSED draft). Use when the user wants an "ad",
  "single image ad", "Meta/TikTok ad", or to advertise the product / a weekly trend. NOT a
  swipe carousel and NOT an organic post (that's social_publishing).
---

# NIS Ad Image

**One image, one message.** A single static ad — no slides, no swipe — so it's fast to
author, trivial to debug, and reads in a single glance in the feed. Modeled on the eToro
pattern: a bold headline with a single accent, a couple of green-check benefits, an optional
proof stat, and a CTA button over a branded hero. The renderer does layout only; **every
number must be real** (from a `nis-trend-radar` brief or a `setup.json`).

## The anatomy (top → bottom, left-aligned)

```
[◍ brand]  newsimpactscreener.com          ← mark + wordmark
KICKER                                       ← small mono accent (optional)
Big bold headline with ONE accent phrase     ← the hook (accent = the number/idea that stops the scroll)
one-line subhead                             ← the stakes / the specifics
✓ benefit line                               ← what they get (green check)
✓ benefit line
┌ $TICKER  +NN% ────────────┐                ← optional proof stat (ticker vs S&P), REAL numbers
└───────────────────────────┘
[ CTA button ]                               ← the action
newsimpactscreener.com · disclaimer          ← footer
```

## Where content is saved (the convention)

All ad content lives under a dated campaign folder, one subfolder per lead magnet:

```
output/ads/<date>-<short-name>/<lead-magnet>/     ← <lead-magnet> ∈ { briefing, market-screening }
    ad.json
    ad_copy.txt
    4x5/ad.png   9x16/ad.png   1x1/ad.png          ← the formats
```

e.g. `output/ads/2026-07-14-geopolitics/briefing/` and
`output/ads/2026-07-14-geopolitics/market-screening/`. The `<date>` is the run date
(`YYYY-MM-DD`); `<short-name>` is the trend/topic or feature slug. `nis-ad-launch` treats
the `<date>-<short-name>` folder as one campaign and each lead-magnet subfolder as an ad set.

## Step 0 — Learn from past performance (close the loop)

Before authoring, pull what previous ads taught us and let it bias this ad's design:

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli design --leaderboard --min-impr 500   # human read
.venv/bin/python -m services.meta_ads.cli design --json --min-impr 500          # machine-readable
```

This joins each past ad's Meta performance to its `design` genome (via `ad_id` in
`launch_manifest.json`) and ranks every lever best-first on the **normalized rates** — so you
can see which `hook_type` / `accent` / `has_proof` / `theme` / `bullet_count` actually won.
**Bias the new spec toward the winners**, but:

- **Compare on rates, not totals.** CTR, CPM, CVR, CPL are already per-impression / per-spend,
  so an ad that ran longer or on a bigger budget is directly comparable — **don't divide by
  days-active or budget again** (double-normalizing). Raw clicks/leads totals are not comparable.
- **Respect sample size.** Rows flagged `⚠low-n` (or below `--min-impr`) are noise — don't chase
  them. Early on there won't be a verdict; that's fine.
- **Mind the confounds (shown, not divided out).** `⚠fatigue` = high frequency deflating CTR (a
  long-run artefact, not a weak creative); a big `CPM` gap = budget/audience differences. Prefer
  comparing ads that ran concurrently at equal budget — which the isolated-budget A/B already does.
- **Vary ONE lever at a time.** Hold the proven levers, change a single new hypothesis, bump
  `design.variant` — so the next run can attribute the lift. (Explore vs. exploit: lean on
  winners, keep one deliberate experiment.)
- If there's no history yet, skip this and author from first principles (Step 1).

## Step 1 — Author the spec (you, Claude)

Write `output/ads/<date>-<short-name>/<lead-magnet>/ad.json` (the renderer writes the
formats next to the spec). For example `output/ads/2026-07-14-geopolitics/briefing/ad.json`:

```json
{
  "slug": "2026-07-14-geopolitics/briefing",
  "theme": "dark",                 // dark (default, high-punch) | light (site theme)
  "accent": "amber",               // amber (default) | pos (green)
  "brand": "newsimpactscreener.com",
  "mark": "NIS",
  "category": "Thematic",           // eyebrow tag — from the screening's category (Thematic|Insider|IPO|…)
  "cadence": "Updated weekdays",     // eyebrow cadence — derived from the screening's schedule (see below)
  "kicker": null,                    // optional override; when null the eyebrow = "CATEGORY · CADENCE"
  "headline": "Iran moved the whole market. Did your inbox?",
  "headline_accent": "the whole market",   // the exact words to paint in the accent colour
  "subhead": "261 stories in 7 days — oil, COIN and energy all reacting.",
  "bullets": ["A daily brief on #geopolitics + XOM, COIN, AAPL",
              "In your inbox before the open — free"],
  "proof": {"ticker": "COIN", "ret": 30, "spy": 4},   // optional — REAL returns only
  "impact_list": {                    // optional — a ranked "impact board" (the curiosity-gap vehicle)
    "title": "Reacting to the Iran news",   // small label above the rows
    "reveal": "partial",              // full (proof) | partial (opens a gap — hides the tail)
    "shown": 3,                       // partial only: rows shown before the "+N more · see them free →" tease (default 3)
    "more_label": "see them free →",  // optional — the tease microcopy (default; never "unlock", it's free)
    "items": [                        // REAL, dated moves only — never invent
      {"ticker": "FRO", "move": "+21%", "dir": "up"},
      {"ticker": "XOM", "move": "+12%", "dir": "up"},
      {"ticker": "CVX", "move": "+8%",  "dir": "up"},
      {"ticker": "LMT", "move": "+5%",  "dir": "up"},
      {"ticker": "CCJ", "move": "+9%",  "dir": "up"},
      {"ticker": "XLE", "move": "+7%",  "dir": "up"}
    ]
  },
  "cta_label": "Get my briefing",
  "cta_note": "Free · weekdays 7am ET",   // trust/cadence line under the button — from the screening schedule
  "destination": "https://www.newsimpactscreener.com/briefings?tags=geopolitics,oil,iran&tickers=XOM,COIN,AAPL",
  "disclaimer": "Not financial advice. For education only.",
  "background_image": "hero.jpg",  // optional — a real photo in the slug dir (cover-fit + scrim). Omit → generated motif.
  "background": {                   // REEL only — the drifting, topic-linked backdrop (see below)
    "motif": "chart",               // chart | grid | none
    "scene": "tanker",              // optional topic ANIMATION (see the scene table below)
    "rising": true,                 // a "stock price" line that draws itself upward across the screen
    "tickers": ["XOM", "CVX", "XLE", "FRO"],   // the ad's topic tickers → scrolling ticker-tape
    "speed": 1.0
  },
  "ad": {
    "primary_text": "the in-feed caption above the image (pain → the tool → the proof → CTA)",
    "headline": "The news that moved your stocks — before the open",  // shows under the image
    "description": "Free daily briefing. No account.",
    "cta_label": "Sign Up",
    "destination": "https://www.newsimpactscreener.com/briefings?tags=…&tickers=…"
  },
  "design": {                        // creative-genome metadata — for engagement analysis
    "hook_type": "question",         // question|number_drop|contradiction|fomo|confession|how_to|authority
    "angle": "fear_of_missing_news", // the persuasion angle in a word or two (snake_case)
    "primary_emotion": "urgency",    // urgency|fear|greed|curiosity|trust
    "visual_style": "data",          // data|editorial|photo
    "persona": "busy_swing_trader",  // who it targets
    "offer": "free_daily_briefing",  // the promise
    "curiosity_type": "partial_list",// none|partial_list|withheld_tickers|withheld_winner|withheld_mechanism|number_tease|pattern_interrupt
    "curiosity_strength": 2,          // 0 none · 1 implied · 2 explicit gap  (auto-inferred from impact_list if omitted)
    "variant": "v1"                  // label to tell A/B variants of the same concept apart
  }
}
```

- **`headline` + `headline_accent`** carry the ad. Keep the headline < ~9 words; the accent is
  the single number/idea that stops the scroll. One accent only.
- **`proof`** is optional but strong — a real `$TICKER +NN%` vs the S&P. Never invent it; pull
  from a `setup.json` `benchmarks` or a trend brief's `most_affected`.
- **`impact_list`** is the newer, higher-leverage version of `proof`: a ranked board of the
  tickers moving on the story (source it verbatim from the trend brief's `most_affected` /
  `tickers_in_play`). `reveal: "full"` shows every row (a proof play); `reveal: "partial"`
  shows the top `shown` (default 3) and hides the rest behind a **`+N more · see them free →`**
  tease — that withheld tail is the curiosity gap. The tease says *free* (never "unlock"),
  since every screening is a free email/Telegram sub; override with `impact_list.more_label`.
  See the section below.

**Templated legitimacy fields — drive these from the screening row, not hand-copy.** They cost
nothing to fill and add a per-theme trust signal so each ad reads as a real, scheduled product:
- **`category`** — the screening's category tag (`Thematic`/`Insider`/`IPO`/…) → the eyebrow.
- **`cadence`** + **`cta_note`** — derived from the screening's `schedule` (cron) + `timezone`
  via a helper, so the wording is consistent:
  ```python
  from build_ad_image import cadence_from_schedule
  cadence_from_schedule("0 7 * * 1-5", "America/New_York")
  # → {"cadence": "Updated weekdays", "cta_note": "Free · weekdays 7am ET"}
  ```
  Pull `category`, `schedule`, `timezone` off the `market_screenings` row for the destination
  screening: the eyebrow becomes `CATEGORY · CADENCE` and a trust line sits under the CTA —
  closing the "what am I actually signing up for" gap before the click.
- **`ad.*`** feeds `ad_copy.txt` AND the single-image creative (its `headline`→`name`,
  `description`→`description` under the image). `ad.destination` is the real click target.

**Copy voice** — same anti-jargon rules as the reels: plain words, one point of view,
comparisons over terms, no invented figures. First line of `primary_text` is a self-contained
scroll-stopper.

## Step 2 — Render

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-ad-image/scripts/build_ad_image.py \
    --spec output/ads/2026-07-14-geopolitics/briefing/ad.json   # all ratios; add --ratios 4x5 to limit
```

Outputs next to the spec (`output/ads/<date>-<short-name>/<lead-magnet>/`):
- `4x5/ad.png` — 1080×1350 (Meta feed)
- `9x16/ad.png` — 1080×1920 (TikTok / Reels / Stories)
- `1x1/ad.png` — 1080×1080 (square; the one `nis-ad-launch` uploads)
- `ad_copy.txt` — primary text · headline · description · CTA (paste into Ads Manager)
- `design.json` — the resolved creative genome (authored `design` + auto-derived facts)

Review every render before shipping. `theme: dark` is the default for stopping power;
`background_image` swaps the generated chart motif for a real photo (cover-fit + readability
scrim), if you have one that fits.

## Design metadata — what drives engagement

Every render writes **`design.json`**: your authored `design` block merged with the factual
attributes the renderer derives (`theme`, `accent`, `background_type`, `headline_words`,
`bullet_count`, `has_proof`/`proof_type`, `cta_words`, `primary_text_chars`, `formats`) plus
join keys (`slug`, `lead_magnet`, `campaign`, `utm_content`, `utm_campaign`, `rendered_at`).
The derived facts are objective and consistent across every ad, so they aggregate cleanly.

When you launch, `nis-ad-launch` writes **`output/ads/<campaign>/launch_manifest.json`** —
one row per ad joining the Meta **`ad_id`** to that ad's `design`. Later, join `meta_ads
insights` (per-ad CTR/CPC/spend, keyed by `ad_id`) to the manifest to answer *which design
choices drive engagement* — dark vs light, proof vs no proof, `hook_type=question` vs
`number_drop`, 1 bullet vs 3, short vs long primary text.

**Author the `design` block with a controlled vocabulary** (snake_case, reuse values across
ads — free text won't aggregate). The point is to vary *one lever at a time* across variants
(`variant: "v1"`, `"v2"`, …) so the analysis can attribute the lift. Only describe what's
actually in the creative — the derived facts are cross-checked against it.

## Curiosity gaps — the lever to leverage

A curiosity gap = reveal enough to open a question, withhold the answer, make the click the
only way to close it. It reliably lifts **CTR** — but a strong gap with a weak payoff is just
**clickbait**: CTR up, CVR down, spend wasted. So the thing you optimise is **curiosity scored
on CVR / cost-per-lead**, never CTR alone. `meta_ads design` now carries the levers
(`curiosity_type`, `curiosity_strength`, `impact_list_reveal`) and auto-flags **`⚠clickbait`**
(top-quartile CTR + bottom-quartile CVR) so a magnetic-but-hollow gap can't hide.

**Gap mechanisms** (each a distinct, testable `curiosity_type` — same trend, different thing withheld):

| `curiosity_type` | Withholds | Example (Hormuz week) |
|---|---|---|
| `withheld_tickers` | the names | "3 S&P names are quietly ripping on the Iran news. Is one yours?" |
| `partial_list` | the rest of the list | impact_list `reveal:"partial"` — `FRO +21 · XOM +12 · … +2 more →` |
| `withheld_winner` | which is #1 | "The biggest winner of the Hormuz shock isn't an oil stock." |
| `withheld_mechanism` | the *why* | "Why is a shipping stock beating every energy name this week?" |
| `number_tease` | the payoff size | "One name is up 21% since Monday. Most people missed it." |
| `pattern_interrupt` | the expected frame | "Everyone's watching oil. The real move is two sectors over." |

**Pace the gap across the funnel** — this is what stops a strong gap from backfiring. The gap
is a three-beat sequence: **ad opens it → landing page narrows it → email closes it.**
- Reveal *everything* on the landing page → no reason to submit the email → clicks, no leads.
- Reveal *nothing* → they bounce → no leads.
- With `partial_list`: ad shows the top 3 → landing shows those 3 + "unlock the full ranked list"
  → email delivers the rest. Curiosity **and** a reason to convert, message-matched the whole way.

**First built-in A/B — full vs partial impact list.** Author two variants that differ on
*only* the reveal (hold trend, headline, visual, CTA constant):
- `variant: "impact_full"` → `impact_list.reveal: "full"` (proof play; `curiosity_strength` 1)
- `variant: "impact_partial"` → `impact_list.reveal: "partial"`, `shown: 3` (gap; `curiosity_strength` 2)

Launch both, then read the winner on **CVR / $-per-lead** (watch `⚠clickbait`):

```bash
.venv/bin/python -m services.meta_ads.cli design --by impact_list_reveal --min-impr 500
.venv/bin/python -m services.meta_ads.cli design --by curiosity_type     --min-impr 500
```

That result feeds the next ad's genome (Loop A) — bias toward the gap that pulled *leads*, not
just clicks.

## Reel variant (video) — same ad, animated

Meta favours Reels/video, and motion usually lifts CTR. `build_ad_reel.py` renders a
~15s vertical (9:16) reel from the **same `ad.json`** — the **brand stays on screen the
whole time** while the text elements **fly in from the left** one at a time (fast, with an
ease-back overshoot), paced across the clip and finishing on the **CTA, which breathes
with a soft glow**. It reuses the exact static layout, so the reel matches the image.

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-ad-image/scripts/build_ad_reel.py \
    --spec output/ads/<date>-<short-name>/<lead-magnet>/ad.json --seconds 15 --fps 30 [--music track.mp3]
```

Outputs next to the spec: `9x16/ad_reel.mp4`, `9x16/ad_reel_poster.png` (thumbnail), and a
few `ad_reel_preview_*.png` stills for quick review (deletable). Tune with `--seconds`
(shorter = punchier) and `--fps`.

- **Music — do NOT bundle copyrighted audio.** Leave it silent and add **Meta's licensed
  music** in the Reels ad editor (rights-cleared, and what Meta's own tip recommends), or
  pass `--music` with a royalty-free file you own.
- **Launching is automatic.** Once `9x16/ad_reel.mp4` exists, `nis-ad-launch` auto-detects it
  and launches it as a **video ad** — it uploads the reel straight to Meta (`/advideos`,
  Meta-hosted, no Supabase), waits for processing, uploads the poster as the thumbnail, and
  builds a `video_data` creative — all in `draft --go`, no manual upload. The reel is
  preferred over the static image whenever present; set `"launch_as": "image"` in `ad.json`
  to force the static instead.

### The reel background — what it should be (generic, topic-linked)

The reel's backdrop is **atmosphere, never the message**. It is a subtle, brand-tinted
"living dashboard" that **drifts slowly leftward** behind the text — so it feels alive without
ever competing with the foreground. It is **generic by construction**: the *motif is fixed*,
only its *content* changes per topic, so one definition serves every ad.

**What it contains** (all dim, low-contrast, bottom-weighted):
- a faint **grid** (the terminal/dashboard feel),
- a drifting **chart line** tinted by the ad's `accent` (green = opportunity, amber = neutral —
  it inherits the ad's framing), and
- an optional scrolling **ticker-tape of the topic's own tickers** — this is the topic link.

**How it's topic-linked (the generic trick):** don't design a bespoke background per topic —
just set `background.tickers` to the ad's tickers. A geopolitics ad drifts `XOM CVX XLE FRO`;
an AI ad drifts `NVDA AMD AVGO`. Same motif, same code, topic-specific names. Pull them from
the trend brief's `top_topic.tickers_in_play` (or `lead_story.most_affected`).

**Spec (`background` block, REEL only):**
- `motif`: `chart` (grid + drifting line + tape) · `grid` (grid + tape, no line) · `none` (static).
- `rising`: `true` draws a central **rising "stock price" chart** — a jagged uptrend that draws
  itself left→right (with a leading price dot + soft fill) across the clip, behind the text. Great
  for "winners"/opportunity ads; it sits under the copy so keep the copy short-ish on the right.
- `tickers`: the topic symbols for the tape (4–8 works best). Omit → no tape.
- `speed`: drift multiplier (default `1.0`; lower = calmer).
- A `background_image` photo overrides the motif and stays static (no drift).

**Guardrails:** keep it quiet — no flashing, no high-contrast motion, nothing that pulls the
eye off the headline/CTA. The text is the pitch; the background is mood. If in doubt, dim it.

#### Topic icons — a custom animation per topic, from ONE icon library

The topic visual comes from an **icon font** (Font Awesome 6 Free Solid, bundled at
`scripts/assets/fa-solid-900.ttf`, SIL OFL — free to redistribute). One font = a consistent,
professional look across every ad — you **name icons, you don't draw them**. A glyph drifts
across a band behind the text; icons that face a fixed way are flipped to their travel
direction. This replaces the generic chart line so it stays uncluttered.

Two ways to set it:
- **`background.scene`** — a named **preset** of layers (quickest):

| `scene` | Icons (drift directions) | Fits topics like |
|---|---|---|
| `tanker` | cargo-ship ◄ + fighter-jet ► (with contrail) | geopolitics · oil · Hormuz · shipping · defense |
| `ai` | microchip ◄ + satellite ► | AI · semiconductors · tech · data |
| `energy` | oil-can ◄ + bolt ► | energy · power · commodities |
| `crypto` | coins ◄ + rocket ► | crypto · risk-on |

- **`background.icons`** — an explicit list of **layers** for full control:
```json
"background": { "tickers": ["XOM","CVX"], "icons": [
  { "icon": "ship", "dir": "left",  "band": 0.74, "count": 2, "size": 150, "alpha": 90 },
  { "icon": "jet",  "dir": "right", "band": 0.16, "count": 2, "size": 96, "speed": 2.3, "trail": true }
] }
```
Layer fields: `icon` (a name in `ICON_MAP`), `dir` (`left`/`right`), `band` (0–1 vertical),
`count`, `size`, `speed`, `alpha`, `color` (`mut` dim | `accent`), `trail` (contrail behind it).
**Orientation is automatic** — directional glyphs (jet, plane, …) are flipped so the nose
matches `dir` (via `_ICON_FACES`); only set `flip` to override.

**To theme a new topic:** pick icons that fit (e.g. `chip`+`satellite`, `oil`+`bolt`,
`coins`+`rocket`, `truck`, `industry`, `globe`, `shield`) — either add a `SCENE_PRESETS` entry
or just list `background.icons`. To add a **font icon** that isn't mapped yet, drop its Font
Awesome codepoint into `ICON_MAP` (one line). For **richer/thematic art** the font lacks (e.g.
`cargo-ship`, from Game Icons), drop a mono PNG into `scripts/assets/` and register it in
`ICON_ASSETS` — it's recolored + animated exactly like a glyph. Bundled art must be
attribution-friendly (see `scripts/assets/ATTRIBUTION.txt`; Game Icons = CC BY, FA = OFL). No
drawing, ever.

**Guardrails still apply:** keep it dim and banded top/bottom; the icons are mood, the text is
the message.

## Trend-driven lead-magnet ads (the main use)

Built from a **`nis-trend-radar`** brief, this becomes a "would-have-helped" lead-magnet ad —
one per magnet (they're the meta_ads A/B). Map the brief onto the spec:

- `kicker` ← "This week in the market"
- `headline` / `headline_accent` ← `lead_story.narrative` distilled to one line + its number
- `subhead` ← the trend's scale (`{N} stories in 7 days, {delta}`)
- `bullets` ← the magnet pitch (`lead_magnets.<magnet>.pitch`) + the preset it configures
- `proof` ← a `most_affected` move (briefing) or a name from the matched screen (screening)
- `cta_label` + `destination` ← **`lead_magnets.<magnet>.url` verbatim** (the preset deep-link:
  `/briefings?tags=…&tickers=…` or `/marketscreenings/<slug>`), so the click lands pre-configured.

`utm_content=news_briefing` vs `market_screening` is already in those URLs, so `meta_ads
reconcile` attributes real sign-ups back to the trend + feature.

## Step 3 — Launch

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli preflight
.venv/bin/python -m services.meta_ads.cli draft --campaign 2026-07-14-geopolitics --go
```

`nis-ad-launch` treats the `<date>-<short-name>` folder as one campaign, turns each
lead-magnet subfolder (`briefing`, `market-screening`) into an ad set, and builds a
**single-image** creative from its `1x1/ad.png` — everything PAUSED until you flip it
Active. See the `nis-ad-launch` skill.

## Notes

- **One image beats a deck for cold traffic.** No swipe means the whole pitch is in frame 1 —
  the only frame most people see. That's the point of this skill.
- **Proof still rules.** A timely hook + a real number converts; a hook alone doesn't. If you
  have no real stat, drop `proof` rather than fake one.
- **Test variants** by rendering multiple `<slug>`s (vary headline, accent, proof, CTA) and
  letting Ads Manager pick the winner. Feed winners (via `reconcile`) into the next spec.
- **Single image is the whole ad system.** One image per ad, one message. (`nis-ad-launch`
  will still upload multiple `1x1/slide-*.png` as a carousel if they ever exist, but this
  skill only produces the single `1x1/ad.png`.)
```
