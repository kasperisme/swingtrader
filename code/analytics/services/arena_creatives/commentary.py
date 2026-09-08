"""
commentary — the sound of the race: frame-locked beats, a voice, and a bed.

The point of commentary on a league-table race is not that words are spoken. It
is that the words land **on the moment they describe**. A voice-over that says
"and the coinflip takes the lead" three seconds after the bar has already moved
is worse than silence, because it teaches the viewer that the audio and the
picture are unrelated and they stop listening.

So the unit here is a **beat**: a thing that happened, the session it happened
on, and the exact second of the reel that session is on screen. The timeline
maths mirrors ``ArenaRace.tsx`` — intro, race, outro — and the race act maps
session index to time linearly, so a beat at session 22 of 47 is spoken while
session 22 is being drawn.

Three products come out of one beat list:

* the **voice-over** (ElevenLabs, one segment per beat, laid onto a silent track
  at each beat's second),
* the **burned-in captions** (the same beats, handed to the spec) — most social
  video is watched muted, so a commentary track that exists only in audio
  reaches a minority of the audience,
* the **music bed**, ducked underneath the voice.

Everything upstream of the words is deterministic. The default lines are
templates over real numbers; a director can replace any of them via
``--script``, but cannot introduce a beat that did not happen.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Timeline. Must match the constants in ArenaRace.tsx. ─────────────────────
INTRO_S = 2.2
OUTRO_S = 5.0

#: Beats closer together than this run into each other once spoken. Roughly one
#: line's length at the commentator's rate, so consecutive beats butt up rather
#: than leaving dead air between them.
MIN_BEAT_GAP_S = 3.0


@dataclass(frozen=True)
class VoiceProfile:
    """A commentator, and how fast it actually talks.

    ``words_per_sec`` is **measured**, not assumed — synthesise a handful of real
    beat lines with the voice and divide ``spoken_words`` by the segment length.
    It differs enough between voices to change how many words a slot holds (2.7
    against 2.2 is a whole clause), and a budget carried over from a different
    voice is how commentary starts talking over itself.

    Re-measure after changing a voice or its settings:

        for t in lines: len(AudioSegment(tts(t))) / spoken_words(t)
    """

    voice_id: str
    name: str
    #: Measured rate, already discounted ~10% — per-line rate varies with
    #: punctuation, and the budget should be the pessimistic end of that.
    words_per_sec: float
    stability: float
    style: float


VOICES: dict[str, VoiceProfile] = {
    # The default. Faster and more dynamic — the play-by-play register, which is
    # what a table race wants. NOTE: this is a PUBLIC LIBRARY voice, not one in
    # the account's own list: `client.voices.get(...)` returns voice_not_found
    # for it while text-to-speech accepts it happily. Do not "fix" that 404 by
    # removing the id.
    "commentator": VoiceProfile(
        voice_id="gnPxliFHTp6OK6tcoA6i",
        name="commentator",
        words_per_sec=2.4,  # measured 2.66
        stability=0.45,     # looser: lets the delivery lift on the numbers
        style=0.45,
    ),
    # The steadier alternative: a measured studio read rather than pitch-side.
    # Better for a season round-up than for an overtake.
    "broadcaster": VoiceProfile(
        voice_id="onwK4e9ZLuTAKqWW03F9",  # Daniel — Steady Broadcaster
        name="broadcaster",
        words_per_sec=2.0,  # measured 2.19
        stability=0.62,
        style=0.30,
    ),
}


def active_voice() -> VoiceProfile:
    """The commentator for this run.

    ``ARENA_COMMENTARY_VOICE`` picks a profile by name. ``ARENA_COMMENTARY_VOICE_ID``
    overrides the raw id for a one-off — it keeps the selected profile's rate,
    which is a guess for an unmeasured voice, so measure it before it becomes a
    default.
    """
    prof = VOICES.get(os.environ.get("ARENA_COMMENTARY_VOICE", "commentator"), VOICES["commentator"])
    override = os.environ.get("ARENA_COMMENTARY_VOICE_ID")
    if override and override != prof.voice_id:
        log.warning(
            "ARENA_COMMENTARY_VOICE_ID overrides %s; keeping its %.1f words/sec budget, "
            "which is unmeasured for this voice",
            prof.name,
            prof.words_per_sec,
        )
        return VoiceProfile(override, "override", prof.words_per_sec, prof.stability, prof.style)
    return prof


_ELEVEN_TTS_MODEL = "eleven_multilingual_v2"
_ELEVEN_OUTPUT_FORMAT = "mp3_44100_128"

#: The bed. Generated through ElevenLabs sound-effects and cached to disk, the
#: same approach the podcast uses for its hook music — which is what keeps the
#: audio licence-clean without a stock-music subscription.
MUSIC_PROMPT = os.environ.get(
    "ARENA_MUSIC_PROMPT",
    "Sports broadcast underscore for a league table results round-up: driving "
    "muted pulse, tense low strings, subtle rising tension, steady tempo, no "
    "vocals, no melody on top, broadcast quality, loopable",
)

_ASSETS = Path(__file__).resolve().parent.parent.parent / "scripts" / "assets" / "audio"


@dataclass
class Beat:
    """One thing worth saying, and the second of the reel to say it on."""

    key: str
    at_seconds: float
    text: str
    #: Session index into the race keyframes this beat describes (None for beats
    #: that belong to the intro or the outro rather than to a session).
    session_index: Optional[int] = None
    #: Words the slot can carry before the line runs into the next beat.
    word_budget: int = 0
    #: Candidate lines, longest first. The slot decides which one is used —
    #: a beat's timing is fixed by the picture, so the WORDS have to give way,
    #: not the moment. Written as variants rather than truncated at render time
    #: because a clipped sentence is a fact half-said.
    variants: list[str] = field(default_factory=list)

    def to_caption(self) -> dict[str, Any]:
        return {"atSeconds": round(self.at_seconds, 2), "text": self.text}


def spoken_words(text: str) -> int:
    """Estimate how many words a line takes to SAY, not to write.

    Written word count is a bad proxy the moment a number appears, and this
    commentary is mostly numbers: "plus 2.89%" is two written words and about
    six spoken ones ("plus two point eight nine percent"). Budgeting on the
    written count is what let a seven-word closing line overrun its slot by a
    full second and lose its last word.
    """
    n = 0
    for tok in text.split():
        core = tok.strip(".,;:—-()").replace(",", "")
        # A bare em-dash is a pause, not a word. Counting it cost every dated
        # line one word of its budget and knocked it down a rung.
        if not any(ch.isalnum() for ch in core):
            continue
        if not any(ch.isdigit() for ch in core):
            n += 1
            continue
        digits = core.replace("$", "").replace("%", "").replace("+", "").replace("-", "")
        if "." in digits:
            _, frac = digits.split(".", 1)
            # integer part + "point" + one word per decimal digit
            n += 2 + sum(c.isdigit() for c in frac)
        elif sum(c.isdigit() for c in digits) <= 2:
            n += 1  # "fifteen", "nine"
        else:
            n += 2  # "one hundred", "forty seven thousand"
        if "%" in tok:
            n += 1  # "percent"
        if "$" in tok:
            n += 1  # "dollars"
    return n


# ── Timeline helpers ─────────────────────────────────────────────────────────


def race_window(total_seconds: float) -> tuple[float, float]:
    """(start, duration) of the race act, matching the composition."""
    race = max(1.0, total_seconds - INTRO_S - OUTRO_S)
    return INTRO_S, race


def seconds_for_session(idx: int, n_sessions: int, total_seconds: float) -> float:
    """The second of the reel at which keyframe ``idx`` is on screen."""
    start, dur = race_window(total_seconds)
    if n_sessions <= 1:
        return start
    return start + (idx / (n_sessions - 1)) * dur


# ── Beat detection ───────────────────────────────────────────────────────────


def _leader_at(entries: list[dict[str, Any]]) -> str:
    return max(entries, key=lambda e: e["value"])["id"]


def _find_lead_changes(keyframes: list[dict[str, Any]], *, min_hold: int = 2) -> list[dict[str, Any]]:
    """Sessions where the leader changed and the new leader then held it.

    ``min_hold`` filters the noise: on a day when the top two are level to three
    decimal places the leader flickers, and calling every flicker makes the
    commentary sound like it is reading a spreadsheet rather than watching a
    race.
    """
    out: list[dict[str, Any]] = []
    prev = _leader_at(keyframes[0]["entries"])
    for i in range(1, len(keyframes)):
        cur = _leader_at(keyframes[i]["entries"])
        if cur == prev:
            continue
        held = 0
        for j in range(i, min(len(keyframes), i + min_hold)):
            if _leader_at(keyframes[j]["entries"]) == cur:
                held += 1
            else:
                break
        if held >= min_hold:
            out.append({"index": i, "slug": cur, "from": prev, "label": keyframes[i]["label"]})
            prev = cur
        # A flicker leaves `prev` alone, so the next real change is still caught.
    return out


def build_beats(
    standings: dict[str, Any],
    race: dict[str, Any],
    *,
    story: Optional[dict[str, Any]] = None,
    total_seconds: float = 22.0,
    max_beats: int = 8,
) -> list[Beat]:
    """The commentary spine: an opener, the lead changes, and the result.

    Beats are spaced at least ``MIN_BEAT_GAP_S`` apart and capped, because a
    22-second reel that tries to call nine overtakes says nothing about any of
    them. When there are more lead changes than slots, the ones kept are those
    involving a **control** — a random number generator or a buy-and-hold going
    top of a board of AI strategies is the whole point of the experiment, and it
    outranks one thinking agent passing another.
    """
    keyframes = race["keyframes"]
    n = len(keyframes)
    rows = {r["slug"]: r for r in standings["rows"]}
    controls = {r["slug"] for r in standings["rows"] if str(r.get("engine") or "").lower() == "deterministic"}

    start, dur = race_window(total_seconds)
    beats: list[Beat] = []

    # ── the opener, over the intro ───────────────────────────────────────────
    champ = standings["championship"]
    cash = int(champ.get("startingCash") or 100_000)
    sessions = standings.get("sessions", n)
    beats.append(
        Beat(
            key="open",
            at_seconds=0.35,
            text="",
            variants=[
                f"{len(rows)} A.I. agents. {cash // 1000} thousand dollars each. "
                f"{sessions} trading sessions. One market.",
                f"{len(rows)} A.I. agents. {cash // 1000} thousand dollars each. "
                f"{sessions} trading sessions.",
                f"{len(rows)} A.I. agents. {cash // 1000} thousand dollars each.",
                f"{len(rows)} agents. Same market.",
            ],
        )
    )
    # The premise, over the top of the board. Without it the head of the reel is
    # one short line and three seconds of nothing, and the viewer never learns
    # what the experiment actually varies — which is the only reason the
    # leaderboard means anything.
    beats.append(
        Beat(
            key="premise",
            at_seconds=start + 2.2,
            text="",
            variants=[
                "Same model. Same broker. Same risk limits. The only difference "
                "is what each one is allowed to see.",
                "Same model, same broker, same limits. Only the data differs.",
                "Same model. Same broker. Only the data differs.",
                "Only the data differs.",
            ],
        )
    )

    # ── the lead changes ─────────────────────────────────────────────────────
    changes = _find_lead_changes(keyframes)
    # A colour beat that is not a lead change: the moment the eventual last-placed
    # agent is at its lowest. Its bar is at full extension to the left, so there
    # is something on screen to talk about, and a race called only from the front
    # ignores half the picture.
    # Derived beats are chosen only from sessions that are actually SELECTABLE.
    # Picking the global argmin first and filtering afterwards silently drops the
    # beat whenever the low point happens to fall in the last two seconds — which
    # is exactly where a bottom-of-the-table low tends to be.
    selectable = [
        i
        for i in range(n)
        if start + 5.6 <= seconds_for_session(i, n, total_seconds) <= start + dur - 1.8
    ] or list(range(n))

    def _value(i: int, slug: str) -> float:
        return next((e["value"] for e in keyframes[i]["entries"] if e["id"] == slug), 0.0)

    # Score each change: a control taking the lead is the story; otherwise
    # prefer changes that are spread out across the race.
    scored = []
    for c in changes:
        row = rows.get(c["slug"], {})
        control = c["slug"] in controls
        scored.append({**c, "control": control, "score": 100 if control else 50, "row": row})
    # ── Derived beats get a RANGE of acceptable sessions, not one ───────────
    #
    # A lead change happens on exactly one session. "The field is under water"
    # and "the bottom is at its lowest" are true across a stretch of them. Given
    # a single index, both were silently lost the moment that index fell within
    # the minimum gap of a lead beat — which is common, because the sessions
    # worth talking about tend to cluster. Offering the whole stretch lets the
    # scheduler slide the beat to where it fits instead of dropping it.
    def _under(i: int) -> int:
        return sum(1 for e in keyframes[i]["entries"] if e["value"] < 0)

    def _spread(idxs: list[int], limit: int = 10) -> list[int]:
        """Thin a run of candidate sessions to a manageable, spread-out set."""
        if len(idxs) <= limit:
            return idxs
        step = len(idxs) / limit
        return [idxs[int(k * step)] for k in range(limit)]

    field_max = max(_under(i) for i in selectable)
    if field_max >= max(3, len(rows) // 2):
        for i in _spread([i for i in selectable if _under(i) >= field_max - 1]):
            scored.append(
                {
                    "index": i, "slug": "__field__", "from": None,
                    "label": keyframes[i]["label"], "control": False, "kind": "field",
                    "score": 65, "row": {"name": "the field"}, "n_under": _under(i),
                }
            )

    worst = standings["rows"][-1]
    worst_min = min(_value(i, worst["slug"]) for i in selectable)
    if worst_min < -0.03:
        near_low = [i for i in selectable if _value(i, worst["slug"]) <= worst_min * 0.85]
        for i in _spread(near_low):
            scored.append(
                {
                    "index": i, "slug": worst["slug"], "from": None,
                    "label": keyframes[i]["label"], "control": False, "kind": "bottom",
                    "score": 70, "row": worst,
                }
            )

    scored.sort(key=lambda c: (-c["score"], c["index"]))

    slots = max(0, max_beats - 2)  # the opener and the result are reserved

    # Greedy pick with DIMINISHING RETURNS per agent. Without the decay the
    # control bonus takes every slot, and an agent that leads three times gets
    # called three times while the rest of the field is never named — which
    # reads as a stuck commentator rather than a race. Each repeat of the same
    # slug costs more than the control bonus is worth, so a second spell is only
    # called when nothing else is competing for the slot.
    chosen: list[dict[str, Any]] = []
    picked: dict[str, int] = {}
    while len(chosen) < slots:
        best, best_score = None, float("-inf")
        for c in scored:
            if c in chosen:
                continue
            t = seconds_for_session(c["index"], n, total_seconds)
            # The opener owns the head of the reel. A lead beat crowding in
            # right behind it steals the opener's slot, and the opener is the
            # line that explains what anyone is looking at.
            if t < start + 5.6 or t > start + dur - 1.8:
                continue
            if any(
                abs(t - seconds_for_session(o["index"], n, total_seconds)) < MIN_BEAT_GAP_S
                for o in chosen
            ):
                continue
            eff = c["score"] - 60 * picked.get(c["slug"], 0)
            if eff > best_score:
                best, best_score = c, eff
        if best is None:
            break
        chosen.append(best)
        picked[best["slug"]] = picked.get(best["slug"], 0) + 1
    chosen.sort(key=lambda c: c["index"])

    # An agent is explained the FIRST time it goes top and not again. Commentary
    # that re-introduces the same competitor every time it leads sounds like a
    # machine reading rows, which is exactly what it is trying not to sound like.
    introduced: set[str] = set()
    for c in chosen:
        row = c["row"]
        name = row.get("name", c["slug"])
        surname = str(name).split()[-1]
        t = seconds_for_session(c["index"], n, total_seconds)
        value = _value(c["index"], c["slug"]) if c["slug"] != "__field__" else 0.0
        pct = f"{value * 100:+.1f}%".replace("+", "plus ").replace("-", "minus ")
        first = c["slug"] not in introduced
        introduced.add(c["slug"])

        if c.get("kind") == "field":
            k = c["n_under"]
            variants = [
                f"{c['label']}, and {k} of the {len(rows)} are under water. "
                f"The market is not making this easy.",
                f"{c['label']}, and {k} of the {len(rows)} are now under water.",
                f"{c['label']} — {k} of the {len(rows)} are under water.",
                f"{k} of the {len(rows)} are under water.",
                f"{k} of {len(rows)} under water.",
            ]
        elif c.get("kind") == "bottom":
            variants = [
                f"And at the bottom of the board, {name} is down "
                f"{abs(value) * 100:.0f}%. {row.get('tagline') or ''}".strip(),
                f"And at the bottom of the board, {name} is down {abs(value) * 100:.0f}%.",
                f"At the bottom, {name} is down {abs(value) * 100:.0f}%.",
                f"{name} is down {abs(value) * 100:.0f}%.",
                f"{surname}, bottom.",
            ]
        elif c["control"] and first:
            long_what, short_what = (
                ("It picks its stocks at random, on a fixed seed.", "It picks at random.")
                if c["slug"] == "burton-malarkey"
                else ("It bought the index on day one and has not traded since.",
                      "It never trades.")
            )
            variants = [
                f"{c['label']} — and {name} goes top of the board. {long_what}",
                f"{c['label']} — {name} goes top. {long_what}",
                f"{c['label']} — and {name} goes top of the board. {short_what}",
                f"{c['label']} — {name} goes top of the board. {short_what}",
                f"{c['label']} — {name} leads. {short_what}",
                f"{name} leads. {short_what}",
                f"{surname} leads. {short_what}",
                f"{surname} leads.",
            ]
        elif first:
            variants = [
                f"{c['label']} — {name} takes the front at {pct}. "
                f"{row.get('tagline') or ''}".strip(),
                f"{c['label']} — {name} takes the front at {pct}.",
                f"{c['label']} — {name} takes the front.",
                f"{name} takes the front.",
                f"{surname} takes the front.",
            ]
        else:
            variants = [
                f"{c['label']}, and {surname} is back in front at {pct}. "
                f"It has led this board before.",
                f"{c['label']}, and {surname} is back in front at {pct}.",
                f"{surname} is back in front at {pct}.",
                f"{surname} is back in front.",
                f"{surname} again.",
            ]
        # Keys carry the session so two spells in the lead are two beats, not a
        # collision — the script override and the audio segments key on this.
        kind = c.get("kind", "lead")
        beats.append(
            Beat(
                key=f"{kind}:{c['slug'].strip('_')}@{c['index']}"
                if kind != "field"
                else f"field@{c['index']}",
                at_seconds=t,
                text="",
                session_index=c["index"],
                variants=variants,
            )
        )

    # ── the result, over the outro ───────────────────────────────────────────
    leader = standings["rows"][0]
    bottom = standings["rows"][-1]
    lead_pct = f"{leader['return'] * 100:+.2f}%".replace("+", "plus ").replace("-", "minus ")
    hook = (story or {}).get("headline")
    beats.append(
        Beat(
            key="result",
            at_seconds=start + dur + 0.5,
            text="",
            variants=[
                v
                for v in (
                    f"{hook} The whole board is public." if hook else None,
                    hook,
                    f"At the close: {leader['name']}, {lead_pct}. "
                    f"The whole board is public.",
                    f"At the close: {leader['name']}, {lead_pct}. "
                    f"{bottom['name']} last.",
                    f"At the close: {leader['name']}, {lead_pct}.",
                    # A coarser number is worth more than no number: two decimals
                    # cost three spoken words on their own.
                    f"At the close: {leader['name']}, up {leader['return'] * 100:.1f}%.",
                    f"At the close: {leader['name']}.",
                    f"Your leader: {leader['name']}.",
                )
                if v
            ],
        )
    )

    beats.sort(key=lambda b: b.at_seconds)
    _budget(beats, total_seconds)
    return beats


def _budget(beats: list[Beat], total_seconds: float) -> None:
    """How many words each beat can carry, then pick the line that fits."""
    for i, b in enumerate(beats):
        nxt = beats[i + 1].at_seconds if i + 1 < len(beats) else total_seconds
        slot = max(0.6, nxt - b.at_seconds - 0.25)
        b.word_budget = max(3, int(slot * active_voice().words_per_sec))
        if b.variants:
            fits = [v for v in b.variants if spoken_words(v) <= b.word_budget]
            # Longest that fits; if nothing fits, the shortest written variant
            # and an overrun warning — never a truncation.
            b.text = fits[0] if fits else b.variants[-1]


def check_overruns(beats: list[Beat], total_seconds: float) -> list[str]:
    """Lines whose word count will not fit their slot, as warnings.

    Reported rather than silently truncated: a clipped commentary line is a
    wrong fact half-said, and the director should shorten it deliberately.
    """
    out = []
    for i, b in enumerate(beats):
        words = spoken_words(b.text)
        if words > b.word_budget:
            nxt = beats[i + 1].at_seconds if i + 1 < len(beats) else total_seconds
            out.append(
                f"beat {b.key!r} at {b.at_seconds:.1f}s has {words} words but only "
                f"{b.word_budget} fit before {nxt:.1f}s — shorten it or move the beat"
            )
    return out


def load_script(path: str | Path, beats: list[Beat], total_seconds: float) -> list[Beat]:
    """Replace beat TEXT from an authored script; timings stay derived.

    The file is ``{"<beat key>": "the line"}``. Keys that do not match a
    detected beat are refused rather than appended — the words are the
    director's, the events are not.
    """
    data = json.loads(Path(path).read_text())
    known = {b.key for b in beats}
    unknown = set(data) - known
    if unknown:
        raise ValueError(
            f"script has beats that were not detected: {sorted(unknown)}. "
            f"Detected: {sorted(known)}"
        )
    for b in beats:
        if b.key in data:
            b.text = str(data[b.key])
            # Clear the variants: _budget() re-picks text from them, which would
            # silently discard the authored line. An override is a decision, and
            # if it does not fit the slot the right answer is a warning, not a
            # quiet substitution of the template.
            b.variants = []
    _budget(beats, total_seconds)
    return beats


# ── Audio ────────────────────────────────────────────────────────────────────


def _eleven():
    from elevenlabs.client import ElevenLabs

    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY not set — cannot voice the commentary")
    return ElevenLabs(api_key=key)


def _tts(text: str, out_path: Path) -> Path:
    client = _eleven()
    voice = active_voice()
    audio = client.text_to_speech.convert(
        voice_id=voice.voice_id,
        text=text,
        model_id=_ELEVEN_TTS_MODEL,
        output_format=_ELEVEN_OUTPUT_FORMAT,
        voice_settings={
            "stability": voice.stability,
            "similarity_boost": 0.75,
            "style": voice.style,
            "use_speaker_boost": True,
        },
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"".join(audio))
    return out_path


def ensure_music(duration_seconds: float = 22.0, *, prompt: Optional[str] = None) -> Optional[Path]:
    """Generate (and cache) the arena bed. Returns None if unavailable.

    Cached under a hash of the prompt so changing the prompt regenerates rather
    than silently serving the old bed. Failure is not fatal — a reel with a
    voice and no music is fine; a pipeline that dies because a music API was
    down is not.
    """
    p = prompt or MUSIC_PROMPT
    tag = hashlib.sha1(p.encode()).hexdigest()[:8]
    target = _ASSETS / f"arena_bed_{tag}.mp3"
    if target.exists() and target.stat().st_size > 0:
        log.info("arena music bed (cached): %s", target)
        return target

    try:
        client = _eleven()
    except RuntimeError as exc:
        log.warning("no music: %s", exc)
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    # The sound-effects endpoint caps well below a full reel, so a short bed is
    # generated and looped to length in the mix.
    gen_s = min(20.0, max(8.0, duration_seconds / 2))
    log.info("generating arena music bed (%.1fs, prompt %r)", gen_s, p[:60])
    try:
        audio = client.text_to_sound_effects.convert(
            text=p, duration_seconds=gen_s, prompt_influence=0.3
        )
        target.write_bytes(b"".join(audio))
        return target
    except Exception as exc:  # noqa: BLE001 — never fatal
        log.warning("music generation failed (%s); continuing without a bed", exc)
        return None


#: Mix targets, in dBFS. Levels are NORMALISED to these rather than attenuated
#: by a fixed amount, because neither source has a predictable level: the TTS
#: output varies per line and the generated bed varies per prompt. A blind
#: `-21 dB` on an already-quiet bed put the music 29 dB under the voice — a bed
#: nobody could hear, which is the same as no bed at all.
VOICE_DBFS = -16.0
MUSIC_DBFS = -30.0  # ~14 dB under the voice: present, clearly underneath
DUCK_DB = -8.0  # a further drop while a line is being spoken


def _normalise(seg, target_dbfs: float):
    """Set a segment's level to a target, tolerating digital silence."""
    if seg.dBFS == float("-inf"):
        return seg
    return seg.apply_gain(target_dbfs - seg.dBFS)


