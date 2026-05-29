# viral_reels — data-driven reel generator

Turns the **News Impact Screener** data foundation (plus external sources like
FMP price/OHLC) into short **vertical bar-chart-race reels** in the style of
r/dataisbeautiful. A ~20-second reel should convey its entire point through the
animation alone — the bars race, overtake, and resolve into a takeaway.

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

# 4. One-shot starter spec (director then edits copy + captions)
python -m services.viral_reels.cli scaffold --kind cluster --window-days 14 \
    --overlay-ticker NVDA --out out/reel_spec.json

# 5. Validate + render
python -m services.viral_reels.cli validate out/reel_spec.json
python -m services.viral_reels.cli render   out/reel_spec.json --out out/reel.mp4
```

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

Render an arbitrary spec:

```bash
npx remotion render src/index.ts BarChartRace out/reel.mp4 --props=/abs/path/reel_spec.json
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
