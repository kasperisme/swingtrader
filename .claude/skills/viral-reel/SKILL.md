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
the most surprising, change-rich story, let the visualization tell it, **and
write the post caption** that frames it (step 5) — the hook and takeaway live in
the caption, not on the pixels.

Service: `code/analytics/services/viral_reels/` · Renderer: `.../viral_reels/reel/`
Read its `README.md` once before your first run.

## Two formats — pick the one that fits the story

- **Bar chart race** (`BarChartRace`) — "which viral area is winning over time?"
  Clusters / dimensions / tickers race by article volume. Default; the rest of
  this doc covers it.
- **Price + News** (`PriceNewsChart`) — "did the news actually move the stock?"
  An animated **OHLC candlestick** chart (green/red bodies + high-low wicks) with
  scored news events plotted on it (pins + callouts showing the next-day move).
  Use when the user names a ticker and wants to show news → price reaction.

  **You pick the events — don't ship the auto-selection.** The whole point is
  news → price *causation*: pick the headline that plausibly caused each notable
  move. So lead with the **price-aware catalyst view** — it ranks the biggest
  close-to-close moves and, for each, lists the articles published on the
  session that produced it (the news *just before* the move):

  ```bash
  python -m services.viral_reels.cli catalysts --ticker NVDA \
      --window-days 30 --top-moves 12 --per-move 6
  # → output/viral_reels/NVDA/data/catalysts.json (per-ticker; --out optional)
  ```
  Read `catalysts.json` and, for each notable drop/gain you want to feature,
  pick the candidate that best *explains* it — the bullish fundamental headline
  before a rip, the warning/de-risk headline before a drop. This is the
  directorial judgement the heuristic can't make: a big move on a near-neutral
  or off-topic headline is noise, and the loudest headline of a day is often not
  the catalyst (e.g. prefer "Buy Nvidia Ahead Of Trump-Xi Summit" over a
  tangential robot-deal headline that merely scored high). Aim for ~5 picks that
  **spread across the window** and tell an arc (setup → catalyst → reaction →
  resolution). `news-candidates` (one headline per day + advisory `impact`) is
  the complementary day-by-day view if you want the full pool.

  **Even coverage — an event every ≤3-4 chart ticks.** The whole window is the
  reel: the candles draw one-by-one at a steady pace, so any stretch
  with no event is dead air on screen. Whatever window you render, keep *all*
  the chart's points (don't trim the run-up — a 30-day reel shows the full 30
  days), and land an event at least every 3-4 trading-day **points** —
  including from the first point to the first event, and from the last event to
  the end. "Tick" = one price point = one trading day, so a 20-point chart needs
  ~5-6 well-spread events as a floor, not a cap. Filler is fine: when nothing
  big happened, plot the strongest available headline for that stretch (a
  "Buy/Hold ahead of earnings" take, an analyst note) just to keep the line
  populated — the catalysts still carry the story. To colour pins, mix the
  internal `news-candidates` events (they carry AI `sentiment`) in with the FMP
  catalyst headlines. `validate` and `render` print non-fatal `coverage:`
  warnings for any gap over 4 ticks — clear them before shipping. And **don't**
  call `align_first_event_to_second_point` here — it trims the opening run-up,
  which fights "show the whole window" (it's only for the auto `price-news`
  quick draft).

  **Thin internal coverage? Pull from FMP too.** The internal feed is sparse for
  some tickers (you'll see only a handful of days with news). Two extra sources
  widen it — both emit events in the same shape as `news-candidates`, with the
  next-day price `move` annotated:

  ```bash
  # FMP stock news — broad third-party coverage, always an article image.
  # Internal AI sentiment is recovered by url match where the article exists in
  # our DB (else the pin is neutral amber).
  python -m services.viral_reels.cli fmp-news --ticker SNOW --window-days 30
  # FMP company press releases — the company's OWN catalysts at their exact
  # timestamp. Best for anchoring a move to its true cause: a third-party
  # write-up of earnings often lands a day late, but "COMPANY REPORTS Q1
  # RESULTS" is dated the session that actually moved the stock.
  python -m services.viral_reels.cli fmp-press --ticker SNOW --window-days 45
  # → output/viral_reels/SNOW/data/{fmp_news,fmp_press}.json
  ```
  Use press releases to fix attribution (e.g. SNOW's earnings press release is
  dated the day *before* the +36% gap, where the news article was dated the day
  *after*). Caveats: the press-release feed is noisy — law-firm "class action /
  deadline alert" spam dominates many days; pick the real catalysts (earnings,
  guidance, M&A, product). Press-release titles are often ALL-CAPS and have no
  image — tidy the `title` and expect the card's fallback thumbnail. FMP events
  carry no sentiment unless url-matched, so their pins read neutral; mix in
  internal `catalysts`/`news-candidates` events when you want the green/red
  sentiment colour. You can freely combine events from all sources in one
  `chart["events"]` list — just keep each event's fields verbatim and sort by
  `t` before building.

  Build the spec from your chosen articles — sourced from the catalyst view so
  the move and the headline are aligned (preserve each field verbatim; never
  invent titles, moves, or prices):

  ```python
  from services.viral_reels import data_sources as ds, spec as spec_mod
  chart = ds.price_history("NVDA", window_days=30)
  cats  = ds.move_catalysts("NVDA", window_days=30, points=chart["points"],
                            top_moves=40, per_move=10)
  by_from = {m["from"]: m for m in cats}
  # (move-day, substring of the catalyst headline you picked for that move)
  picks = [("2026-05-05", "Cash Generation Soars"),
           ("2026-05-14", "Strong Setup Ahead Of Earnings"), ...]
  events = []
  for day, needle in picks:
      m = by_from[day]
      hit = next(c for c in m["candidates"] if needle.lower() in c["title"].lower())
      events.append({**hit, "move": f'{m["pct"]:+.1f}% next day'})  # align move to headline
  events.sort(key=lambda e: e["t"])
  chart["events"] = events
  chart = ds.align_first_event_to_second_point(chart, lead=1)
  spec = spec_mod.build_price_news_spec(chart=chart, theme="midnight",
      title="<ignored>", subtitle="Price vs. AI-scored headlines · last 30 days",
      outro_title="<ignored>", outro_takeaway="<ignored>")
  import json; json.dump(spec, open("output/viral_reels/NVDA/spec.json", "w"), indent=2)
  ```
  Then `render` it — the mp4 lands next to the spec:
  ```bash
  python -m services.viral_reels.cli render output/viral_reels/NVDA/spec.json
  # → output/viral_reels/NVDA/reel.mp4
  ```

  `price-news` (the one-shot scaffold) still exists and auto-selects a
  distributed-by-impact set — fine for a quick draft, but treat its output as a
  starting point to re-curate, not the final cut. Either way the data layer
  fills `chart.points` and each event's sentiment/move/`imageUrl`. No on-reel
  hook/takeaway text; add it in IG.

  **Longer reels — go intraday.** A daily chart over a short window has too few
  candles to stretch past ~20s. To make a much longer reel (e.g. to run under a
  voice-over), pull an **intraday** interval so there are many more points to
  draw smoothly, and set the total length explicitly:

  ```bash
  # hourly bars over 7 days (~35 points), stretched to a fixed length…
  python -m services.viral_reels.cli price-news --ticker MSFT --window-days 7 \
      --interval 1hour --duration 60
  # …or auto-match the length to a voice-over file (a Nami×Luffy dialog.mp3):
  python -m services.viral_reels.cli price-news --ticker MSFT --window-days 7 \
      --interval 1hour --match-audio output/viral_reels/MSFT/dialog/dialog.mp3
  ```
  `--interval` accepts `daily` (default) or FMP intraday intervals (`1min`,
  `5min`, `15min`, `30min`, `1hour`, `4hour`). Intraday points carry a full ISO
  `t` and events are snapped to a mid-session point of their day. `--duration`
  sets the reel length in seconds; `--match-audio` reads it off any audio/video
  file (ffprobe). Internal news is ~1/day, so expect non-fatal `coverage:` gap
  warnings on an hourly chart (7-hour gaps between daily events) — fine when the
  reel is a backing visual; widen with FMP events if you want denser pins.