def build_audio(
    beats: list[Beat],
    out_dir: Path,
    *,
    total_seconds: float,
    with_voice: bool = True,
    with_music: bool = True,
    music_dbfs: float = MUSIC_DBFS,
    duck_db: float = DUCK_DB,
    keep_segments: bool = False,
) -> Optional[Path]:
    """Voice the beats, lay them on the timeline, duck a bed under them.

    Returns the mixed track, or None when neither layer could be produced.
    """
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError("pydub not installed — run: pip install pydub (needs ffmpeg)") from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    total_ms = int(total_seconds * 1000)
    voice = AudioSegment.silent(duration=total_ms)
    windows: list[tuple[int, int]] = []

    if with_voice:
        seg_dir = out_dir / "vo"
        for b in beats:
            seg = seg_dir / f"{b.key.replace(':', '_')}.mp3"
            log.info("voicing %s @ %.1fs — %s", b.key, b.at_seconds, b.text[:60])
            _tts(b.text, seg)
            # Per-line normalisation, not per-track: ElevenLabs returns a
            # different level for a four-word line than for a twelve-word one,
            # and normalising the assembled track would leave that unevenness
            # in place while flattening the whole thing against the bed.
            audio = _normalise(AudioSegment.from_file(seg), VOICE_DBFS)
            at = int(b.at_seconds * 1000)
            end = at + len(audio)
            if end > total_ms:
                log.warning(
                    "beat %r runs %.1fs past the end of the reel — it will be cut off",
                    b.key,
                    (end - total_ms) / 1000,
                )
            # The estimator is a budget, not a measurement. Once the segment
            # exists its true length is known, so an actual collision is
            # reported rather than left for someone to notice on playback.
            nxt = next((int(o.at_seconds * 1000) for o in beats if o.at_seconds > b.at_seconds), None)
            if nxt is not None and end > nxt:
                log.warning(
                    "beat %r overruns the next beat by %.1fs — shorten the line or "
                    "lengthen the reel (--duration)",
                    b.key,
                    (end - nxt) / 1000,
                )
            voice = voice.overlay(audio, position=at)
            windows.append((at, min(end, total_ms)))
        if not keep_segments and seg_dir.exists():
            for f in seg_dir.glob("*.mp3"):
                f.unlink()
            if not any(seg_dir.iterdir()):
                seg_dir.rmdir()

    bed = None
    if with_music:
        music_path = ensure_music(total_seconds)
        if music_path:
            src = AudioSegment.from_file(music_path)
            bed = AudioSegment.empty()
            while len(bed) < total_ms:
                # Crossfade the loop point so the seam is not a click.
                bed = src if len(bed) == 0 else bed.append(src, crossfade=600)
            bed = _normalise(bed[:total_ms], music_dbfs).fade_in(700).fade_out(1200)

            # Duck under each spoken window rather than globally, so the bed is
            # present between the lines and out of the way underneath them.
            for at, end in windows:
                head, mid, tail = bed[:at], bed[at:end].apply_gain(duck_db), bed[end:]
                bed = head + mid + tail

    if bed is None and not with_voice:
        return None
    mixed = bed.overlay(voice) if bed is not None else voice
    out = out_dir / "audio.mp3"
    mixed.export(out, format="mp3")
    log.info("mixed audio → %s (%.1fs)", out, len(mixed) / 1000)
    return out


def speech_coverage(beats: list[Beat], total_seconds: float) -> float:
    """Estimated fraction of the reel carrying speech.

    A race with commentary over half its runtime plays as a silent chart that
    someone occasionally comments on. Around 0.8 is the target — dense enough to
    feel called, with air left for the music between lines.
    """
    wps = active_voice().words_per_sec
    spoken = sum(spoken_words(b.text) / wps for b in beats)
    return min(1.0, spoken / max(1e-6, total_seconds))


def beats_to_json(beats: list[Beat]) -> list[dict[str, Any]]:
    return [asdict(b) for b in beats]
