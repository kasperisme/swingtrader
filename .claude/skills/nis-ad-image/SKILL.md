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

## Step 1 — Author the spec (you, Claude)

Write `output/ads/<slug>/ad.json`:

```json
{
  "slug": "geopolitics-briefing-v1",
  "theme": "dark",                 // dark (default, high-punch) | light (site theme)
  "accent": "amber",               // amber (default) | pos (green)
  "brand": "newsimpactscreener.com",
  "mark": "NIS",
  "kicker": "This week in the market",
  "headline": "Iran moved the whole market. Did your inbox?",
  "headline_accent": "the whole market",   // the exact words to paint in the accent colour
  "subhead": "261 stories in 7 days — oil, COIN and energy all reacting.",
  "bullets": ["A daily brief on #geopolitics + XOM, COIN, AAPL",
              "In your inbox before the open — free"],
  "proof": {"ticker": "COIN", "ret": 30, "spy": 4},   // optional — REAL returns only
  "cta_label": "Get my briefing",
  "destination": "https://www.newsimpactscreener.com/briefings?tags=geopolitics,oil,iran&tickers=XOM,COIN,AAPL",
  "disclaimer": "Not financial advice. For education only.",
  "background_image": "hero.jpg",  // optional — a real photo in the slug dir (cover-fit + scrim). Omit → generated motif.
  "ad": {
    "primary_text": "the in-feed caption above the image (pain → the tool → the proof → CTA)",
    "headline": "The news that moved your stocks — before the open",  // shows under the image
    "description": "Free daily briefing. No account.",
    "cta_label": "Sign Up",
    "destination": "https://www.newsimpactscreener.com/briefings?tags=…&tickers=…"
  }
}
```

- **`headline` + `headline_accent`** carry the ad. Keep the headline < ~9 words; the accent is
  the single number/idea that stops the scroll. One accent only.
- **`proof`** is optional but strong — a real `$TICKER +NN%` vs the S&P. Never invent it; pull
  from a `setup.json` `benchmarks` or a trend brief's `most_affected`.
- **`ad.*`** feeds `ad_copy.txt` AND the single-image creative (its `headline`→`name`,
  `description`→`description` under the image). `ad.destination` is the real click target.

**Copy voice** — same anti-jargon rules as the reels: plain words, one point of view,
comparisons over terms, no invented figures. First line of `primary_text` is a self-contained
scroll-stopper.

## Step 2 — Render

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-ad-image/scripts/build_ad_image.py \
    --spec output/ads/<slug>/ad.json          # all ratios; add --ratios 4x5 to limit
```

Outputs under `output/ads/<slug>/`:
- `4x5/ad.png` — 1080×1350 (Meta feed)
- `9x16/ad.png` — 1080×1920 (TikTok / Reels / Stories)
- `1x1/ad.png` — 1080×1080 (square; the one `nis-ad-launch` uploads)
- `ad_copy.txt` — primary text · headline · description · CTA (paste into Ads Manager)

Review every render before shipping. `theme: dark` is the default for stopping power;
`background_image` swaps the generated chart motif for a real photo (cover-fit + readability
scrim), if you have one that fits.

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
.venv/bin/python -m services.meta_ads.cli draft --go     # creates a single-image PAUSED draft
```

`nis-ad-launch` auto-detects `1x1/ad.png` and builds a **single-image** creative (not a
carousel); everything is PAUSED until you flip it Active. See the `nis-ad-launch` skill.

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
