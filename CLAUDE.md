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

## Before touching Supabase data — READ THE CATALOG FIRST

**Rule: never write a query, a migration, or any peer/aggregate/graph/similarity
computation over `swingtrader` data before checking what already exists.**

```bash
cd code/analytics && cat docs/supabase_index.md        # 84 objects + 51 RPCs, one line each
cd code/analytics && .venv/bin/python -m services.catalog.build find "<capability>"
```

The schema is large (84 tables/views, 851 columns, 51 functions) and much of what
looks missing is already built and refreshed daily. A peer-relationship finder was
once written from scratch, iterated through four failed designs, and still returned
NVDA and AAPL as Crocs' peers — while `ticker_relationship_edges` held 38k typed,
directional, evidence-backed edges and answered it correctly in one query.

Load the **`supabase-schema`** skill for the workflow, the most-reinvented list, and
the join traps. Regenerate after any migration:
`cd code/analytics && .venv/bin/python -m services.catalog.build`

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
| `supabase-schema` | **Before** any query, migration, or peer/aggregate/graph/similarity computation over `swingtrader` data — the generated catalog of 84 tables/views + 51 RPCs with the intent behind each, plus the article-to-ticker join traps. Also use before concluding something "doesn't exist yet" |
| `caveman` | Writing `cavemanBody` for any blog post or doc page |
| `ui-ux-pro-max` | Designing or reviewing UI components, layouts, styles |
| `taste-skill` | Building any UI — enforces premium design standards, kills generic AI patterns |
| `viral-reel` | Producing short vertical data-reels (bar chart race videos) from the news-impact data foundation; Claude directs the story, Remotion renders |
| `nis-arena-report` | The Arena's weekly broadcast package — a still league TABLE (4:5/9:16/1:1) + the season RACE reel, reported in sports grammar (position, ▲▼ movement, W/L form guide, promotion/relegation bands, one strap line). Storyline is DETECTED, not chosen, so the unflattering hook (a control leading; the coinflip beating LLMs) ships. Read-only over the arena public views; renders through the shared Remotion project |
| `nis-stock-breakdown` | Making an Instagram-ready swing-trade breakdown of one stock from its NIS Momentum setup — annotated price+volume chart, fundamentals, and a derived entry/stop/target trade, assembled into a carousel + caption |
| `nis-breakout-alert` | Hourly (`/loop 1h`) auto-poster: reads the breakout-screening agent's latest result; when tickers have just CONFIRMED price+volume breakouts, renders ONE roundup reel (live board of all breakouts, most-significant one highlighted + featured) and posts it immediately to IG+TikTok via Zernio. Live/urgency framing; reuses the nis-stock-breakdown render scripts + the social_publishing publisher |
| `nis-ad-image` | Single-image ad for Meta + TikTok (eToro pattern: brand mark → bold headline w/ one accent → subhead → green-check benefits → optional REAL proof stat → CTA, over a branded hero). Renders 4:5 / 9:16 / 1:1 + `ad_copy.txt` from a Claude-authored `ad.json`. The creative for ads (esp. trend-driven lead-magnet ads from `nis-trend-radar`); feeds `nis-ad-launch` as a single-image creative |
| `nis-ad-launch` | The paid last mile: pushes a rendered `nis-ad-image` (its `1x1/ad.png` + `ad.json`) into Meta Ads Manager as **PAUSED** campaign drafts via the `meta_ads` module. `preflight` checks every account/permission gate; `draft --go` builds the feature A/B (1 campaign → 1 ad set/feature → 1 single-image ad/feature, isolated budgets), all PAUSED until you flip Active by hand. Also the measurement side (`insights`/`reconcile` → cost per REAL lead) |
| `nis-priced-in-story` | The **priced-in** reconstruction of ONE company as a narrated vertical REEL (IG/TikTok): what its price already believes, every assumption it refuses to fund, and the question that settles it — nothing withheld, a long ledger becomes more scenes. Picks the name on how well it will TELL, **refuses rows whose target spread is corrupted by a stock split** (7 of 543 live rows are), animates at 1080×1920, voices via ElevenLabs, posts through `social_publishing`. Paid single-image variants via `nis-ad-image`. Grounded tier only — the judged `priced_in_pct` never reaches a creative |
| `nis-trend-radar` | Find the single most talked-about news **topic/trend of the last week** — a data-backed "trend brief" for downstream ad generation. Reuses the `/articles` trend views (tag + ticker daily aggregates), buckets current-vs-prior 7-day windows, excludes generic process tags, and picks the dominant thematic story by volume × acceleration; pulls real evidence headlines + tickers in play, a distilled `lead_story`, and preset `lead_magnets` deep-links. Writes `output/trends/<date>/trend_brief.{json,md}`; feeds the headline of `nis-ad-image` |
| `ticker-pair-divergence` | Making a viral reel about a ticker PAIR — the non-obvious relationship (from `ticker_pair_stats` + the relationship graph), normalized line charts with company logos riding each line, the divergence flagged, and the mean-reversion (pairs) trade voiced |
| `nis-performance` | The whole-funnel performance foundation — wires GA4 + Search Console + Meta Ads + Supabase leads + PostHog into ONE snapshot joined on `utm_content`/feature (Supabase leads = conversion truth), computes cost-per-real-lead, and derives deterministic **routed** action flags. Writes `output/performance/<date>/snapshot.{json,md}`; the JSON is the data foundation the action skills consume (feeds `nis-ad-image` Step 0, SEO, CRO, conversion instrumentation). Read-only. Run before an ad/content push or weekly |

