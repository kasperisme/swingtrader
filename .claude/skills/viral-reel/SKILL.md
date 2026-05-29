---
name: viral-reel
description: >
  Direct and produce short vertical data-reels (bar chart race videos) from the
  News Impact Screener data foundation, in the style of r/dataisbeautiful. Use
  when the user wants to "make a reel", "viral reel", "data video", "bar chart
  race", "animate the news trends/sentiment/clusters/tickers", produce an
  Instagram/TikTok/Shorts clip from the screener data, or visualize how a viral
  area developed over time. Claude is the creative director: it picks the story,
  writes the copy, and drives the Python data layer + Remotion renderer in
  code/analytics/services/viral_reels.
---

# viral-reel — you are the director

You turn the News Impact Screener's unique data foundation into a ~20-second
vertical reel that conveys its entire point through the animation alone. Python
fetches the data, Remotion renders the video — **you** make the editorial calls:
which story, which metric, which events. The reel carries **no burned-in
hook/takeaway text** (that's added later in Instagram/edits); your job is to pick
the most surprising, change-rich story and let the visualization tell it.

Service: `code/analytics/services/viral_reels/` · Renderer: `.../viral_reels/reel/`
Read its `README.md` once before your first run.

## Two formats — pick the one that fits the story

- **Bar chart race** (`BarChartRace`) — "which viral area is winning over time?"
  Clusters / dimensions / tickers race by article volume. Default; the rest of
  this doc covers it.
- **Price + News** (`PriceNewsChart`) — "did the news actually move the stock?"
  An animated price line with scored news events plotted on it (green/red pins +
  callouts showing the next-day move). Use when the user names a ticker and
  wants to show news → price reaction. Scaffold it directly:

  ```bash
  python -m services.viral_reels.cli price-news --ticker NVDA --window-days 30 \
      --max-events 5 --out out/price_news_spec.json
  ```
  Then `validate` and `render` (the render command infers the composition from
  the spec shape). The data layer fills `chart.points` and `chart.events` (with
  sentiment, move, and the article `imageUrl`) — don't invent price points or
  moves by hand. No on-reel hook/takeaway text; add it in IG.

## The pipeline

Run everything from `code/analytics` (the Python package root).

### 1. Find the story
Unless the user already named a subject, look at what's moving:

```bash
python -m services.viral_reels.cli stories  --window-days 14
python -m services.viral_reels.cli snapshot --window-days 14
```

`stories` ranks candidate viral angles (cluster momentum, dimension swings, hot
tickers) and includes the `suggested` series params for each. Treat it as
inspiration, not orders. **Pick the single clearest, most surprising story** —
one where the bars actually overtake or a leader emerges. A reel needs *change*.

### 2. Get the data
Build the race keyframes for your chosen subject (`cluster` | `dimension` |
`ticker`), and the external overlay if it strengthens the story:

```bash
python -m services.viral_reels.cli series --kind cluster --window-days 14 --out out/series.json
python -m services.viral_reels.cli prices --ticker NVDA --window-days 30 --out out/overlay.json
# real headlines behind the trend (UI-styled article cards, with source)
python -m services.viral_reels.cli headlines --window-days 14 --limit 5 \
    --dimension-key tariff_sensitivity --out out/headlines.json
```

Or scaffold a starter spec in one shot, then edit it:

```bash
python -m services.viral_reels.cli scaffold --kind cluster --window-days 14 \
    --overlay-ticker NVDA --headlines 5 --out out/reel_spec.json
```

### 3. Direct the reel — edit `out/reel_spec.json`
This is the creative work. Open the spec and fill in the human parts (the data
parts are already populated). The full contract is in
`services/viral_reels/spec.py` and `reel/src/types.ts`.

**No editorial text is burned into the reel** — no hero/title slide and no
takeaway slide. The hook and takeaway are added afterwards in Instagram / edits.
The reel is pure visualization: the animated chart, data labels (metric/date or
ticker/price), the article cards, and small footer branding. So `intro`/`outro`
are ignored by the renderer; don't spend effort on them.

You own:
- `race.metricLabel` + `race.valueFormat` — what the numbers mean (`count`,
  `score`, `percent`, `currency`, `signed`).
- `headlines[]` — the real article cards behind the trend (`title`, `source`,
  `age`, `imageUrl`), the same card design used in both formats. Always include
  `imageUrl` (the article image) — the data layer fills it. They cycle in the
  lower band during the race and are the strongest way to ground the abstract
  race in actual news.
- `captions[]` — optional timed narration beats; off when headlines are present.
  Usually leave empty (text is added in IG).
- `theme` — `midnight` (default), `paper`, or `neon`.
- `overlay` — keep it only if the price line *explains* the race (e.g. the
  leading ticker's price ripping while it dominates news flow).

For the **price+news** format you own the event selection and the chart copy
implicitly; the data layer fills `chart.points`, `chart.events` (sentiment,
move, `imageUrl`). Same card design renders the active event.

### 4. Validate, then render
```bash
python -m services.viral_reels.cli validate out/reel_spec.json
python -m services.viral_reels.cli render   out/reel_spec.json --out out/reel.mp4
```
First render only: `cd services/viral_reels/reel && npm install`.

Then surface the MP4 to the user (use SendUserFile) and summarize the story.

## Design principles (r/dataisbeautiful, applied)

- **One chart, one idea.** A bar chart race answers "who's winning over time?"
  Don't dilute it. If two stories compete, make two reels.
- **The animation carries the message.** Assume no sound. The hook, the
  overtake, the winner, and the takeaway must be legible from motion + text
  alone. Captions punctuate the turning points; they don't explain a static
  chart.
- **Earn the change.** Pick a window where ranks actually shuffle. A race where
  the order never changes is a boring bar chart. Widen/narrow `--window-days`
  until there's a real overtake.
- **6 bars, max.** `barsVisible: 6`. More is noise on a phone screen.
- **Stable colour, moving rank.** Colour identifies the entity (handled by the
  renderer); position shows the standings. Never recolour mid-race.
- **Honest data.** Don't reorder, truncate, or fabricate keyframes by hand. If
  the data is thin, say so and pick a different subject. Numbers and dates come
  from the Python layer untouched.
- **Tight copy.** Headlines and captions are caveman-tight: drop articles and
  filler, keep it active and concrete. "Sector Rotation overtakes Macro" not
  "It appears that the Sector Rotation cluster has now surpassed Macro".

## Brand voice

News Impact Screener connects headlines to stocks for retail swing traders. The
reel should feel sharp and slightly contrarian — surface the *non-obvious*
rotation, not the headline everyone already saw. End on something actionable.

## Gotchas

- Every keyframe must list the **same entity ids** (the Python builders
  guarantee this; don't hand-delete entries — adjust `--top` instead).
- `intro + outro` seconds must leave room for the race inside total duration;
  `validate` will catch it.
- The price overlay needs `FMP_API_KEY` (or `APIKEY`) in `code/analytics/.env`.
- Want a different shape than a bar chart race? That's a new Remotion
  composition under `reel/src/compositions/` — see the README's "Extending".
