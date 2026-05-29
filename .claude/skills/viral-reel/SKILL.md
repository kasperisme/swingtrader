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
vertical **bar chart race** reel that conveys its entire point through the
animation alone. Python fetches the data, Remotion renders the video — **you**
make every creative decision in between: what story to tell, which metric races,
the hook, the captions, and the takeaway.

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
  Then edit the copy (intro hook, outro takeaway), `validate`, and `render` (the
  render command infers the composition from the spec shape). You own the same
  creative calls: the hook, which events matter, and the so-what takeaway. The
  data layer fills `chart.points` and `chart.events` (with sentiment + move) —
  don't invent price points or moves by hand.

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

You own:
- `intro.title` — the **hook** (≤7 words). A question or a claim, not a label.
  There is no hero slide: the hook renders as a text caption overlaid on the
  start of the animation, then fades — so the chart gets the full runtime.
  `intro.durationInSeconds` controls how long the caption holds before fading.
- `intro.kicker` / `intro.subtitle` — brand + what/when (e.g. "AI-scored news impact · last 14 days").
- `race.metricLabel` + `race.valueFormat` — what the numbers mean (`count`,
  `score`, `percent`, `currency`, `signed`).
- `captions[]` — 2–4 timed beats (`atSeconds`, `text`) narrating the overtakes
  so the video reads silently. Land them on the moments where ranks change.
- `headlines[]` — the real article cards behind the trend (`title`, `source`,
  `age`, optional `imageUrl`), styled like the app's news feed. They cycle in
  the lower band during the race and **take precedence over captions** (don't
  set both — use headlines for evidence, captions for narration). This is the
  strongest way to ground the abstract race in actual news.
- `outro.title` + `outro.takeaway` — the **so-what**. What should a trader do
  with this? One line.
- `theme` — `midnight` (default), `paper`, or `neon`.
- `overlay` — keep it only if the price line *explains* the race (e.g. the
  leading ticker's price ripping while it dominates news flow).

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
