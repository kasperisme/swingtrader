"""
viral_reels.dialog — synthetic Nami × Luffy banter about the news.

A spin-off of the reel pipeline: instead of (or alongside) a bar-chart race,
generate a short, voiced **dialogue** where One Piece's money-obsessed navigator
**Nami** breaks down the day's market-moving headlines for the carefree captain
**Luffy**. Nami is the analyst (she loves treasure/berries → loves a good
trade); Luffy is the naive enthusiast who reacts and asks the dumb-smart
questions. The result is a single stitched MP3 voiced via ElevenLabs.

Two stages, mirroring the rest of the service:
  1. Claude writes the script   — `generate_dialog_script()` (Anthropic)
  2. ElevenLabs voices + stitch  — `render_dialog()` (per-turn TTS → ffmpeg/pydub)

Voice IDs are the canonical One Piece fan voices (override via env if needed):
    LUFFY → UnDWNGYfYVHrYbgQXZOS   (env: ELEVENLABS_LUFFY_VOICE_ID)
    NAMI  → uzAAg0A7FBedb5sTJjXA   (env: ELEVENLABS_NAMI_VOICE_ID)

Requires: anthropic (script) + elevenlabs (voice) + ffmpeg (stitch, via pydub).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import data_sources as ds

log = logging.getLogger(__name__)

# Spoken-word pace used to budget how many words fit in a time slot (~144 wpm).
_WORDS_PER_SEC = 2.4
# The renderer holds the final candle for ~2.2s after the line finishes drawing.
_RENDER_HOLD_S = 2.2

# --- Voices -----------------------------------------------------------------

LUFFY_VOICE_ID = os.environ.get("ELEVENLABS_LUFFY_VOICE_ID", "UnDWNGYfYVHrYbgQXZOS")
NAMI_VOICE_ID = os.environ.get("ELEVENLABS_NAMI_VOICE_ID", "uzAAg0A7FBedb5sTJjXA")

_ELEVEN_MODEL = "eleven_multilingual_v2"
_ELEVEN_OUTPUT_FORMAT = "mp3_44100_128"


@dataclass(frozen=True)
class Speaker:
    name: str          # display name in the script
    voice_id: str
    stability: float
    style: float


# Luffy: low stability + high style → loose, energetic, goofy delivery.
# Nami: steadier, a touch of expression → the sharp navigator/analyst.
SPEAKERS: dict[str, Speaker] = {
    "luffy": Speaker("Luffy", LUFFY_VOICE_ID, stability=0.40, style=0.55),
    "nami": Speaker("Nami", NAMI_VOICE_ID, stability=0.60, style=0.35),
}


def _speaker(name: str) -> Speaker:
    key = (name or "").strip().lower()
    if key not in SPEAKERS:
        raise ValueError(f"Unknown speaker {name!r}. Valid: {list(SPEAKERS)}")
    return SPEAKERS[key]


# --- Stage 0: gather the news the two will talk about -----------------------

def gather_news_context(
    ticker: str | None = None,
    window_days: int = 7,
    limit: int = 6,
) -> dict[str, Any]:
    """Pull a compact slice of real news for the dialogue to be grounded in.

    Ticker-scoped → that ticker's strongest recent headlines (with AI sentiment
    and next-day move). Otherwise → the market-wide trend snapshot + top
    headlines. Degrades to an empty context (with a warning) if the data layer
    is unreachable, so the dialogue can still be written generically.
    """
    ctx: dict[str, Any] = {"ticker": (ticker or "").upper() or None, "window_days": window_days}
    try:
        if ticker:
            events = ds.news_candidates(ticker.upper(), window_days=window_days)
            events.sort(key=lambda e: e.get("impact", 0), reverse=True)
            ctx["headlines"] = [
                {
                    "title": e.get("title"),
                    "source": e.get("source"),
                    "sentiment": e.get("sentiment"),
                    "move": e.get("move"),
                    "date": e.get("date") or e.get("t"),
                }
                for e in events[:limit]
            ]
        else:
            ctx["snapshot"] = ds.trend_snapshot(window_days=window_days)
            ctx["headlines"] = [
                {"title": h.get("title"), "source": h.get("source"), "age": h.get("age")}
                for h in ds.headlines(window_days=window_days, limit=limit)
            ]
    except Exception as exc:  # data layer needs Supabase creds; don't hard-fail
        log.warning("news context unavailable (%s) — writing a generic dialogue", exc)
        ctx["headlines"] = []
    return ctx


# --- Stage 1: write the script (Anthropic) ----------------------------------

_SYSTEM = """You are a comedy scriptwriter voicing two One Piece characters as a \
finance double-act for a swing-trading brand (News Impact Screener).

