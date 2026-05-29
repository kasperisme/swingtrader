# viral_reels — data-driven reel generator

Turns the **News Impact Screener** data foundation (plus external sources like
FMP price/OHLC) into short **vertical data-reels** in the style of
r/dataisbeautiful. A ~20-second reel should convey its entire point through the
animation alone.

Two formats (each a Remotion composition):

| Format | Composition | Answers |
|--------|-------------|---------|
| **Bar chart race** | `BarChartRace` | "Which viral area is winning over time?" — clusters / dimensions / tickers race by article volume, with optional price overlay + article cards. |
| **Price + News** | `PriceNewsChart` | "Did the news actually move the stock?" — an animated price line with scored news events plotted on it, each headline popping a sentiment-coloured pin + an article card showing the price reaction. |

Both formats share one **`ArticleCard`** design (thumbnail + uppercase source +
title + meta) and show the real article images. **No hook/takeaway text is
burned into the reel** — that's added afterwards in Instagram/edits; `intro`/
`outro` in a spec are ignored by the renderer.

Both open with a built-in **catch beat** (~1.5–3.7s): a punchy entrance plus a
spotlight pulse on the eventual hero (the winning bar / the live price edge) to
grab the viewer early — the rest plays at its natural pace.

## Who does what

```
┌─────────────┐   keyframes/overlay JSON   ┌──────────────┐   ReelSpec JSON   ┌──────────┐
│   Python    │ ─────────────────────────▶ │ Claude Code  │ ────────────────▶ │ Remotion │ ─▶ reel.mp4
│ (this pkg)  │                            │ (the skill = │                   │  (reel/) │
│ data only   │ ◀───── inspect ──────────  │  director)   │                   │  render  │
└─────────────┘                            └──────────────┘                   └──────────┘
```

- **Python** — deterministic data acquisition. Queries the news-impact daily
  views, builds time-bucketed race keyframes, fetches the FMP price overlay,
  and surfaces candidate "viral" stories. No creative decisions.
- **Claude Code** — the creative director (`viral-reel` skill). Picks the
  subject, frames the story, writes the title/captions/takeaway, assembles the
  final `ReelSpec`.
- **Remotion** (`reel/`) — renders the `ReelSpec` to a 1080×1920 MP4.

## The ReelSpec contract

`spec.py` (Python) and `reel/src/types.ts` (TypeScript) are two views of the
same JSON contract — **keep them in sync**. A spec carries the format, theme,
intro/outro copy, the race `keyframes`, an optional external `overlay`, and
timed `captions`. See `reel/samples/sample_spec.json` for a complete example.

Every keyframe must list the **same set of entity ids** (values carried
forward) — the renderer interpolates value *and* rank between keyframes for
smooth overtakes. `spec.validate()` enforces this.

## CLI

```bash
cd code/analytics

# 1. What's moving? Pick a subject.
python -m services.viral_reels.cli stories  --window-days 14
python -m services.viral_reels.cli snapshot --window-days 14

# 2. Build race keyframes for the subject
python -m services.viral_reels.cli series --kind cluster   --window-days 14
python -m services.viral_reels.cli series --kind dimension --top 8
python -m services.viral_reels.cli series --kind ticker    --top 8 --value-mode cumulative_articles

# 3. External overlay (FMP price/OHLC)
python -m services.viral_reels.cli prices --ticker NVDA --window-days 30

# 3b. Real headlines behind the trend (UI-styled article cards)
python -m services.viral_reels.cli headlines --window-days 14 --limit 5 \
    --dimension-key tariff_sensitivity

# 4. One-shot starter spec (director then edits copy + captions)
python -m services.viral_reels.cli scaffold --kind cluster --window-days 14 \
    --overlay-ticker NVDA --headlines 5 --out out/reel_spec.json

# 5. Validate + render (render infers the composition from the spec shape)
python -m services.viral_reels.cli validate out/reel_spec.json
python -m services.viral_reels.cli render   out/reel_spec.json --out out/reel.mp4
```

### Price + News format

```bash
# Scaffold a price line + scored news events for a ticker, then edit the copy
python -m services.viral_reels.cli price-news --ticker NVDA --window-days 30 \
    --max-events 5 --out out/price_news_spec.json
python -m services.viral_reels.cli render out/price_news_spec.json --out out/price_news.mp4
```

The price line draws left-to-right at a steady pace; dates run along the chart's
x-axis. Each news event pops a pin on the line (green = positive sentiment,
red = negative) and an article card that floats **over the graph** with the
headline, source, and the next-day price move — so it's obvious which headlines
moved the stock. `price-news` trims the empty pre-news run-up so the first
article lands on the **2nd rendered date** (on screen within ~2s).

`series`, marks of value:

| value mode | meaning | best for |
|---|---|---|
| `cumulative_articles` (default) | running sum of article volume | the race — monotonic growth with rank shuffles |
| `cumulative_attention` | running sum of `count × |weighted_avg|` | how much the news *cared* |
| `level` | raw daily weighted-average sentiment | sentiment swings (can go negative) |

## Rendering (Remotion)

```bash
cd code/analytics/services/viral_reels/reel
npm install                 # first time only (Remotion ships its own ffmpeg)
npm run studio              # interactive preview of the sample spec
npm run render:sample       # render the bundled sample to out/reel.mp4
```

Render an arbitrary spec. **The CLI `render` command is the supported path** —
it wraps the spec correctly. If you call Remotion directly, note that input
props must match the composition's prop shape `{"spec": <ReelSpec>}`, *not* a
bare ReelSpec (a bare spec silently loses to the default props during Remotion's
merge):

```bash
# wrap the bare ReelSpec first
node -e "const s=require('/abs/path/reel_spec.json');process.stdout.write(JSON.stringify({spec:s}))" > props.json
npx remotion render src/index.ts BarChartRace out/reel.mp4 --props=props.json
```

The composition reads `format` from the spec via `calculateMetadata`, so
duration/dimensions/fps are spec-driven.

## Environment

Reuses `code/analytics/.env`:

- `SUPABASE_URL`, `SUPABASE_KEY` — news-impact data
- `FMP_API_KEY` (or `APIKEY`) — price overlay

## Extending

- **New animation template** — add a composition under `reel/src/compositions/`,
  register it in `reel/src/Root.tsx`, and pass `--composition <id>` to render.
- **New external source** — add a builder to `data_sources.py` that returns an
  `overlay` dict, then teach `spec.build_spec`/the renderer about the new type.
- **New race subject** — add a builder to `SERIES_BUILDERS` in `data_sources.py`.
