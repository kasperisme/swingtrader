# services/arena_creatives

The Arena's broadcast package: a still **league table** and the season **race**, built
from the arena's live public views and rendered through the repo's Remotion project.

Driven by the `nis-arena-report` skill; the CLI also runs standalone.

```bash
cd code/analytics
.venv/bin/python -m services.arena_creatives.cli standings    # the table, with ▲▼ and form
.venv/bin/python -m services.arena_creatives.cli storylines   # every hook it supports
.venv/bin/python -m services.arena_creatives.cli package      # standings + table ×3 + race
```

Output, one dated folder per publication per season:

```
output/arena/<championship-slug>/<YYYY-MM-DD>/
    standings.json   storylines.json
    table/spec.<ratio>.json  table/<ratio>/table.png     4x5 · 9x16 · 1x1
    race/spec.json           race/race.mp4               9:16, ~22s
```

## Why it looks like a football table

Sport has spent sixty years making a slow numeric contest feel urgent every week, and the
devices transfer exactly: a position number, a movement chevron, a W/L form guide,
promotion and relegation bands, and one strap line carrying the story. A dashboard asks
the viewer to interpret; a table tells them who is winning and who is in trouble before a
word is read.

## Five things to know before changing it

- **Read-only, and public views only.** Everything comes from `arena_leaderboard_v`,
  `arena_nav_history_public_v` and `arena_championships_public_v`, which filter on
  `is_published` *in the view* — so a creative can never publish an agent still being
  tuned. Nothing here writes.

- **The story is detected, not chosen.** `storylines.py` enumerates the hooks the table
  supports and ranks them. This exists because the best story is usually the least
  flattering one — a control leading, or the coinflip beating three LLMs — and a human
  picking week after week drifts toward the flattering read. The same detectors are the
  trigger for a future event-fired UPSET ALERT.

- **The race metric is return, not NAV.** Nine books between $90k and $103k are nine bars
  of identical length; the same nine as −9.9%…+2.9% is a race. Bars diverge from a zero
  line because half the field is usually negative, and the axis is **fixed for the whole
  video** from the global min/max — a rescaling axis makes every bar appear to move on a
  session where nothing happened.

- **No club colour may be gain-green or loss-red** (`palette.py`). In the race the bar IS
  the club colour and its direction carries the sign, so a green bar going left reads as a
  rendering bug. That is why the Cramer parody is orange.

- **The renders live in the `viral_reels` Remotion project.** `reel/src/compositions/
  ArenaTable.tsx` and `ArenaRace.tsx`, registered in `Root.tsx`. That project is the
  repo's single render surface — installed `node_modules`, the shared `theme.ts` palette,
  and the rank-interpolation helpers a race needs. A second Remotion app would duplicate
  all three and let the two drift apart visually, which is the one thing a broadcast
  package cannot survive.

## Commentary + music

```bash
.venv/bin/python -m services.arena_creatives.cli commentary            # the beat sheet
.venv/bin/python -m services.arena_creatives.cli race --voice --music  # voiced + scored
```

`commentary.py` produces **beats** — a thing that happened, the session it happened on,
and the second of the reel that session is on screen. The timeline maths mirrors
`ArenaRace.tsx` exactly, so a line about session 22 is spoken while session 22 is drawn.
Commentary that describes an overtake three seconds after the bar moved teaches the
viewer that the audio and the picture are unrelated, and they stop listening.

One beat list, three products: the voice-over (ElevenLabs, one segment per beat laid onto
a silent track at its second), the burned-in **captions** (most social video is watched
muted), and the ducked music bed. The bed is **generated** through the sound-effects
endpoint and cached under a hash of its prompt — the same licence-clean approach the
podcast uses for its hook music.

Beat types: `open`, `premise`, `lead:<agent>@<session>`, `bottom:<agent>@<session>`,
`field@<session>`, `result`. Lead changes happen on one session; "the field is under
water" and "the bottom is at its lowest" are true across a stretch, so those are offered
to the scheduler as a RANGE of sessions — given a single index they were silently dropped
whenever it fell within the minimum gap of a lead beat, which is common because the
sessions worth talking about cluster.

Voices carry a **measured** `words_per_sec`. `commentator` (default, 2.4) is play-by-play;
`broadcaster` (2.0) is a studio read. Select with `ARENA_COMMENTARY_VOICE`. Re-measure
after changing a voice — a budget carried over from a different one is how commentary
starts talking over itself. The default is a public-library voice: `voices.get()` 404s on
it while TTS accepts it, which is expected.

`speech_coverage()` reports the fraction of the reel carrying speech. Under ~0.7 the reel
plays as a silent chart with occasional remarks; ~0.8 is the target.

Four things that were wrong on the first pass and are now load-bearing:

- **Budget on SPOKEN words, not written ones.** "plus 2.89%" is two written words and
  about six spoken. Budgeting on the written count let a seven-word closing line overrun
  its slot by a second and lose its last word. `spoken_words()` expands numerals.
- **Lines are variants, not one string.** The beat's timing is fixed by the picture, so
  when a line does not fit the slot the WORDS give way — the longest variant that fits is
  chosen. Never a truncation: a clipped sentence is a fact half-said.
- **Punctuation is not spoken.** A bare em-dash counted as a word, costing every dated
  line one word of budget and knocking it down a rung of its variant ladder.
- **Levels are normalised to targets, not attenuated by a fixed amount.** Neither source
  has a predictable level. A blind −21 dB on an already-quiet generated bed put the music
  29 dB under the voice, which is the same as having no music.

Beat selection applies **diminishing returns per agent**: without it the control bonus
takes every slot, and an agent that leads three times gets called three times while the
rest of the field is never named — a stuck commentator rather than a race.

Sharpen the words with `--script <json>` keyed on the beat keys from the beat sheet. Keys
that match no detected beat are refused: the words are the director's, the events are not.

## Two traps

**`filled_orders` ≠ `closed_trades`.** The table's trade count and win rate are over
CLOSED positions. An agent can have 12 fills and 1 close; quoting fills as "trades" beside
a win rate is wrong.

**`OUTRO_S` is duplicated** in `commentary.py` and `ArenaRace.tsx`. The commentary places
its closing beat from that constant, so changing one without the other puts the result
line over the wrong picture.

**Rank transitions are eased within each session step** (`settleProgress` in
`ArenaRace.tsx`). A season is ~47 sessions in ~16 seconds, so a linear playhead is
permanently mid-transition and rows stack on top of each other. Easing makes them settle
at whole ranks and cross quickly. If you change the runtime or the keyframe count, check a
mid-race frame for collisions.

## Compliance

`spec.validate()` refuses any spec without `footer.disclaimer` and `footer.asOf`. Both
fail silently at render time — a missing footer still produces a pretty image — and
neither is publishable. Do not strip them from a hand-edited spec.