NAMI — the navigator. She loves money and treasure (berries!), so she's the \
sharp market analyst. She reads the news, explains which stock it moves and why, \
talks impact/sentiment/price like a pro who's hunting treasure. Confident, a \
little bossy, quick.

LUFFY — the captain. Carefree, simple, food-obsessed, says "Shishishi", doesn't \
understand finance at all but is wildly enthusiastic and asks blunt, dumb-but- \
oddly-insightful questions that let Nami explain things. He'd rather eat meat \
than read a chart.

Write a punchy, funny dialogue where Nami breaks the news down for Luffy. Rules:
- SCROLL-STOPPER: the very FIRST word of the very first line MUST be "Stop" or \
"Wait" (e.g. "Stop — Luffy, look at this." / "Wait. You're telling me…") to \
hook a scroller in the first second. No other opener is allowed.
- Stay 100% in character. Nami carries the substance; Luffy reacts and questions.
- Ground it in the SUPPLIED HEADLINES — name the real tickers/companies/moves. \
Never invent a price or a move that isn't in the data.
- Tight and spoken-word: short turns, natural banter, no narration or stage \
directions, no emojis, no markdown. It will be read aloud by TTS.
- Land an actual takeaway a retail swing trader could use, in Nami's voice.
- End on a quick Luffy punchline.

Return ONLY a JSON object: {"turns": [{"speaker": "nami"|"luffy", "text": "..."}]}.
Alternate speakers naturally; usually open and close in a memorable way."""


def _news_block(ctx: dict[str, Any]) -> str:
    lines: list[str] = []
    if ctx.get("ticker"):
        lines.append(f"Focus ticker: {ctx['ticker']}")
    for h in ctx.get("headlines", []) or []:
        bits = [str(h.get("title") or "").strip()]
        meta = []
        if h.get("source"):
            meta.append(str(h["source"]))
        if h.get("sentiment") is not None:
            meta.append(f"sentiment {h['sentiment']}")
        if h.get("move"):
            meta.append(str(h["move"]))
        if h.get("date"):
            meta.append(str(h["date"]))
        if meta:
            bits.append(f"({', '.join(meta)})")
        lines.append("- " + " ".join(bits))
    snap = ctx.get("snapshot")
    if snap and not ctx.get("ticker"):
        movers = snap.get("clusters") or snap.get("dimensions") or []
        if movers:
            lines.append("Trending areas: " + ", ".join(
                str(m.get("label") or m.get("key")) for m in movers[:5]
            ))
    return "\n".join(lines) or "(no specific headlines available — keep it general about the market)"


def generate_dialog_script(
    ctx: dict[str, Any],
    *,
    turns: int = 8,
    model: str | None = None,
    extra_direction: str | None = None,
) -> list[dict[str, str]]:
    """Ask Claude for a Nami×Luffy dialogue as a list of {speaker, text} turns."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package not installed — run: pip install anthropic") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    resolved_model = model or os.environ.get("ANTHROPIC_IMPACT_MODEL") or "claude-haiku-4-5-20251001"
    user = (
        f"Write roughly {turns} turns of Nami×Luffy dialogue about this news.\n\n"
        f"HEADLINES:\n{_news_block(ctx)}\n"
    )
    if extra_direction:
        user += f"\nExtra direction: {extra_direction}\n"

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=resolved_model,
        max_tokens=1600,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    raw = msg.content[0].text
    return _parse_turns(raw)