## Nami × Luffy news dialogue (voiced audio)

A spin-off deliverable: a short, **voiced** comedy dialogue where One Piece's
money-obsessed navigator **Nami** breaks the day's market-moving headlines down
for the carefree captain **Luffy**. Nami is the analyst (she loves treasure →
loves a good trade); Luffy reacts and asks the dumb-smart questions. Great as an
audio hook over a reel, or a standalone short.

Two stages mirror the rest of the service: **Claude writes the script**
(Anthropic, grounded in real headlines pulled from the data layer), then
**ElevenLabs voices each turn** and ffmpeg stitches them into one MP3.

```bash
# ticker-focused (pulls that ticker's strongest recent headlines + sentiment/move)
python -m services.viral_reels.cli dialog --ticker NVDA --window-days 7 --turns 8
# market-wide (trend snapshot + top headlines) — omit --ticker
python -m services.viral_reels.cli dialog --window-days 7
# script only, no API spend on voice:
python -m services.viral_reels.cli dialog --ticker NVDA --no-render
# → output/viral_reels/<TICKER>/dialog/{dialog_script.json, dialog.mp3}
#   (market-wide → output/viral_reels/dialog/)
```

Flags: `--turns N` (approx turn count), `--direction "<extra creative note>"`,
`--model <anthropic model>`, `--no-render` (script only), `--out-dir <dir>`.

