---
name: nis-arena-report
description: >-
  Produce the Arena's weekly broadcast package — a still league TABLE (4:5 / 9:16 / 1:1)
  and the season RACE reel (9:16) showing nine AI paper-trading agents competing, reported
  in the grammar of a sports results round-up: position, movement chevrons, a W/L form
  guide, promotion and relegation bands, and one strap line carrying the story. Reads the
  live arena public views, detects the storyline deterministically (a control leading, the
  coinflip beating LLMs, a freefall, a climber), renders via Remotion, and hands off to
  social_publishing for organic posting or nis-ad-image/nis-ad-launch for paid. Use when
  the user wants to "post the arena", "the arena table/standings graphic", "the league
  table", "the season race", "show how the arena is unfolding", or a weekly/matchday
  arena update. NOT a stock setup (nis-stock-breakdown) and NOT a news trend ad
  (nis-trend-radar).
---

# NIS Arena Report

The Arena's weekly package. Nine agents, $100,000 each, one market — reported the way
sport reports a league, because sport has spent sixty years solving exactly this problem:
how to make a slow-moving numeric contest feel urgent every single week.

**Two assets, one graphic.** The still table and the race reel share row shapes, club
colours and chrome on purpose. A package only reads as a package if the video is visibly
the same graphic as the still.

## The one thing to get right

**Publish the unflattering story.** The detectors will regularly hand you "a control is
winning" or "a random number generator is beating three of our AIs". That is the hook.
It is the most credible thing this project can say, competitors structurally cannot copy
it, and softening it into "our AI agents are learning fast" throws away the only asset the
board actually has. If a storyline is true, it ships.

## The workflow

### Step 1 — Read the table and the story

```bash
cd code/analytics
.venv/bin/python -m services.arena_creatives.cli standings
.venv/bin/python -m services.arena_creatives.cli storylines
```

`storylines` returns every hook the table currently supports, best first, each with a
ready-written `headline` and a `detail` that is literally true against the numbers.
Detector keys: `control_leads`, `coinflip_beats_llms`, `freefall`, `no_wins`, `best_llm`,
`climber`, `faller`, `streak`, `tight`.

Take the top one unless you have a reason. Pin a different angle with `--story <key>`.

### Step 2 — Render the package

```bash
.venv/bin/python -m services.arena_creatives.cli package
```

Writes `output/arena/<season>/<as-of date>/`:

```
standings.json          the table with movement + form
storylines.json         every hook, best first
table/spec.<ratio>.json + table/<ratio>/table.png    (4x5, 9x16, 1x1)
race/spec.json          + race/race.mp4              (9:16, ~22s)
```

Useful flags: `--ratios 4x5,9x16` · `--hook "your own strap"` · `--story <key>` ·
`--duration 26` · `--lookback 5` (sessions behind the ▲▼ chevron) · `--no-render` to
inspect a spec first. Edit a spec by hand, then
`cli render <spec.json>` to re-render just that one.

### Step 2b — Commentary and music (optional, but it is what makes it a broadcast)

```bash
.venv/bin/python -m services.arena_creatives.cli commentary            # the beat sheet
.venv/bin/python -m services.arena_creatives.cli race --voice --music  # voiced + scored
```

**A beat is a thing that happened, the session it happened on, and the second of
the reel that session is on screen.** The commentary is frame-locked: "the coinflip
takes the lead" is spoken while that bar is actually moving. Beats are detected,
never invented — `open`, `premise` (what the experiment varies), `lead:<agent>@<session>`,
`bottom:<agent>@<session>` (the worst book at its lowest), `field@<session>` (how many
of the nine are under water), and `result`.

Watch **speech coverage** in the beat sheet. Below ~70% the reel plays as a silent
chart somebody occasionally comments on; ~80% is the target, with air left for the
bed between lines. If it reads thin, raise `--max-beats` or shorten `--duration`.

Two voices, in `commentary.py`: `commentator` (default — faster, play-by-play) and
`broadcaster` (steadier, studio). Select with `ARENA_COMMENTARY_VOICE`. Each carries
a **measured** words-per-second rate, because that is what decides how many words a
slot holds — 2.4 against 2.0 is a whole clause. Measure a new voice before making it
a default; `ARENA_COMMENTARY_VOICE_ID` overrides the id but keeps the old rate and
warns.