def _parse_turns(raw: str) -> list[dict[str, str]]:
    """Pull the turns array out of the model response, tolerating code fences."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError(f"Could not parse dialogue JSON from model output:\n{raw[:400]}")
        obj = json.loads(m.group(0))
    turns = obj["turns"] if isinstance(obj, dict) else obj
    cleaned: list[dict[str, str]] = []
    for t in turns:
        speaker = str(t.get("speaker", "")).strip().lower()
        spoken = str(t.get("text", "")).strip()
        if speaker in SPEAKERS and spoken:
            cleaned.append({"speaker": speaker, "text": spoken})
    if not cleaned:
        raise ValueError("Model returned no usable dialogue turns")
    return _ensure_scroll_stopper(cleaned)


def _ensure_scroll_stopper(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    """Guarantee the first line opens with a scroll-stopping 'Stop' / 'Wait'.

    The prompt already asks for this; this is a deterministic safety net so the
    hook is never missing even if the model drifts.
    """
    first = turns[0]["text"].lstrip()
    if re.match(r"^(stop|wait)\b", first, flags=re.IGNORECASE):
        return turns
    turns[0]["text"] = "Wait. " + turns[0]["text"]
    return turns


# --- Event-synced dialogue (commentary timed to the reel's pins) ------------
#
# The plain dialogue above is length-matched to the reel but content-blind. This
# path instead reads the **events actually plotted on the reel**, computes when
# each pin appears on screen (mirroring PriceNewsChart's linear-draw timing), and
# writes a beat per event so Nami is talking about a headline exactly as its card
# slides onto the chart. A fixed-point solve sizes the reel to the assembled
# audio so the two stay locked.

def _epoch(t: str) -> float:
    s = str(t)
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        from datetime import datetime
        return datetime.fromisoformat(s[:10]).timestamp()


def _event_point_indices(events: list[dict], points: list[dict]) -> list[int]:
    """Point index each event lands on — same nearest-timestamp rule as the renderer."""
    tmap = {p["t"]: i for i, p in enumerate(points)}
    out: list[int] = []
    for e in events:
        t = e.get("t")
        if t in tmap:
            out.append(tmap[t])
        else:
            te = _epoch(t)
            out.append(min(range(len(points)), key=lambda i: abs(_epoch(points[i]["t"]) - te)))
    return out


def event_time_seconds(idx: int, n: int, fps: int, duration_s: float) -> float:
    """On-screen time (s) at which the line reaches point ``idx`` — mirrors
    PriceNewsChart: linear draw over ``drawF = total - 1 - hold`` frames."""
    total_frames = round(duration_s * fps)
    last_f = max(1, total_frames - 1)
    hold_f = round(_RENDER_HOLD_S * fps)
    draw_f = max(1, last_f - hold_f)
    pass_frame = (idx / max(1, n - 1)) * draw_f
    return pass_frame / fps


_SYNC_SYSTEM = """You are a comedy scriptwriter voicing two One Piece characters \
as a finance double-act for a swing-trading brand (News Impact Screener). The \
dialogue is a VOICE-OVER for a stock chart video: the price line draws left→right \
and news-headline cards pop onto the chart at specific moments. Your script must \
TALK ABOUT EACH HEADLINE EXACTLY AS IT APPEARS.

NAMI — the navigator. Loves money/treasure (berries!), so she's the sharp market \
analyst. She reads each headline as it lands, says what it did to the stock \
(use the given move/sentiment), quick and confident, a little bossy.
LUFFY — the captain. Carefree, simple, food-obsessed, says "Shishishi", clueless \
about finance but wildly enthusiastic; asks blunt dumb-but-insightful questions.

You get an ordered list of EVENTS (the cards, in the order they appear on screen), \
each with its headline, source, sentiment, price move, and a WORD BUDGET (how many \
words of dialogue fit before the next card appears). Write:
- "hook": the opener. FIRST WORD MUST be "Stop" or "Wait" (scroll-stopper). Tease \
the stock before the first card lands. Keep within its word budget.
- "beats": ONE per event, in the SAME order. beats[i].event_index = i. Each beat is \
1-3 short turns that react to THAT headline by name and its move — Nami explains, \
Luffy reacts. Stay within each beat's word budget so the talk tracks the card.
- "outro": the closing takeaway (Nami, actionable + slightly contrarian) + a quick \
Luffy punchline.

