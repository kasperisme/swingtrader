---
name: nis-trend-radar
description: >-
  Find the single most talked-about news topic/trend of the last week — a data-backed
  "trend brief" that feeds downstream ad generation (nis-ad-image). Reuses the exact
  views the public /articles trend board reads (tag + ticker daily aggregates), buckets a
  current-vs-prior 7-day window, excludes generic process tags (earnings/lawsuit/…), and
  picks the dominant thematic story by volume × acceleration — then pulls real evidence
  headlines and the tickers in play. Writes output/trends/<date>/trend_brief.{json,md}.
  Use when the user wants "what's the trend this week", "the most talked-about topic",
  "a timely/newsjacking ad angle", or trend input for an ad. NOT a stock setup
  (nis-stock-breakdown) and NOT the ad renderer itself (nis-ad-image).
---

# NIS Trend Radar

Finds **the story of the week** from the news-impact data and packages it as a *trend
brief* for a timely, newsjacking ad. It does the analysis; `nis-ad-image` turns the
chosen angle into creative; `nis-ad-launch` ships it. This skill makes no creative
choices and invents nothing — every topic, number, and headline comes from the data.

It reads the **same Supabase views the public `/articles` trend board uses**, so the
brief always agrees with what the site shows:

- `swingtrader.news_trends_tag_daily_v` — theme tags per day (`article_count`)
- `swingtrader.news_trends_ticker_daily_v` — ticker mentions per day (+ sentiment)
- `search_news_by_tags` RPC — the /articles tag search, for evidence headlines
- `news_article_tickers` — links the tickers actually in the topic's articles
- `news_impact_heads` (`cluster='STORY_KEY_POINTS'`) — the scored claims that
  **explain the story**, exactly as the /articles page renders them (`scores_json`
  = point→impact, `reasoning_json` = point→text)
- `news_articles.search_tags` — the co-occurring theme tags for the briefing preset
- `market_screenings` — the curated screeners, matched to the topic for the CTA

---

## Step 1 — Generate the brief

```bash
cd code/analytics
.venv/bin/python ../../.claude/skills/nis-trend-radar/scripts/find_weekly_trend.py \
    --window-days 7 --top 8
```

Writes to `output/trends/<end-date>/`:
- `trend_brief.json` — the full machine-readable brief (feed this to the ad step)
- `trend_brief.md` — a human-readable summary (read this to pick the angle)

Options:
- `--window-days N` — current window length; compared against the prior N days (default 7).
- `--top N` — board size per mode (default 8).
- `--evidence N` — how many headlines to pull for the topic (default 24).
- `--topic <tag>` — **force** a specific theme as the topic (overrides the auto-pick),
  e.g. `--topic semiconductors`. Use when you want a different angle than the winner.
- `--include-generic` — allow structural tags (earnings, lawsuit, …) to win. Off by default.

### How the topic is chosen

1. Every tag is folded into **current vs prior** window counts → `current`, `deltaPct`,
   `isNew`, and a 14-day `spark` (mirrors `lib/trends.ts` exactly).
2. **Generic process tags are excluded** from the pick — `earnings`, `guidance`,
   `lawsuit`, `class action`, `valuation`, `ratings`, etc. describe an article *type*,
   not a trend; they're always high-volume and make a dead hook. (They still appear in
   the raw `boards`.)
3. The winner maximizes **heat = volume × acceleration** (`current × (1 + 2·growth)`),
   so a big *rising* theme beats a bigger *flat* one — a flat evergreen isn't a trend.
4. The brief also hands you two alternate angles: **`biggest_topic`** (most articles) and
   **`fastest_rising_topic`** (steepest climb with real volume), plus 5 runner-ups —
   so you can pick the angle, not just accept the default.

---

## The one story — `lead_story`

The brief's first field, **`lead_story`**, is the single narrative the ad is built on —
already distilled so there's no synthesis to do. It's derived deterministically from the
strongest signals: the dominant topic + its highest-impact scored claim (the `driver`) +
the tickers the story is actually moving and the direction. It carries:

