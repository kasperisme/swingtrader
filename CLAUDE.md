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
(`PriceNewsChart` — a price line with scored news events plotted on it to show
which headlines moved the stock). Split:
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
- `code/analytics/services/viral_reels/reel/src/compositions/PriceNewsChart.tsx` — price line + news events animation

## Sanity Studio

Mounted at `/studio`. Use Vision tool for GROQ queries.

Content types:
- `post` — Blog posts
- `docPage` — Documentation pages (grouped by `section`, ordered by `order`)
- `author`, `category` — Supporting types