Hard rules: stay 100% in character; ground every claim in the supplied headline/ \
move/sentiment — NEVER invent a price or a move; no narration, stage directions, \
emojis, or markdown (it's read aloud by TTS). BREVITY IS CRITICAL: each beat is a \
voice-over slot that MUST fit its word budget — treat the budget as a hard cap, go \
UNDER it, and keep turns punchy (a beat is often just one Nami line + one short \
Luffy reaction). Going over desyncs the video. Total dialogue should feel fast.

Return ONLY JSON:
{"hook":[{"speaker","text"}],"beats":[{"event_index":0,"turns":[{"speaker","text"}]}],"outro":[{"speaker","text"}]}"""


def _events_brief(events: list[dict], budgets: list[int]) -> str:
    lines = []
    for i, (e, wb) in enumerate(zip(events, budgets)):
        meta = []
        if e.get("source"):
            meta.append(str(e["source"]))
        if e.get("sentiment") is not None:
            meta.append(f"sentiment {e['sentiment']:+.2f}" if isinstance(e["sentiment"], (int, float)) else f"sentiment {e['sentiment']}")
        if e.get("move"):
            meta.append(str(e["move"]))
        tag = f" ({', '.join(meta)})" if meta else ""
        lines.append(f'[{i}] "{str(e.get("title") or "").strip()}"{tag} — budget ~{wb} words')
    return "\n".join(lines)


def generate_synced_dialog(
    chart: dict[str, Any],
    *,
    fps: int,
    provisional_duration: float,
    hook_words: int,
    outro_words: int,
    model: str | None = None,
    extra_direction: str | None = None,
) -> dict[str, Any]:
    """Ask Claude for an event-synced script: a hook, one beat per plotted event,
    and an outro. ``provisional_duration`` only sizes the per-beat word budgets;
    the final reel length is solved later from the rendered audio."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package not installed") from exc
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    events = chart["events"]
    # The reel now draws at a variable speed locked to the voice-over, so each
    # beat just needs a balanced, snappy length — split the talk budget evenly
    # across the events (a couple of seconds reserved for hook + outro).
    talk_s = max(8.0, provisional_duration - _RENDER_HOLD_S)
    per_beat_s = talk_s / max(1, len(events))
    budgets: list[int] = [max(10, round(per_beat_s * _WORDS_PER_SEC))] * len(events)

    user = (
        f"Reel is ~{provisional_duration:.0f}s. Hook budget ~{hook_words} words, "
        f"outro budget ~{outro_words} words.\n\n"
        f"EVENTS (in on-screen order):\n{_events_brief(events, budgets)}\n"
    )
    if extra_direction:
        user += f"\nExtra direction: {extra_direction}\n"

    resolved_model = model or os.environ.get("ANTHROPIC_IMPACT_MODEL") or "claude-haiku-4-5-20251001"
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=resolved_model,
        max_tokens=2200,
        system=_SYNC_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return _parse_synced(msg.content[0].text, n_events=len(events))