## Priced-In (scheduled, NYSE + NASDAQ)

See `code/strategylab/research/PRICED-IN-FINDINGS.md` §8 and `code/strategylab/README.md`.

Reconstructs what a share price already contains and publishes it to
`/quote/<symbol>`. Runs unattended over the whole universe via the Mac Mini
crontab (`code/strategylab/scripts/run_priced_in.sh`).

```bash
cd code/strategylab
.venv/bin/python -m strategylab.social.cli universe queue    # what is due
.venv/bin/python -m strategylab.social.cli batch --dry-run   # the pass, without running it
.venv/bin/python -m strategylab.social.cli predict status    # the sealed Tier-3 ledger
```

Three things to know before touching it:

- **The LLM backend is Ollama** (`glm-5.1:cloud`), set in `code/strategylab/.env`
  via `STRATEGYLAB_LLM_BACKEND=ollama`. ~110s/ticker; a full 725-name pass is one
  week of nightly runs. `investigate` needs tool use and stays on Anthropic.
- **`batch` promotes rows to the PUBLIC quote pages.** The gate publishes only a
  row that can render AND whose inputs moved (new analyst model, median ≥2%,
  price ≥10%, or the live row ≥30 days old). Held rows are still written.
- **The prediction ledger is Supabase, not `output/runs/predictions.db`.** The
  local SQLite file is dead; `swingtrader.research_predictions` is the source of
  truth and its trigger enforces seal-once/resolve-once server-side.

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

## The Arena (competing AI paper-trading agents)

See `code/analytics/services/arena/README.md` and the public page at `/arena`.

Nine agents, **$100,000 each**, trading against each other daily. Every agent gets
the same model, broker, risk limits and universe; what differs is **which slice of
the platform's data it can see** (`roster.py`). That difference is the experiment.
Two of the nine are deterministic controls — `the-index` (buy SPY, hold) and
`the-coinflip` (seeded random) — because a leaderboard of seven strategies with
nothing to beat is a ranking, not a result.

**The rule that makes it credible: an LLM's only write is an order intent.** It
calls `place_order`; cash, positions, fills, realised P&L and NAV are computed by
`broker.py` (deterministic Python) from the tables. A model cannot mark its own
book, spend cash it does not have, or revise a fill after the outcome is known —
a DB trigger enforces that last one. Rejected orders are stored, not discarded.

```bash
cd code/analytics
.venv/bin/python -m services.arena.cli sync-roster    # write roster.py -> DB, fund accounts
.venv/bin/python -m services.arena.cli run-day        # the nightly job: fill -> mark -> decide
.venv/bin/python -m services.arena.cli standings
.venv/bin/python -m services.arena.cli show the-skeptic
```

**Championships.** The arena runs in fixed 3-month windows (`arena_championships`).
Every agent is re-funded at the start of each, so standings/returns/drawdown are
computed WITHIN a championship — a curve that spans a re-funding is not a curve.
The winner takes a title that carries forward until another agent wins a later
championship; consecutive wins are defences. The lineage is DERIVED
(`arena_title_lineage_v`) from concluded championships, never stored as a
mutable flag.

```bash
.venv/bin/python -m services.arena.cli championship create --slug season-3 --start 2027-01-01
.venv/bin/python -m services.arena.cli championship start   --slug season-3
.venv/bin/python -m services.arena.cli championship conclude --slug season-2
.venv/bin/python -m services.arena.cli championship title      # the belt lineage
```

**Historical replay** (`services/arena/backtest.py`). `cli.py backtest --start
<date>` replays past sessions. Prices are always point-in-time (each session's
own open and close). The agents' RESEARCH mostly is not: `--point-in-time` gates
the only source with real history (the screening boards, via `run_at`), while
news scores, priced-in rows and pair z-scores cannot be rewound at all — see the
per-agent table in `services/arena/README.md`. A replay demonstrates the
machinery; it is not evidence a strategy works. Every replayed row carries
`is_backtest`. Resumable; `--decide-every N` spaces out the expensive LLM
decisions while still filling and marking daily.

