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
# Outputs are organised per project under code/analytics/output/viral_reels/
# (so --out is optional — see "Output layout" below):
#   <TICKER>/data/*.json  raw pulls   <TICKER>/spec.json   <TICKER>/reel.mp4
#   race/                 bar-chart-race reels

# 1. What's moving? Pick a subject.
python -m services.viral_reels.cli stories  --window-days 14
python -m services.viral_reels.cli snapshot --window-days 14

# 2. Build race keyframes for the subject
python -m services.viral_reels.cli series --kind cluster   --window-days 21
python -m services.viral_reels.cli series --kind dimension --top 8 --window-days 21
python -m services.viral_reels.cli series --kind ticker    --top 8 --value-mode cumulative_articles

# 3. External overlay (FMP price/OHLC)
python -m services.viral_reels.cli prices --ticker NVDA --window-days 45

# 3b. Real headlines behind the trend (UI-styled article cards)
python -m services.viral_reels.cli headlines --window-days 21 --limit 8 \
    --dimension-key tariff_sensitivity

# 4. One-shot starter spec (director then edits copy + captions)
python -m services.viral_reels.cli scaffold --kind cluster --window-days 21 \
    --overlay-ticker NVDA --headlines 5          # → output/viral_reels/race/reel_spec.json

# 5. Validate + render (render infers the composition from the spec shape)
python -m services.viral_reels.cli validate output/viral_reels/race/reel_spec.json
python -m services.viral_reels.cli render   output/viral_reels/race/reel_spec.json
# → output/viral_reels/race/reel.mp4 (render defaults next to the spec)
```

### Price + News format

```bash
# Price-aware director input: biggest moves, each with the headlines that
# could explain it (news just *before* the move) — pick the catalyst per move
python -m services.viral_reels.cli catalysts --ticker NVDA --window-days 30 \
    --top-moves 12 --per-move 6                  # → output/viral_reels/NVDA/data/catalysts.json
# Or the full day-by-day pool (one headline per day + advisory impact score)
python -m services.viral_reels.cli news-candidates --ticker NVDA --window-days 30

# Widen thin internal coverage with FMP (events in the same shape):
#   stock news — broad third-party coverage + article images (sentiment
#   recovered by url match where the article is in our DB, else neutral)
python -m services.viral_reels.cli fmp-news --ticker SNOW --window-days 30
#   press releases — the company's own catalysts at exact timing (best for
#   anchoring a move to its true cause when third-party write-ups lag a day)
python -m services.viral_reels.cli fmp-press --ticker SNOW --window-days 45
#   → output/viral_reels/SNOW/data/{fmp_news,fmp_press}.json

# One-shot scaffold (auto-selects events; treat as a draft to re-curate)
python -m services.viral_reels.cli price-news --ticker NVDA --window-days 45 --max-events 8
python -m services.viral_reels.cli render output/viral_reels/NVDA/spec.json
# → spec at output/viral_reels/NVDA/spec.json, render at output/viral_reels/NVDA/reel.mp4
```

The director (Claude Code) is expected to choose the events: `catalysts`/
`news-candidates` surface the data, then Claude picks the headline that best
*explains* each move and builds the spec from those articles (see the
`viral-reel` skill for the build snippet). `price-news` only provides a
heuristic default.

### Output layout

Each reel is a **per-project folder** under `output/viral_reels/`, not a flat
dump:

```
output/viral_reels/
  <TICKER>/                 # one folder per price+news reel (NVDA/, SNOW/, …)
    data/                   # raw source pulls (catalysts, candidates, fmp_news, fmp_press, overlay)
    spec.json               # the assembled ReelSpec
    reel.mp4                # the render (defaults next to its spec)
  race/                     # bar-chart-race reels (not ticker-scoped)
    reel_spec.json  reel.mp4
```

Ticker commands default their `--out` into `<TICKER>/data/`, `price-news` writes
`<TICKER>/spec.json`, and `render` writes the mp4 next to the spec — so `--out`
is optional and outputs stay organised.

The price line draws left-to-right at a steady pace; **both axes grow with the
reveal** — the x-axis expands (earlier points compress left) and the y-range is
the running min/max of the data shown so far, so the viewer can't see the whole
range up front and it expands as new highs/lows arrive. Dates run along the
chart's x-axis; price gridline values sit on the left, and the **live price tag
on the right edge (ticker + price + %Δ) follows the leading point up/down**
(green/red by direction) — there is no top header, so the article card gets the
extra space. Each news event pops a pin on the line (green = positive sentiment,
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