def _clean_turns(turns: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for t in turns or []:
        spk = str(t.get("speaker", "")).strip().lower()
        txt = str(t.get("text", "")).strip()
        if spk in SPEAKERS and txt:
            out.append({"speaker": spk, "text": txt})
    return out


def _parse_synced(raw: str, *, n_events: int) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError(f"Could not parse synced dialogue JSON:\n{raw[:400]}")
        obj = json.loads(m.group(0))

    hook = _clean_turns(obj.get("hook"))
    outro = _clean_turns(obj.get("outro"))
    by_idx: dict[int, list[dict[str, str]]] = {}
    for b in obj.get("beats") or []:
        ei = b.get("event_index")
        turns = _clean_turns(b.get("turns"))
        if isinstance(ei, int) and turns:
            by_idx[ei] = turns
    beats = [{"event_index": i, "turns": by_idx.get(i, [])} for i in range(n_events)]
    if not hook:
        hook = [{"speaker": "nami", "text": "Wait. Watch this one."}]
    hook = _ensure_scroll_stopper(hook)
    return {"hook": hook, "beats": beats, "outro": outro}


# --- Stage 2: voice + stitch (ElevenLabs + ffmpeg/pydub) ---------------------

def _tts_segment(text: str, speaker: Speaker, out_path: Path) -> Path:
    from elevenlabs.client import ElevenLabs

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    client = ElevenLabs(api_key=api_key)
    audio = client.text_to_speech.convert(
        voice_id=speaker.voice_id,
        text=text,
        model_id=_ELEVEN_MODEL,
        output_format=_ELEVEN_OUTPUT_FORMAT,
        voice_settings={
            "stability": speaker.stability,
            "similarity_boost": 0.75,
            "style": speaker.style,
            "use_speaker_boost": True,
        },
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"".join(audio))
    return out_path


def render_dialog(
    turns: list[dict[str, str]],
    out_path: Path,
    *,
    gap_ms: int = 350,
    keep_segments: bool = False,
) -> Path:
    """Voice each turn via ElevenLabs and stitch them into one MP3."""
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError("pydub not installed — run: pip install pydub (needs ffmpeg)") from exc

    out_path = Path(out_path)
    seg_dir = out_path.parent / "segments"
    combined = AudioSegment.empty()
    gap = AudioSegment.silent(duration=gap_ms)

    for i, turn in enumerate(turns):
        spk = _speaker(turn["speaker"])
        seg_path = seg_dir / f"{i:03d}_{spk.name.lower()}.mp3"
        log.info("voicing turn %d/%d — %s (%d chars)", i + 1, len(turns), spk.name, len(turn["text"]))
        _tts_segment(turn["text"], spk, seg_path)
        combined += AudioSegment.from_file(seg_path)
        if i < len(turns) - 1:
            combined += gap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(out_path, format="mp3")
    log.info("stitched %d turns → %s (%.1fs)", len(turns), out_path, len(combined) / 1000)

    if not keep_segments:
        for f in seg_dir.glob("*.mp3"):
            f.unlink()
        if seg_dir.exists() and not any(seg_dir.iterdir()):
            seg_dir.rmdir()
    return out_path


# --- Orchestration ----------------------------------------------------------

def make_dialog(
    *,
    ticker: str | None = None,
    window_days: int = 7,
    turns: int = 8,
    out_dir: Path,
    model: str | None = None,
    extra_direction: str | None = None,
    render: bool = True,
) -> dict[str, Any]:
    """End-to-end: gather news → write script → (optionally) voice it.

    Returns {"script": [...], "script_path": str, "audio_path": str | None}.
    """
    out_dir = Path(out_dir)
    ctx = gather_news_context(ticker, window_days=window_days)
    script = generate_dialog_script(ctx, turns=turns, model=model, extra_direction=extra_direction)

    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = out_dir / "dialog_script.json"
    script_path.write_text(json.dumps({"context": ctx, "turns": script}, indent=2))

    audio_path: Path | None = None
    if render:
        audio_path = render_dialog(script, out_dir / "dialog.mp3")

    return {
        "script": script,
        "script_path": str(script_path),
        "audio_path": str(audio_path) if audio_path else None,
    }


# --- Event-synced render + reel orchestration -------------------------------

def render_timed_dialog(
    structured: dict[str, Any],
    chart: dict[str, Any],
    *,
    fps: int,
    provisional_duration: float,  # unused now; kept for signature stability
    out_path: Path,
    turn_gap_ms: int = 140,
    beat_pad_ms: int = 250,
) -> tuple[Path, float, list[dict[str, Any]]]:
    """Voice hook/beats/outro back-to-back (no dead air), then build a
    variable-speed **draw schedule** so each event's candle is reached exactly
    when its beat starts. Mutates ``chart`` with ``keyframes`` and returns
    ``(path, duration_s, schedule)``. The reel length == the spoken length."""
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError("pydub not installed — run: pip install pydub (needs ffmpeg)") from exc

    out_path = Path(out_path)
    seg_dir = out_path.parent / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)

    def _voice_group(name: str, turns: list[dict[str, str]]):
        clip = AudioSegment.empty()
        gap = AudioSegment.silent(duration=turn_gap_ms)
        for j, turn in enumerate(turns):
            spk = _speaker(turn["speaker"])
            seg = seg_dir / f"{name}_{j:02d}_{spk.name.lower()}.mp3"
            log.info("voicing %s turn %d/%d — %s", name, j + 1, len(turns), spk.name)
            _tts_segment(turn["text"], spk, seg)
            clip += AudioSegment.from_file(seg)
            if j < len(turns) - 1:
                clip += gap
        return clip

    pad = AudioSegment.silent(duration=beat_pad_ms)  # small breath between beats
    hook_clip = _voice_group("hook", structured["hook"])
    beat_clips = [
        _voice_group(f"beat{b['event_index']:02d}", b["turns"]) if b["turns"] else AudioSegment.silent(duration=600)
        for b in structured["beats"]
    ]
    outro_clip = _voice_group("outro", structured["outro"]) if structured["outro"] else AudioSegment.empty()

    points = chart["points"]
    n = len(points)
    idxs = _event_point_indices(chart["events"], points)

    # Continuous timeline: hook, then each beat back-to-back, then outro.
    base = AudioSegment.silent(duration=0)
    base += hook_clip + pad
    beat_starts: list[float] = []
    for clip in beat_clips:
        beat_starts.append(len(base) / 1000)  # seconds at which this beat begins
        base += clip + pad
    outro_start = len(base) / 1000
    base += outro_clip
    duration = len(base) / 1000

    # Build the draw schedule: the line should reach event k's candle (idx_k)
    # exactly at beat_starts[k]. Enforce strictly-increasing idx + time so the
    # piecewise-linear draw is monotonic. Start at (0,0); finish drawing the
    # tail during the outro so the last candle isn't frozen too early.
    hold_s = _RENDER_HOLD_S
    keyframes: list[dict[str, float]] = [{"t": 0.0, "idx": 0.0}]
    prev_idx = 0.0
    prev_t = 0.0
    for k, idx in enumerate(idxs):
        t = max(beat_starts[k], prev_t + 0.2)
        fidx = float(idx)
        if fidx <= prev_idx:
            fidx = prev_idx + 1.0
        fidx = min(fidx, float(n - 1))
        keyframes.append({"t": round(t, 3), "idx": round(fidx, 3)})
        prev_idx, prev_t = fidx, t
    end_draw = max(prev_t + 0.5, duration - hold_s)
    if prev_idx < n - 1:
        keyframes.append({"t": round(end_draw, 3), "idx": float(n - 1)})
    chart["keyframes"] = keyframes

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.export(out_path, format="mp3")
    log.info("timed dialogue → %s (%.1fs, %d beats, schedule-driven)", out_path, duration, len(beat_clips))

    schedule = [{"group": "hook", "start_s": 0.0, "dur_s": round(len(hook_clip) / 1000, 2)}]
    for k, clip in enumerate(beat_clips):
        ev = chart["events"][k]
        schedule.append({
            "group": f"beat{k}", "start_s": round(beat_starts[k], 2), "dur_s": round(len(clip) / 1000, 2),
            "pin_at_s": round(keyframes[k + 1]["t"], 2),
            "event": str(ev.get("title") or "")[:70], "t": ev.get("t"),
        })
    schedule.append({"group": "outro", "start_s": round(outro_start, 2), "dur_s": round(len(outro_clip) / 1000, 2)})

    for f in seg_dir.glob("*.mp3"):
        f.unlink()
    if seg_dir.exists() and not any(seg_dir.iterdir()):
        seg_dir.rmdir()
    return out_path, duration, schedule