**Provenance.** Every tool call is recorded and turned into linkable resources
(`arena_decisions.resources`) — the specific screening board, quote pages and
articles a decision rested on, each with the URL of the page publishing it. The
agent pages link both to those and to the trader they are modelled on
(`/traders/<slug>`, a Sanity `trader` document joined by `arenaAgentSlug`).

Five things to know before touching it:

- **Fills happen at the NEXT session's open, never the decision session's close.**
  Filling at the close would hand every agent a free overnight gap — the easiest
  way to manufacture a fake edge. `marks.py` keeps opens and closes separate for
  exactly this reason.
- **`roster.py` is the source of truth**, `arena_agents` is a projection. Editing a
  prompt and re-running `sync-roster` writes definition columns only — it never
  resets a running experiment. Changing `ARENA_MODEL` mid-competition invalidates
  the comparison, so it is one env var for the whole roster.
- **Run `tests/test_arena_broker.py` after any broker change.** 21 in-memory tests
  over slippage direction, weighted average cost, realised P&L on partial closes
  and shorts, and every rejection path. If that math drifts, every number on the
  public leaderboard is wrong.
- **Every write must be inside a championship.** `store` raises rather than
  writing an unscoped row; `scheduler.bind_championship()` sets it. `--only`
  scopes fill and mark as well as decide — marking the whole roster during a
  partial replay fabricates flat curves for agents that never took part.
- **`get_fmp_tool_schemas()` cannot be called from a running event loop** (it uses
  `asyncio.run`). `scheduler._warm_fmp_catalogue()` populates its cache before
  the loop starts. Without that warm-up the failure is swallowed as a warning
  and FMP-enabled agents silently run with no FMP tools at all.

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

## Arena Creatives (the weekly broadcast package)

See `code/analytics/services/arena_creatives/README.md` and the `nis-arena-report` skill.

Turns the Arena's live standings into the two assets a sports league publishes every
week: a still **league table** (4:5 / 9:16 / 1:1) and the season **race** reel (9:16).
Read-only, and over the **public** views only (`arena_leaderboard_v`,
`arena_nav_history_public_v`, `arena_championships_public_v`) — those filter on
`is_published` in the view, so a creative cannot publish an agent still being tuned.

```bash
cd code/analytics
.venv/bin/python -m services.arena_creatives.cli standings    # the table, with ▲▼ + form
.venv/bin/python -m services.arena_creatives.cli storylines   # every hook it supports
.venv/bin/python -m services.arena_creatives.cli commentary   # the voice-over beat sheet
.venv/bin/python -m services.arena_creatives.cli package      # standings + table ×3 + race
.venv/bin/python -m services.arena_creatives.cli race --voice --music   # voiced + scored
```

Lands in `output/arena/<season>/<as-of date>/`. Publishing goes through
`social_publishing`'s **ad-hoc** mode (`--media` + `--caption-file`, `--ticker ARENA` as
the storage label) — no per-ticker folder, nothing in the publisher needed changing.

Four things to know before touching it:

- **The story is detected, not chosen.** `storylines.py` ranks the hooks the table
  supports. It exists because the best story is usually the least flattering one — a
  control leading, a random number generator beating three LLM agents — and a human
  picking week after week drifts toward the flattering read. The same detectors are the
  trigger for a future event-fired upset alert.
- **The race metric is return, not NAV**, drawn as bars diverging from a zero line on an
  axis fixed for the whole video. Nine books between $90k and $103k are nine bars of
  identical length; a rescaling axis makes every bar move on a day nothing happened.
- **No club colour may be gain-green or loss-red** (`palette.py`). In the race the bar IS
  the club colour and its direction carries the sign.
- **The commentary is frame-locked.** `commentary.py` emits *beats* — an event, the
  session it happened on, and the second of the reel that session is on screen (the
  timeline mirrors `ArenaRace.tsx`, so `OUTRO_S` is duplicated in both and must stay in
  step). One beat list drives the ElevenLabs voice-over, the burned-in captions (most
  social video is watched muted) and the ducked music bed, which is **generated** via the
  sound-effects endpoint and cached — not licensed from anywhere. Budgets are computed on
  SPOKEN words ("plus 2.89%" is two written words and about six spoken) against a voice's
  **measured** words-per-second, so a new commentator must be measured before it becomes
  a default. Watch `speech coverage` in `cli commentary`: ~80% is the target.
- **The renders live in the `viral_reels` Remotion project** (`ArenaTable.tsx`,
  `ArenaRace.tsx`, registered in `Root.tsx`) — the repo's single render surface. A second
  Remotion app would duplicate `node_modules`, the theme and the interpolation helpers,
  and let the two drift apart visually.

