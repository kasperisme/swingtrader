# swingtrader — Claude Code Project Guide

## Project Overview

**News Impact Screener** — swing trading research platform connecting headlines to stocks for retail investors.

Stack: Next.js (App Router) + TypeScript + Supabase (auth/DB) + Sanity (CMS) + Tailwind, deployed on Vercel.

Key directories:
- `code/ui/` — Next.js app
- `code/ui/sanity/` — Sanity studio + schemas
- `code/ui/lib/sanity/` — GROQ queries, types, Sanity client
- `code/ui/app/blog/` — Blog pages
- `code/ui/app/docs/` — Documentation pages
- `code/ui/components/` — Shared UI components

## Content Writing — Blog Posts & Documentation

### Always write two versions

Every blog post (`post`) and documentation page (`docPage`) in Sanity has two body fields:

| Field | Purpose |
|-------|---------|
| `body` | Full prose — complete sentences, SEO-friendly, conversational |
| `cavemanBody` | Compressed caveman version — same structure, ~70% fewer words |

**Whenever writing or editing blog or doc content, always produce both `body` and `cavemanBody`.**

### Use the caveman skill for `cavemanBody`

Invoke `.claude/skills/caveman/SKILL.md` when producing `cavemanBody` content.

Core caveman rules (quick ref):
- Drop: articles (a/an/the), filler (just/basically/really), hedging, pleasantries
- Keep: technical terms exact, code unchanged, numbers/data
- Pattern: `[thing] [action] [reason]. [next step].`
- Fragments OK. Short synonyms. Active voice only.

Example pair:

> **Normal:** "The news impact score is calculated by analyzing sentiment, volume, and asset relevance across multiple sources."
>
> **Caveman:** "News impact score = sentiment + volume + asset relevance. Multi-source."

### Sanity schema reference

```typescript
// postType.ts + docPageType.ts both have:
body:        blockContent   // full prose
cavemanBody: blockContent   // caveman-compressed prose (optional but always fill it)
```

GROQ queries already fetch both fields. The UI switches between them via `CavemanContent` component reading `CavemanModeProvider` context.

## Caveman Mode — UI

The caveman/businessman toggle is global (localStorage-backed via `lib/caveman-mode.tsx`). It appears in:
- Desktop header (`components/site-header.tsx`)
- Mobile nav drawer (`components/site-header-mobile-nav.tsx`)
- Docs sidebar (`app/docs/_components/docs-sidebar.tsx`)

`CavemanContent` (`components/caveman-content.tsx`) renders the appropriate body based on the context.

## Skills Available

| Skill | Use when |
|-------|---------|
| `caveman` | Writing `cavemanBody` for any blog post or doc page |
| `ui-ux-pro-max` | Designing or reviewing UI components, layouts, styles |
| `taste-skill` | Building any UI — enforces premium design standards, kills generic AI patterns |
| `viral-reel` | Producing short vertical data-reels (bar chart race videos) from the news-impact data foundation; Claude directs the story, Remotion renders |
| `nis-stock-breakdown` | Making an Instagram-ready swing-trade breakdown of one stock from its NIS Momentum setup — annotated price+volume chart, fundamentals, and a derived entry/stop/target trade, assembled into a carousel + caption |
| `nis-breakout-alert` | Hourly (`/loop 1h`) auto-poster: reads the breakout-screening agent's latest result; when tickers have just CONFIRMED price+volume breakouts, renders ONE roundup reel (live board of all breakouts, most-significant one highlighted + featured) and posts it immediately to IG+TikTok via Zernio. Live/urgency framing; reuses the nis-stock-breakdown render scripts + the social_publishing publisher |
| `nis-ad-image` | Single-image ad for Meta + TikTok (eToro pattern: brand mark → bold headline w/ one accent → subhead → green-check benefits → optional REAL proof stat → CTA, over a branded hero). Renders 4:5 / 9:16 / 1:1 + `ad_copy.txt` from a Claude-authored `ad.json`. The creative for ads (esp. trend-driven lead-magnet ads from `nis-trend-radar`); feeds `nis-ad-launch` as a single-image creative |
| `nis-ad-launch` | The paid last mile: pushes a rendered `nis-ad-image` (its `1x1/ad.png` + `ad.json`) into Meta Ads Manager as **PAUSED** campaign drafts via the `meta_ads` module. `preflight` checks every account/permission gate; `draft --go` builds the feature A/B (1 campaign → 1 ad set/feature → 1 single-image ad/feature, isolated budgets), all PAUSED until you flip Active by hand. Also the measurement side (`insights`/`reconcile` → cost per REAL lead) |
| `nis-trend-radar` | Find the single most talked-about news **topic/trend of the last week** — a data-backed "trend brief" for downstream ad generation. Reuses the `/articles` trend views (tag + ticker daily aggregates), buckets current-vs-prior 7-day windows, excludes generic process tags, and picks the dominant thematic story by volume × acceleration; pulls real evidence headlines + tickers in play, a distilled `lead_story`, and preset `lead_magnets` deep-links. Writes `output/trends/<date>/trend_brief.{json,md}`; feeds the headline of `nis-ad-image` |
| `ticker-pair-divergence` | Making a viral reel about a ticker PAIR — the non-obvious relationship (from `ticker_pair_stats` + the relationship graph), normalized line charts with company logos riding each line, the divergence flagged, and the mean-reversion (pairs) trade voiced |