def make_dialog_reel(
    *,
    ticker: str,
    window_days: int = 35,
    interval: str = "1hour",
    max_events: int = 6,
    theme: str = "midnight",
    fps: int = 30,
    provisional_duration: float = 85.0,
    hook_words: int = 24,
    outro_words: int = 28,
    out_dir: Path,
    model: str | None = None,
    extra_direction: str | None = None,
) -> dict[str, Any]:
    """Build an event-synced reel + voice-over for ``ticker``.

    Pulls an intraday price chart and its plotted news events, writes a Nami×Luffy
    script with one beat per event, lays the audio on a timeline locked to each
    pin's on-screen moment, sizes the reel to that audio, and returns the spec +
    timed dialogue (the CLI writes spec.json, renders, and muxes the audio in).
    """
    from . import spec as spec_mod

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chart = ds.price_history(ticker, window_days=window_days, interval=interval)
    chart["events"] = ds.news_events(
        ticker, window_days=window_days, max_events=max_events, points=chart["points"]
    )
    chart = ds.anchor_events_to_points(chart)
    if not chart["events"]:
        raise RuntimeError(f"no plottable news events for {ticker} in the last {window_days}d")

    structured = generate_synced_dialog(
        chart, fps=fps, provisional_duration=provisional_duration,
        hook_words=hook_words, outro_words=outro_words,
        model=model, extra_direction=extra_direction,
    )

    audio_path, duration, schedule = render_timed_dialog(
        structured, chart, fps=fps, provisional_duration=provisional_duration,
        out_path=out_dir / "dialog.mp3",
    )

    spec = spec_mod.build_price_news_spec(
        chart=chart,
        theme=theme,
        title=f"<EDIT: did the news move {ticker.upper()}?>",
        subtitle=f"Price vs. AI-scored headlines · last {window_days} days",
        outro_title="<EDIT: the takeaway>",
        outro_takeaway="<EDIT: which headlines moved it>",
        format_overrides={"fps": fps, "durationInSeconds": round(duration, 2)},
    )

    (out_dir / "dialog_script.json").write_text(
        json.dumps({"structured": structured, "schedule": schedule}, indent=2)
    )
    return {
        "spec": spec,
        "duration_s": round(duration, 2),
        "schedule": schedule,
        "audio_path": str(audio_path),
        "script_path": str(out_dir / "dialog_script.json"),
    }