Trap: **`filled_orders` ≠ `closed_trades`.** The trade count and win rate on the table are
over CLOSED positions — an agent can have 12 fills and 1 close.

## CEO Directory (`/ceos`)

See `code/analytics/services/ceos/README.md`. The CEO name on `/quote/<symbol>`
links to `/ceos/<slug>`: title, SEC proxy pay history, leadership team, and the
headlines that name them. Data is `swingtrader.company_ceos` (one row per symbol,
filled from FMP by `services.ceos.cli refresh`), and `ceo_directory_v` groups it
into people. An optional Sanity `ceo` document (portrait + `body`/`cavemanBody`)
adds editorial content to a page. It is joined by slug, which must be copied from
the page URL.

```bash
cd code/analytics
.venv/bin/python -m services.ceos.cli refresh --limit 500   # largest first, skips rows < 30d old
.venv/bin/python -m services.ceos.cli stats
```

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

## Google Analytics + Search Console (read-only insight)

See `code/analytics/services/google_analytics/`. Service-account access to the **GA4 Data
API** (acquisition channels, landing pages, key events) + the **Search Console API**
(organic queries, CTR/position, striking-distance SEO opportunities). GA4 is already
installed site-side (gtag `G-FQ87KHKLS5` in `app/layout.tsx`).

```bash
cd code/analytics
.venv/bin/python -m services.google_analytics.cli verify        # green/red creds + both APIs
.venv/bin/python -m services.google_analytics.cli discover      # list accessible GA4 props + GSC sites
.venv/bin/python -m services.google_analytics.cli summary|channels|landing|conversions|queries|sc-pages|opportunities
.venv/bin/python -m services.google_analytics.cli sitemaps          # registered sitemaps + last fetch
.venv/bin/python -m services.google_analytics.cli resubmit-sitemap  # force Google to re-download it
.venv/bin/python -m services.google_analytics.cli inspect --since 24h   # URL Inspection triage of new URLs
.venv/bin/python -m services.seo.cli indexnow --since 24h               # push new URLs to Bing/Yandex
```

**New-page workflow:** there is no API for GSC's "Request indexing" button (the
Indexing API is licensed for JobPosting/livestream pages only — using it for
anything else is spam). `inspect` reads the sitemap's `<lastmod>`, runs the URL
Inspection API (2,000/day) and sorts URLs into request / fix / quality /
indexed; only the **request** bucket is worth the UI's ~10 manual requests a
day, and each row carries its GSC deep link. Both `--since` flags depend on
`app/sitemap.ts` emitting only TRUE lastmods — never stamp `now`.

`resubmit-sitemap` is the only supported way left to make Google re-fetch the
sitemap (the `google.com/ping?sitemap=` endpoint was retired in 2023). It needs
the **write** `webmasters` scope — `client.gsc_write_client()`, requested nowhere
else — plus Full/Owner permission in Search Console. It refreshes Google's copy
of the URL LIST; it does not force per-page indexing, and `contents[].indexed`
in the API response is a dead legacy field that always reads 0.

Needs `GA4_PROPERTY_ID`, `GSC_SITE_URL`, and `GOOGLE_APPLICATION_CREDENTIALS` (path to the
service-account JSON in the gitignored `secrets/`) or inline `GOOGLE_SERVICE_ACCOUNT_JSON`
in `code/analytics/.env`. The SA needs Viewer on the GA4 property + a user in Search Console,
and the Data / Admin / Search Console APIs enabled in the Cloud project.

## Performance Foundation (whole-funnel insight)

See `code/analytics/services/performance/README.md` and the `nis-performance` skill.

The **unified** layer over every wired platform (GA4, Search Console, Meta Ads, Supabase
leads, PostHog). Joins them along the funnel keyed on **`utm_content`/feature** (Supabase
leads = the conversion truth), computes **cost-per-real-lead** per feature, and derives
deterministic **routed** action flags (`{severity, area, finding, action, route_to}`). Each
source is a fault-tolerant adapter, so a dead platform degrades gracefully.

```bash
cd code/analytics
.venv/bin/python -m services.performance.cli status               # which platforms are reachable
.venv/bin/python -m services.performance.cli snapshot --days 28   # build → output/performance/<date>/snapshot.{json,md}
```

The **JSON is the data foundation** the action skills consume (`nis-ad-image` Step 0, SEO,
CRO, conversion instrumentation); the **MD** is the analyst digest. Read-only — it never
changes campaigns/spend/content. Add a platform by adding a `<name>_block()` adapter to
`services/performance/sources.py` + (optionally) a `_flags()` rule with a `route_to`.

## Sanity Studio

Mounted at `/studio`. Use Vision tool for GROQ queries.

Content types:
- `post` — Blog posts
- `docPage` — Documentation pages (grouped by `section`, ordered by `order`)
- `author`, `category` — Supporting types