Voices (canonical One Piece fan voices, override via env):
`ELEVENLABS_LUFFY_VOICE_ID=UnDWNGYfYVHrYbgQXZOS`,
`ELEVENLABS_NAMI_VOICE_ID=uzAAg0A7FBedb5sTJjXA`. Needs `ANTHROPIC_API_KEY` +
`ELEVENLABS_API_KEY` in `code/analytics/.env`, plus ffmpeg on PATH. Implemented
in `services/viral_reels/dialog.py`. The script grounds the banter in the real
tickers/moves from the news pull — never invents a price; review
`dialog_script.json` and re-run (tweak `--direction`/`--turns`) if a beat is off.
The first line **always opens with "Stop" or "Wait"** (a scroll-stopper hook),
enforced in both the prompt and a code safety net.

**Pair the dialog with a reel (voiced price-news video).** Generate the dialog,
build a length-matched **intraday** price-news reel for the same ticker, then mux
the audio onto the render so the Nami×Luffy banter plays over the moving chart:

```bash
python -m services.viral_reels.cli dialog --ticker MSFT --window-days 7 --turns 8
python -m services.viral_reels.cli price-news --ticker MSFT --window-days 7 \
    --interval 1hour --match-audio output/viral_reels/MSFT/dialog/dialog.mp3
python -m services.viral_reels.cli render output/viral_reels/MSFT/spec.json \
    --audio output/viral_reels/MSFT/dialog/dialog.mp3
# → reel.mp4 (silent) + reel_audio.mp4 (dialog muxed in)
```
`render --audio <file>` muxes any audio track onto the rendered reel (copies
video, encodes AAC, `-shortest`) and writes a sibling `*_audio.mp4`.

### `dialog-reel` — event-synced voice-over (the connected version)

`dialog` + `price-news` above only *length*-match; the talk doesn't track the
chart. **`dialog-reel`** ties them together so Nami comments on each plotted
headline **exactly as its card slides onto the chart**:

```bash
python -m services.viral_reels.cli dialog-reel --ticker MSFT \
    --window-days 35 --interval 1hour --max-events 6
# → spec.json (with a draw schedule), dialog/dialog.mp3, reel.mp4, reel_audio.mp4
```

How it works:
- Pulls the intraday chart + the news events it plots, then writes a script as a
  **hook + one beat per event + outro**, each beat naming that headline and its
  real move/sentiment (never invents numbers).
- Voices the beats back-to-back (no dead air) and emits a variable-speed **draw
  schedule** (`chart.keyframes`: `{t, idx}`) so the candle line reaches each
  event's bar at the exact second its beat starts. The renderer draws faster
  through quiet stretches and slows where events cluster.
- The reel length equals the spoken length; video and audio stay locked.

The first line still opens with **"Stop"/"Wait"**. Flags: `--max-events` (pins to
feature), `--target-seconds` (budgets beat length; final length = the spoken
length), `--window-days`/`--interval` (chart breadth & candle pace), `--direction`,
`--theme`, `--no-render` (writes spec + audio, prints the finishing `render`
command), `--model`. The `chart.keyframes` schedule is what makes the sync work —
keep it when hand-editing the spec; drop it and the draw reverts to constant
speed. Inspect `dialog/dialog_script.json` → `schedule` to see each beat's start
vs. its pin time (they should match).

## Cover / poster image (the standard way — don't hand-roll one)

When you need a still **cover/thumbnail** for the reel (IG feed poster, CEO/hero
shot), use the built-in `card` command — it scaffolds a `StockCard` poster
(1080×1350) and **auto-fetches** the company profile, FMP stats (price/Δ/mktcap/PE),
the internal Impact badge, any NIS screening the ticker is in, and a
Wikipedia/Commons **CEO portrait**:

```bash
python -m services.viral_reels.cli card --ticker SNDK --window-days 65 \
    --headline "Every green candle had a headline." --tag "+115% in 9 weeks"
# → output/viral_reels/SNDK/card.json   (edit headline/tag/badge/heroImageUrl)
python -m services.viral_reels.cli render output/viral_reels/SNDK/card.json \
    --out output/viral_reels/SNDK/card.png   # card specs render as a single PNG
```