## Scheduled Screenings (Agent)

See `.openclaw/skills/screen-agent/SKILL.md` for full setup docs.

Architecture: OpenClaw handles scheduling (one sync cron + per-screening jobs), Python handles execution (LLM agent loop + data tools + Telegram delivery).

Key files (under `code/analytics/services/agent/`):
- `engine.py` — single-ticker LLM agent loop, `run_screening`, Telegram delivery
- `multi_ticker.py` — fan-out pipeline for screenings with ≥2 tickers: classify → skill recipe | dynamic plan → per-ticker ladder → conclude
- `skills.py` — predefined `ScreeningSkill` recipes (`news_impact`, `breakout`, `portfolio_rundown`, `relationship_contagion`) + deterministic analytics + `classify_skill`
- `data_queries.py` — Supabase query wrappers (market-wide + user-specific)
- `sync_crons.py` — Reconciles Supabase screenings with OpenClaw cron jobs
- `cli.py` — CLI: `tick`, `run <id>`, `setup-cron`, `validate-skills`, `classify`
- `code/ui/app/actions/screenings-agent.ts` — Server actions + plan gates
- `code/ui/app/protected/agents/` — UI for managing agents

### Multi-ticker = skills-first

When a screening has ≥2 tickers, `multi_ticker.py` runs. A cheap classifier maps
the prompt to a predefined skill whose **hardcoded** tool plan (internal RAG +
FMP, no model tool-choice) runs a deterministic-first ladder: **FETCH** (literal
tool calls) → **COMPUTE** (`skill.analytics`, pure Python, decides clear cases) →
**JUDGE** (LLM only for ambiguous tickers, tuned by `skill.eval_focus`) →
**VERDICT** (concluder). Only when no skill fits does it divert to the legacy
dynamic LLM planner. Run `python -m services.agent.cli validate-skills` after FMP
plan changes to confirm/repair the breakout skill's FMP tool names.

## Viral Reels (Data-Reel Generator)

See `.claude/skills/viral-reel/SKILL.md` and `code/analytics/services/viral_reels/README.md`.

Turns the news-impact data foundation (+ FMP price/OHLC) into ~20s vertical
video reels (r/dataisbeautiful style). Two formats: **bar chart race**
(`BarChartRace` — viral areas racing by volume) and **price + news**
(`PriceNewsChart` — an OHLC candlestick chart with scored news events plotted on
it to show which headlines moved the stock). Split:
- **Python** (`services/viral_reels/`) — deterministic data: builds race
  keyframes from `news_trends_*_daily_v` views + ticker sentiment, fetches the
  FMP price overlay, ranks candidate "viral" stories. No creative choices.
- **Claude Code** (`viral-reel` skill) — the director: picks the story, writes
  hook/captions/takeaway, assembles the `ReelSpec`.
- **Remotion** (`services/viral_reels/reel/`) — renders the `ReelSpec` to MP4.

Key files:
- `code/analytics/services/viral_reels/data_sources.py` — race-keyframe builders + FMP overlay
- `code/analytics/services/viral_reels/spec.py` — `ReelSpec` contract + validation (mirror of `reel/src/types.ts`)
- `code/analytics/services/viral_reels/story_finder.py` — heuristic story candidates
- `code/analytics/services/viral_reels/cli.py` — `stories|snapshot|series|prices|headlines|article-images|scaffold|price-news|news-candidates|catalysts|fmp-news|fmp-press|validate|render`
- `code/analytics/services/viral_reels/data_sources.py` — also wraps FMP **stock-news** (`fmp_stock_news`) + **press-releases** (`fmp_press_releases`) to widen thin internal coverage and anchor moves to the company's own catalysts
- `code/analytics/services/viral_reels/reel/src/compositions/BarChartRace.tsx` — bar-chart-race animation
- `code/analytics/services/viral_reels/reel/src/compositions/PriceNewsChart.tsx` — OHLC candlestick + news events animation