Read the beat sheet before rendering. It shows each line, its second, and how many
**spoken** words the slot holds (numbers are expensive: "plus 2.89%" is two written
words and about six spoken ones). Then sharpen the words:

```bash
cat > $RUN/race/script.json <<'JSON'
{ "open": "Nine A.I. agents. One hundred thousand dollars each.",
  "lead:burton-malarkey@9": "July fifteenth. The random number generator goes top.",
  "result": "Nobody beat doing nothing." }
JSON
.venv/bin/python -m services.arena_creatives.cli race --voice --music --script $RUN/race/script.json
```

Keys come from the beat sheet and must match a detected beat — the words are yours,
the events are not. Re-run `commentary --script ...` to check your lines fit their
slots before spending a render.

Writing the lines:
- **Short.** A slot holds 7–12 spoken words. Clipped is the register anyway.
- **The commentator says the scoreline; the graphic says the story.** Don't try to
  fit the full strap into the closing beat — it is already on screen behind it.
- **Say what the picture is doing**, not what the viewer should feel.
- Spell numbers the way they are said, or keep them out of the line.

`--voice` defaults the reel to 32s (a steady broadcast read needs the room) and turns
captions on, because most social video is watched muted — the beats are burned in as
well as spoken. `--music` alone gives a scored silent race. Output is
`race_audio.mp4` **next to** the silent `race.mp4`; the silent render is kept so
rewriting a line does not mean re-rendering 960 frames.

### Step 3 — Write the caption (this is the creative act)

The CLI deliberately does **not** write `caption.txt`. The numbers are deterministic; the
words are not. Write it to `output/arena/<season>/<date>/caption.txt`.

**The register.** Match-report voice: present tense, short declaratives, the number early,
no hedging and no hype. A results round-up does not sell — it reports, and the reporting is
what makes it credible.

Structure that works:

```
Line 1   The strap, verbatim or sharpened. One fact, no wind-up.
Line 2   The number that proves it.
Line 3-5 The two or three other things that moved. Names, positions, numbers.
Line 6   Why anyone should care — what varies between these agents.
Line 7   Where to watch it. newsimpactscreener.com/arena
Footer   Paper trading. Not investment advice.
```

Do:
- Name agents by name and give the position: "Michael Beary is up four places to 3rd."
- Use table points: 1 point ≈ $1,000. Say it once, it sticks.
- Let the controls be the joke and the proof at the same time.
- Explain the experiment in one clause: every agent gets the same model, broker, risk
  limits and universe — only the **slice of data it can see** differs.

Do not:
- Imply a paper result is an achievable return, or project one forward.
- Call a lead "proof" that a strategy works. 47 sessions is not evidence.
- Editorialise about a real investor. The names are affectionate parodies of a public
  *approach*; nothing implies affiliation or endorsement.
- Drop the disclaimer. It is burned into every render — keep it in the caption too.

### Step 4 — Publish

Organic, through the existing publisher's ad-hoc mode (no per-ticker folder needed):

```bash
RUN=output/arena/season-1/2026-09-04
.venv/bin/python -m services.social_publishing.cli publish --ticker ARENA \
    --media $RUN/race/race_audio.mp4 --caption-file $RUN/caption.txt \
    --platforms instagram,tiktok --dry-run
```

Post `race_audio.mp4` when it exists — a silent reel is autoplayed muted and then
gets no reward for the viewer who unmutes.

The still table is image-only, so drop TikTok for it (TikTok is video-only and the CLI
will refuse):

```bash
.venv/bin/python -m services.social_publishing.cli publish --ticker ARENA \
    --media $RUN/table/4x5/table.png --caption-file $RUN/caption.txt \
    --platforms instagram,facebook,linkedin
```

Paid: hand the 1:1 table (or a purpose-built creative) to `nis-ad-image` →
`nis-ad-launch`, tagging `utm_content=arena_table` / `arena_race` / `arena_upset` so
`meta_ads design` can later tell you which broadcast format actually converts.

## The sports grammar, and what maps to what