Flags: `--headline`, `--tag`, `--hero-image-url <url>`, `--no-ceo-photo`,
`--no-nis`, `--theme`. The CEO photo auto-fetch misses for some execs (sets
`heroImageUrl: null`) — then pass `--hero-image-url <URL>`, or set
`card.heroImageUrl` in the JSON. `StockCard` renders it via `<Img>`, so it needs
a **real URL** (remote, or a `data:image/...;base64,` URL for a local file — a
bare `public/` path 404s). Do **not** build a new Remotion composition for
covers; `StockCard` already is the cover generator.

### Output layout
Everything for one reel lives in a **per-project folder** — never a flat dump:

```
output/viral_reels/
  <TICKER>/                 # one folder per price+news reel (e.g. NVDA/, SNOW/)
    data/                   # raw source pulls the director reads
      catalysts.json  candidates.json  fmp_news.json  fmp_press.json  overlay.json
    spec.json               # the assembled ReelSpec you build
    reel.mp4                # the render (defaults next to its spec)
    caption.md              # the post caption you write (step 5)
  race/                     # bar-chart-race reels (not ticker-scoped)
    reel_spec.json  reel.mp4  caption.md
```

The CLI defaults every artifact into this tree (ticker commands → `<TICKER>/…`,
`render` → next to the spec), so `--out` is optional. Keep new reels inside
their own `<TICKER>/` (or `race/<subject>/`) folder — don't write loose files
into `output/viral_reels/` directly.

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
python -m services.viral_reels.cli series --kind cluster --window-days 14 --out output/viral_reels/series.json
python -m services.viral_reels.cli prices --ticker NVDA --window-days 30 --out output/viral_reels/overlay.json
# real headlines behind the trend (UI-styled article cards, with source)
python -m services.viral_reels.cli headlines --window-days 14 --limit 5 \
    --dimension-key tariff_sensitivity --out output/viral_reels/headlines.json
```

Or scaffold a starter spec in one shot, then edit it:

```bash
python -m services.viral_reels.cli scaffold --kind cluster --window-days 14 \
    --overlay-ticker NVDA --headlines 5 --out output/viral_reels/reel_spec.json
```

### 3. Direct the reel — edit `output/viral_reels/reel_spec.json`
This is the creative work. Open the spec and fill in the human parts (the data
parts are already populated). The full contract is in
`services/viral_reels/spec.py` and `reel/src/types.ts`.

**No editorial text is burned into the reel** — no hero/title slide and no
takeaway slide. The hook and takeaway are added afterwards in Instagram / edits.
The reel is pure visualization: the animated chart, data labels (metric/date or
ticker/price) and the article cards. So `intro`/`outro`
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
python -m services.viral_reels.cli validate output/viral_reels/reel_spec.json
python -m services.viral_reels.cli render   output/viral_reels/reel_spec.json --out output/viral_reels/reel.mp4
```
First render only: `cd services/viral_reels/reel && npm install`.

### 5. Write the reel caption
The reel ships with **no on-screen words**, so the post caption carries the hook,
the story, and the takeaway. Always produce one as the final deliverable and save
it next to the reel:

`output/viral_reels/<TICKER>/caption.md`  (race reels → `race/<subject>/caption.md`)

Structure — caveman-tight, written assuming the viewer only reads line 1:
- **Hook** — line 1, ≤125 chars (IG/TikTok truncate there). The single most
  surprising thing the reel shows; lead with the number/turn, not the setup.
- **The arc** — 2–4 short lines walking the story the animation tells
  (setup → catalyst → reaction → resolution); one news→price beat per line.
- **Takeaway** — the so-what: actionable and slightly contrarian (brand voice).
- **CTA** — point at the product, e.g. `Scored headlines → newsimpactscreener.com`.
- **Hashtags** — 5–10, broad + niche, and the **cashtag** (`$TER`) since IG/X
  index it: `#swingtrading #stockmarket $TER #Teradyne #AItrading …`.
- **Disclaimer** — one line: `Not financial advice.` (finance content needs it.)

Rules: every number/date/ticker **verbatim from the spec** — never invent a price
or move the reel doesn't show; active voice, no hedging; emoji sparingly (1–3, to
mark beats, not decorate); keep the whole thing skimmable on a phone. Match the
caption's beats to what's actually on screen so a viewer reading while watching
sees them line up.

Then surface **both** the MP4 and the caption to the user (use SendUserFile for
the video) and summarize the story.

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