- `narrative` — one ready-to-use paragraph, e.g. *"President Trump threatened to
  'decimate and destroy' Iran… It's the week's most-discussed market story — 259 articles,
  up 101% vs last week — and it reads risk-off for stocks. Pressuring COIN while lifting
  AAPL, NVDA, MSFT."*
- `framing` — `risk-off` | `opportunity` | `mixed` (the ad's emotional angle)
- `driver` — the single scored claim (`text`, `impact`) the story hangs on
- `most_affected` — the top tickers by |impact|, with sign

**The ad leads with `lead_story.narrative`.** Use it as the cover hook + explainer spine;
pull the proof ticker from `most_affected` where possible. The rest of the brief (below)
is supporting detail if you want to enrich or pick a different angle.

## The conversion linkage — `lead_magnets`

The brief's `lead_magnets` field turns the trend into a **direct ad → lead-magnet path**.
The premise of the ad is: *"here's the story that dominated this week — and here's how
[the briefing / the screener] would have kept you on top of it."* The CTA lands the user
on the lead-magnet page **already configured for this topic**, so signing up is one step.
Two variants (they map 1:1 to the meta_ads A/B, `utm_content=news_briefing` vs
`market_screening`):

- **`news_briefing.url`** → `/briefings?tags=…&tickers=…` — the sign-up form arrives with
  the topic's tags (topic + co-occurring themes, e.g. `geopolitics, oil, iran,
  strait_of_hormuz`) and the tickers the story moves (e.g. `AAPL, XOM, COIN`) already
  filled in. `/briefings` reads these params and shows a "Preloaded for you" chip.
- **`market_screening.url`** → `/marketscreenings/<slug>` — the curated screener most
  connected to the topic. Matched by real **topical** keyword overlap; a **framing nudge**
  (risk-off→`nis-short`, opportunity→momentum/thematic) only breaks ties for the closest
  link, it doesn't count as topical support. `candidates[]` lists the runners-up.
- **`market_screening.needs_new_screening: true`** → **no existing screener clearly covers
  this narrative.** When set, the brief highlights it (a ⚠️ callout in the `.md`) and returns
  **`suggested_screening`** — a ready-to-build spec (`name`, `category`, `slug`, `description`,
  `seed_tickers`, an `llm_prompt` seed, and where to create it). Create it in the screenings
  admin and re-run the brief; the CTA then links to the new screener automatically. Until
  then the CTA uses the closest fallback (marked `is_fallback: true`) — decide whether the
  screening variant is worth running this week or whether to create the screener first.

Both URLs carry `utm_source=meta&utm_medium=paid&utm_campaign=trend_<topic>&utm_content=…`,
so `meta_ads reconcile` attributes real sign-ups back to the trend + feature. **These URLs
are the ad's CTA/destination — use them verbatim** (the presets are the whole point).

## Step 2 — Read the brief, pick the angle

Open `trend_brief.md`. The top block is **⭐ THE STORY** (`lead_story`) — use it. Below it
you'll see the top topic, its `delta`, **why it's trending** (the scored story key points),
the **tickers in play** (topic mentions + impact), the **headline evidence** (each with
its top claims), and the alternate angles — all supporting detail.

### "Why it's trending" — the story explained, not just counted

`top_topic.why_its_trending` is the payload that makes the ad *smart*: the highest-impact
**STORY_KEY_POINTS** claims aggregated across the topic's articles (deduped, ranked by
absolute impact), plus the same claims attached per-headline. These are the exact scored
statements the `/articles` page shows — e.g. for `#geopolitics` this week: *"Trump will
reimpose a naval blockade against Iran"*, *"20% fee for cargo through the Strait of
Hormuz"*, *"oil surged 9%"*. **Write the ad's explainer copy from these**, not from your
own priors — they're grounded, dated, and consistent with the site. The `impact` sign
tells you the market's read (− = risk/fear framing, + = opportunity framing).

Choose the angle for the ad:
- **Default:** the `top_topic` — the dominant, accelerating story (best for "everyone's
  talking about X this week").
- **Bigger, calmer story:** use `biggest_topic` if you want the largest theme regardless
  of acceleration.
- **Emerging story:** use `fastest_rising_topic` for a "this is just starting" angle.
- Corroborate: if the runner-ups reinforce the winner (e.g. topic `geopolitics` with
  runner-ups `iran`, `oil`, `middle east`), the story is real and safe to lead with.

The winning topic's `tickers_in_play` are the names moving *on that story* — computed
**within the topic's own articles**, not market-wide:
- `topic_mentions` — how often the ticker appears across the topic's articles (its
  prominence *in this story*), from `news_article_tickers`.
- `topic_impact` — the mean per-article sentiment on that ticker **in these same
  articles** (from `ticker_sentiment_heads_v`) — i.e. how *this story* is hitting the
  name (− = the trend is a headwind, + = a tailwind). `—` when it's mentioned but not
  sentiment-scored in-topic.
- `week_mentions` / `week_sentiment` — the ticker's overall weekly figures, for contrast
  (is the topic sentiment better or worse than how the name reads market-wide?).

So for `#geopolitics` you get the names the story is actually moving and its direction on
each (e.g. `COIN −0.30` as risk-off hits crypto, energy names catching a bid) — the exact
tickers the ad should name, with the right fear-vs-opportunity framing.

---

## Step 3 — Feed it into the ad (downstream)

This is a **lead-magnet ad**: it shows the week's story and how *one specific lead magnet*
would have kept the viewer on top of it, with a CTA that lands them on that magnet **preset
for the topic**. Build **two ads — one per magnet** (they're the meta_ads A/B):

**Ad A — News briefing** (`utm_content=news_briefing`, CTA → `lead_magnets.news_briefing.url`)
**Ad B — Market screening** (`utm_content=market_screening`, CTA → `lead_magnets.market_screening.url`)

Hand the chosen angle to **`nis-ad-image`** (single image — the clean default). **Default to
`lead_story`** and only override for a deliberate alternate angle. The brief maps onto the
`ad.json` spec:

- **`headline` + `headline_accent`** ← `lead_story.narrative` distilled to one line + its number
  (the accent is the scroll-stopper). Framed by `lead_story.framing` (risk-off vs opportunity).
- **`subhead`** ← the trend's scale: *"{N} stories in 7 days — {tickers} all reacting."*
- **`bullets`** ← the magnet's pitch + the preset it configures:
  - Ad A: `lead_magnets.news_briefing.pitch` + "the tags/tickers you'd follow" (the preset).
  - Ad B: `lead_magnets.market_screening.pitch` (the matched screen surfaces the names).
- **`proof`** ← a real move tied to the trend: for Ad A, a `most_affected` name (e.g. `COIN`);
  for Ad B, a name from the matched screen / `tickers_in_play`. Drop it rather than fake it.
- **`cta_label` + `ad.destination`** ← **`lead_magnets.<magnet>.url` verbatim** (the preset
  deep-link — the real click target `nis-ad-launch` sends to Meta). `brand` stays the short
  wordmark; the long UTM'd URL never shows on the image.
- **`ad.primary_text`** ← open on the trend, pivot to "you'd have known via {magnet}", close on
  the preset link.

Then render + launch: `nis-ad-image` (→ `output/ads/<slug>/`, incl. `1x1/ad.png`)
→ `nis-ad-launch` (`preflight` → `draft --go`, which auto-detects the single image). Because
the destination is preset per topic, click-to-configured-signup is one step — and `reconcile`
tells you which magnet the trend converted better on.

---

## Notes & guardrails

- **Never invent a topic or a headline.** If the data is thin, say so — don't manufacture
  a trend. Everything in the brief is a real aggregate or a real article.
- **Generic tags are out on purpose.** If you truly want "earnings season" as the theme,
  pass `--include-generic` or `--topic earnings` — but know it's an evergreen, not a trend.
- **Proof still rules the ad.** The trend is the *hook*; the ad still has to prove the
  product with a real market-beater (that's `nis-ad-image`'s proof stat). A timely
  hook + real proof is the combination that converts.
- **Run it weekly.** The brief is dated (`output/trends/<date>/`); regenerate each week so
  the ad angle stays current. Feed winners (by `nis-ad-launch reconcile`) back into which
  angle/topic framings you lean on.
- **Consistency with the site.** Because it reads the same views as `/articles`, the ad's
  trend claim will match what a visitor sees on the site — no contradictory numbers.
```