## Social Publishing (Content Distribution)

See `code/analytics/services/social_publishing/README.md`.

The deterministic **last mile** that pushes finished nis-stock-breakdown assets
(`output/setups/<TICKER>/`) to **Instagram, Facebook, TikTok, LinkedIn**.
Producing the content is a hand-iterated creative process; this service does no
creative work — it reads what's on disk, stages media to a public Supabase
Storage URL, and posts via a **publishing aggregator** (one REST API instead of
four native OAuth flows + Meta/TikTok app review). Backend is pluggable via
`SOCIAL_BACKEND`: **`zernio`** (default, free tier, posts per `accountId`) or
**`ayrshare`** (alternative); the asset/caption layer is identical for both —
only `zernio.py`/`ayrshare.py` behind `backends.py` differ. No scheduler, no
queue, no approval gate — run it per ticker when the assets are final.

```bash
cd code/analytics
.venv/bin/python -m services.social_publishing.cli accounts          # map ZERNIO_ACCOUNT_* env
.venv/bin/python -m services.social_publishing.cli publish --ticker NWPX --dry-run
.venv/bin/python -m services.social_publishing.cli publish --ticker NWPX --platforms linkedin,instagram
```

Per-platform copy: drop `social/<platform>.txt` (e.g. a LinkedIn-voiced caption)
or a `social/manifest.json` (override `kind`/`media`, e.g. LinkedIn as a slide
carousel) in the ticker folder; both fall back to `caption.txt` / the reel.
Needs `ZERNIO_API_KEY` + `ZERNIO_ACCOUNT_*` (or `AYRSHARE_API_KEY`) and a public
`SOCIAL_MEDIA_BUCKET` Supabase bucket.

## Meta Ads (create drafts + measure)

See `code/analytics/services/meta_ads/README.md` and the `nis-ad-launch` skill.

Meta Marketing API, both halves of the paid-ads loop:
- **Create (write, `ads_management`):** `preflight` green/red-checks every gate, then
  `draft --campaign <date>-<short-name> --go` creates a campaign from that folder — 1 ad set
  per lead-magnet subfolder (`briefing` / `market-screening`) → 1 single-image ad each,
  isolated budgets, rollback on any failure, all **PAUSED** until you flip Active by hand.
  Creative comes from `nis-ad-image` (`output/ads/<date>-<short-name>/<lead-magnet>/1x1/ad.png`).
- **Measure (read, `ads_read`):** `insights` rolls per-ad CTR/CPC/spend/Leads up by
  `utm_content` (feature: `market_screening` vs `news_briefing`, from each creative's
  `url_tags`); `reconcile` puts Meta spend/clicks next to the **real email leads in
  Supabase** → cost per actual lead.

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli verify
.venv/bin/python -m services.meta_ads.cli preflight               # check gates before creating
.venv/bin/python -m services.meta_ads.cli draft --campaign <date>-<short-name> [--go] [--budget 70]
.venv/bin/python -m services.meta_ads.cli insights [--since YYYY-MM-DD]
.venv/bin/python -m services.meta_ads.cli reconcile [--since YYYY-MM-DD]
.venv/bin/python -m services.meta_ads.cli design [--by hook_type]   # perf ↔ ad design genome (join on ad_id)
```

Needs `META_ADS_TOKEN` (System User) + `META_AD_ACCOUNT_ID` in `code/analytics/.env`
(+ `META_PAGE_ID`, optional `META_IG_ACCOUNT_ID` / `META_DSA_BENEFICIARY` for creation).
Pairs with the UTM capture (`metadata.utm`) + pixel `Lead` events on the subscribe forms
and the `/protected/attribution` UI view.

## Sanity Studio

Mounted at `/studio`. Use Vision tool for GROQ queries.

Content types:
- `post` — Blog posts
- `docPage` — Documentation pages (grouped by `section`, ordered by `order`)
- `author`, `category` — Supporting types
