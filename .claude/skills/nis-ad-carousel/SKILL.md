---
name: nis-ad-carousel
description: >-
  Produce a paid-ad carousel for Meta (Facebook/Instagram) and TikTok that sells the
  News Impact Screener product — the market-screening feature and the custom news
  screener — using a feature-led, PROOF-driven arc (persona pain → what it does →
  a real screened result → CTA). Renders 5–6 slides in BOTH 4:5 (Meta feed) and 9:16
  (TikTok) from a Claude-authored spec, plus an ad_copy.txt (primary text / headline /
  CTA) to paste into Ads Manager. Use when the user wants an "ad carousel", "carousel
  ad", "promo carousel", "Meta/TikTok ad", or to advertise the screener/product itself
  (NOT an organic single-stock breakdown — that's nis-stock-breakdown).
---

# NIS Ad Carousel

A **product ad**, not an organic post. It sells News Impact Screener to cold traffic by
naming the busy-trader's pain, showing the two core features, and then **proving it with
a real screened result** — the wedge against a niche full of promise-only ads. Output is
the *creative package*; you upload it into Meta/TikTok Ads Manager (see "Publishing").

## The ad arc (5–6 slides)

Cold-traffic ads earn the click. Keep this spine:

```
1 COVER    — persona-pain hook (the reader's exact frustration). No product yet.
2 PROBLEM  — the villain: the setups exist, but they're buried / move before you find them.
3 FEATURE  — market screening: "scans the whole market daily" (mock: screener board).
4 FEATURE  — the custom news screener: "turns the news into tickers" (mock: news→ticker).
5 PROOF    — a REAL screened winner vs the S&P ("proof, not promise"). The differentiator.
6 CTA      — one action → newsimpactscreener.com, free to start + disclaimer.
```

- **Lead with the persona, not the product.** The strongest niche ads open on the
  reader's pain ("you don't have time to watch charts all day"), then reframe.
- **Proof beats promise.** Competitors sell a framework/community with zero data. Your
  edge is a real result — a name the screen flagged that then beat the market. That slide
  carries the ad.
- **Two features, named plainly.** Market screening (finds the leaders) + the custom news
  screener (links headlines→tickers). Don't list ten things; sell these two.

## Step 1 — Author the spec (you, Claude)

Write `output/ads/<slug>/ad.json`. **The proof numbers must be REAL** — pull them from an
existing `output/setups/<TICKER>/setup.json` → `benchmarks.returns` (ticker return + S&P
return). Never invent a result. Pick a genuine market-beater you've already generated
(e.g. SEZL +135% vs S&P +8%, CXW +62% vs +6%).

```json
{
  "slug": "screener-proof-v1",
  "accent": "amber",
  "brand": "newsimpactscreener.com",
  "ad": {
    "primary_text": "the Meta/TikTok caption (pain → the tool → the proof → CTA)",
    "headline": "Find the setup in minutes, not hours",
    "description": "one-line subhead",
    "cta_label": "Sign Up",
    "destination": "newsimpactscreener.com"
  },
  "slides": [
    {"role": "cover",   "kicker": "for busy traders", "headline": "…pain…", "sub": "…turn…"},
    {"role": "problem", "kicker": "the problem", "headline": "…villain…", "body": "…"},
    {"role": "feature", "kicker": "what it does · 1", "headline": "Scans the whole market, daily", "body": "…", "mock": "screener"},
    {"role": "feature", "kicker": "what it does · 2", "headline": "Turns the news into tickers", "body": "…", "mock": "news"},
    {"role": "proof",   "kicker": "proof, not promise", "headline": "It flags them before the move", "ticker": "SEZL", "ret": 135, "spy": 8, "sub": "…"},
    {"role": "cta",     "headline": "See what it found today.", "url": "newsimpactscreener.com", "note": "Free to start", "disclaimer": "Not financial advice. For education only."}
  ]
}
```

Roles + fields: `cover` (headline, sub) · `problem` (headline, body) · `feature`
(headline, body, `mock: "screener"|"news"`) · `proof` (headline, ticker, ret, spy, sub) ·
`cta` (headline, url, note, disclaimer). Every slide takes an optional `kicker`. Keep
headlines short — they auto-wrap and center. `accent`: `amber` (default) or `pos` (green).

**Copy voice** — same anti-jargon rules as the reels: plain words, one point of view,
comparisons over terms, no invented figures. The `ad.primary_text` is the long caption
(pain → tool → proof → CTA); keep the first line a self-contained scroll-stopper.

## Step 2 — Render both ratios

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-ad-carousel/scripts/build_ad_carousel.py \
    --spec output/ads/<slug>/ad.json          # both ratios; add --ratios 4x5 or 9x16 to limit
```

Outputs under `output/ads/<slug>/`:
- `4x5/slide-01.png …` — **1080×1350**, Meta feed carousel cards.
- `9x16/slide-01.png …` — **1080×1920**, TikTok / Reels.
- `ad_copy.txt` — primary text · headline · description · CTA, formatted to paste in.

Light brand theme (warm off-white, navy ink, amber/green accents, mono data), swipe-dot
progress, brand wordmark footer. Content sits in a safe band (TikTok keeps the bottom
~18% clear of the UI). Review every slide before shipping.

## Publishing — read this

**Paid ads are created in Meta / TikTok Ads Manager, not by this pipeline.** The Zernio
publisher posts *organic* content; it cannot launch a paid campaign (that needs your ad
account, campaign/ad-set setup, budget, and targeting). So:

1. **Paid (the intended use):** upload the `4x5/` (Meta) or `9x16/` (TikTok) slide set as
   a carousel ad in Ads Manager, and paste `ad_copy.txt` into the primary text / headline
   / CTA fields. That's the deliverable.
2. **Organic (optional):** you can also post the slides as a normal carousel via
   `services.social_publishing` (drop a `social/manifest.json` pointing at the slide PNGs,
   or use the ad-hoc `--media` path). Good for testing creative organically before paying.

## Notes

- **One product, real proof.** The proof slide is the whole ad — always a true,
  already-generated market-beater. If you don't have one on disk, generate it first
  (`build_setup_chart.py` writes `benchmarks`), then cite it.
- **Test variants.** The spec is the creative genome — vary the cover hook (question vs
  pain vs shock), the proof ticker, and the CTA, render each as its own `<slug>`, and let
  Ads Manager's A/B pick the winner. Feed winners back into the next spec.
- **A carousel is not a reel.** This is static slides for a swipe/scroll ad. For an
  animated single-stock breakdown, use `nis-stock-breakdown`.