| Broadcast device | Arena equivalent | Where it comes from |
|---|---|---|
| League table, promotion/relegation bands | the leaderboard, top-3 green / bottom-2 red | `arena_leaderboard_v` |
| Points | % return (1 pt ≈ $1,000) | `total_return` |
| Goal difference | max drawdown | `max_drawdown` |
| Form guide `W L W W L` | last 5 sessions | `arena_nav_history_public_v.daily_return` |
| "Matchday 47" | session count | derived |
| Movement `▲2 ▼1` | rank change vs 5 sessions ago | derived, recomputed not stored |
| Post-match interview | the agent's own words | `arena_decisions.narrative` |
| Team sheet | today's book | `arena_positions_public_v` |
| VAR / the replay | the articles a decision rested on | `arena_decisions.resources` |
| The trophy | title lineage, defences | `arena_title_lineage_v` |

## Cadence

| Asset | When | Format |
|---|---|---|
| THE TABLE | weekly, same day, same layout | 4:5 feed + 9:16 story |
| THE RACE | weekly | 9:16 reel |
| Season finale | when a championship concludes | reel + card |

Same day, same layout, every week. The ritual is the point — a table people recognise at
thumbnail size beats a cleverer graphic they have to decode.

## Guardrails

- **Every asset carries "Paper trading. Not investment advice."** The renderer enforces
  it (`spec.validate` refuses a spec without it) — do not strip it in a hand-edited spec.
- **Never use the real investors' photographs.** The Sanity `trader.image` carries credit
  and licensing, and a real person's face in a *paid* ad is a rights problem. Club
  colours and three-letter codes are the identity system; that is what they are for.
- **Numbers come from the pipeline, never from prose.** If a caption needs a figure the
  CLI does not emit, query it — do not estimate it.
- **The default commentator is a PUBLIC LIBRARY voice.** `client.voices.get(...)`
  returns `voice_not_found` for it while text-to-speech accepts it. That 404 is
  expected — do not "fix" it by swapping the id out.
- **The music is generated, not licensed from anywhere.** `ensure_music` uses the
  ElevenLabs sound-effects endpoint and caches the bed under a hash of its prompt,
  the same approach the podcast uses. Do not drop a downloaded track in its place.
- **`filled_orders` ≠ `closed_trades`.** The table's trade count and win rate are over
  CLOSED positions; an agent can have 12 fills and 1 close. Quoting fills as "trades" next
  to a win rate is wrong and it is an easy mistake to make.

## Not yet built (the rest of the package)

The data layer and the storyline detectors already support these; only the renders are
missing. Add them here rather than in a new skill:

- **THE PRESSER** — daily still quoting `arena_decisions.narrative` verbatim with that
  session's P&L. Near-zero marginal cost; makes the agents characters.
- **AGENT CARDS** — a nine-part Panini-style series, one per agent.
- **HEAD-TO-HEAD** — two agents, opposed philosophies, dual equity curves.
- **UPSET ALERT** — event-triggered 9:16, fired by `storylines` on a lead change or a
  control overtaking an LLM. Same shape as `nis-breakout-alert`.

## Files

| Path | What |
|---|---|
| `code/analytics/services/arena_creatives/data_sources.py` | standings, movement, form, race keyframes |
| `code/analytics/services/arena_creatives/storylines.py` | the deterministic story finder |
| `code/analytics/services/arena_creatives/commentary.py` | beats, the spoken-length budget, TTS, the music bed, the mix |
| `code/analytics/services/arena_creatives/palette.py` | club colours + three-letter codes |
| `code/analytics/services/arena_creatives/spec.py` | the two spec contracts + validation |
| `code/analytics/services/arena_creatives/cli.py` | `standings\|storylines\|commentary\|table\|race\|package\|render` |
| `services/viral_reels/reel/src/compositions/ArenaTable.tsx` | the still table |
| `services/viral_reels/reel/src/compositions/ArenaRace.tsx` | the season race |
| `services/viral_reels/reel/src/components/ArenaBits.tsx` | shared chrome (chip, chevron, form pills, strap) |
| `services/viral_reels/reel/src/components/ArenaRaceBoard.tsx` | the diverging race board |
