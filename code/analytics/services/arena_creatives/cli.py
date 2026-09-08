"""
arena_creatives.cli — the weekly arena broadcast package.

The ``nis-arena-report`` skill drives these; they also run by hand.

    cd code/analytics

    # What's the table, and what's the story on it?
    python -m services.arena_creatives.cli standings
    python -m services.arena_creatives.cli storylines

    # The two assets
    python -m services.arena_creatives.cli table --ratios 4x5,9x16
    python -m services.arena_creatives.cli race

    # Everything, one command (what the skill runs)
    python -m services.arena_creatives.cli package

    # Re-render an edited spec
    python -m services.arena_creatives.cli render output/arena/<season>/<date>/race/spec.json

Output convention — one dated folder per publication, per season::

    output/arena/<championship-slug>/<YYYY-MM-DD>/
        standings.json          the table, with movement + form
        storylines.json         every hook the table supports, best first
        table/spec.<ratio>.json + table/<ratio>/table.png
        race/spec.json          + race/race.mp4

Assets go out through the existing publisher's ad-hoc mode — no per-ticker
folder is involved, so nothing in ``social_publishing`` needed changing::

    python -m services.social_publishing.cli publish --ticker ARENA \
        --media output/arena/<season>/<date>/race/race.mp4 \
        --caption-file output/arena/<season>/<date>/caption.txt \
        --platforms instagram,tiktok --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import subprocess
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent
# The arena compositions live in the repo's single Remotion project; see the
# note in spec.py for why there is not a second one.
_REEL_DIR = _ANALYTICS / "services" / "viral_reels" / "reel"
_OUT_DIR = _ANALYTICS / "output" / "arena"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ANALYTICS / ".env")
sys.path.insert(0, str(_ANALYTICS))

from services.arena_creatives import commentary as cm  # noqa: E402
from services.arena_creatives import data_sources as ds  # noqa: E402
from services.arena_creatives import spec as spec_mod  # noqa: E402
from services.arena_creatives import storylines as sl  # noqa: E402


def _emit(obj, out: str | None) -> None:
    text = json.dumps(obj, indent=2, default=str)
    if out:
        p = pathlib.Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        print(f"wrote {p}")
    else:
        print(text)


def _run_dir(standings: dict, override: str | None = None) -> pathlib.Path:
    """``output/arena/<season>/<as-of date>/``.

    Keyed on the table's own as-of session rather than today, so re-running the
    package on a Monday for Friday's close overwrites Friday's folder instead of
    silently minting a second, identical one under a new date.
    """
    if override:
        return pathlib.Path(override)
    season = standings["championship"].get("slug") or "season"
    day = standings.get("asOf") or date.today().isoformat()
    return _OUT_DIR / str(season) / str(day)


def _render(spec: dict, spec_path: pathlib.Path, out_path: pathlib.Path, force: bool = False) -> None:
    problems = spec_mod.validate(spec)
    if problems and not force:
        print("Refusing to render an invalid spec (use --force to override):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    for p in problems:
        log.warning("spec problem (forced): %s", p)

    if not (_REEL_DIR / "node_modules").exists():
        print(f"Remotion deps not installed. Run:\n  cd {_REEL_DIR} && npm install", file=sys.stderr)
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Remotion merges input props over the composition's defaults, so the props
    # file must carry the component's prop shape ({"spec": ...}) — handing it a
    # bare spec loses to the defaults and renders the sample.
    props_path = spec_path.parent / "_remotion_props.json"
    props_path.write_text(json.dumps({"spec": spec}))

    verb = "still" if spec_mod.is_still(spec) else "render"
    cmd = ["npx", "remotion", verb, "src/index.ts", spec_mod.composition_for(spec),
           str(out_path), f"--props={props_path}"]
    log.info("rendering: %s (cwd=%s)", " ".join(cmd), _REEL_DIR)
    result = subprocess.run(cmd, cwd=_REEL_DIR)
    if result.returncode != 0:
        sys.exit(result.returncode)
    print(f"rendered {out_path}")


def _mux(video: pathlib.Path, audio: pathlib.Path) -> pathlib.Path:
    """Lay the mixed track onto the render, as a sibling ``race_audio.mp4``.

    The silent render is kept: it is the one to re-cut against if the
    commentary is rewritten, and re-rendering 660 frames to change a sentence is
    a waste of several minutes.
    """
    out = video.with_name(video.stem + "_audio.mp4")
    cmd = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-map", "0:v:0", "-map", "1:a:0", str(out)]
    log.info("muxing audio: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"audio mux failed: {r.stderr[-500:]}", file=sys.stderr)
        sys.exit(r.returncode)
    print(f"muxed {out}")
    return out


def _commentary(standings, race, story, args) -> tuple[list, list[dict]]:
    """Beats + the captions derived from them.

    Only the beats tied to a SESSION become captions. The opener and the result
    are spoken over the intro and the outro, where the picture is already
    saying the same thing — captioning them there would double the words on
    screen and collide with the title card.
    """
    total = float(args.duration or spec_mod.RACE_FORMAT["durationInSeconds"])
    beats = cm.build_beats(standings, race, story=story, total_seconds=total,
                           max_beats=args.max_beats)
    if getattr(args, "script", None):
        beats = cm.load_script(args.script, beats, total)
    for w in cm.check_overruns(beats, total):
        log.warning("commentary: %s", w)
    captions = [b.to_caption() for b in beats if b.session_index is not None]
    return beats, captions


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_standings(args):
    st = ds.build_standings(
        championship_slug=args.championship,
        form_len=args.form,
        move_lookback=args.lookback,
    )
    if args.json or args.out:
        _emit(st, args.out)
        return
    champ = st["championship"]
    print(f"\n{champ['name']}  ·  matchday {st['sessions']}  ·  as of {st['asOf']}\n")
    print(f"{'#':<3} {'AGENT':<20} {'NAV':>10} {'RET':>8} {'DD':>7} {'FORM':<7} {'MOVE':>5}")
    print("-" * 66)
    for r in st["rows"]:
        mv = "" if r["move"] is None else ("=" if r["move"] == 0 else f"{'+' if r['move'] > 0 else ''}{r['move']}")
        print(
            f"{r['rank']:<3} {str(r['name'])[:20]:<20} ${r['nav']:>9,.0f} "
            f"{r['return'] * 100:>7.2f}% {r['drawdown'] * 100:>6.1f}% "
            f"{''.join(r['form']):<7} {mv:>5}"
        )
    print()


def cmd_storylines(args):
    st = ds.build_standings(championship_slug=args.championship, move_lookback=args.lookback)
    found = sl.detect(st)
    if args.json or args.out:
        _emit(found, args.out)
        return
    for c in found:
        print(f"[{c['priority']:>3}] {c['key']}")
        print(f"      {c['headline']}")
        print(f"      {c['detail']}\n")


def cmd_commentary(args):
    """The beat sheet: what gets said, and the second of the reel it lands on."""
    st = ds.build_standings(championship_slug=args.championship, move_lookback=args.lookback)
    race = ds.build_race_keyframes(championship_slug=args.championship,
                                   max_keyframes=args.max_keyframes)
    story = sl.headline(st, prefer=args.story)
    beats, _ = _commentary(st, race, story, args)
    if args.json or args.out:
        _emit(cm.beats_to_json(beats), args.out)
        return
    total = float(args.duration or spec_mod.RACE_FORMAT["durationInSeconds"])
    v = cm.active_voice()
    print(f"\n{len(beats)} beats over {total:.0f}s "
          f"(voice: {v.name} {v.voice_id}, {v.words_per_sec:.1f} spoken words/sec)\n")
    for b in beats:
        # SPOKEN words, the same measure the budget uses — printing the written
        # count here made lines look over budget when they were not.
        print(f"  {b.at_seconds:>5.1f}s  [{b.key}]  "
              f"({cm.spoken_words(b.text)}/{b.word_budget} spoken words)")
        print(f"          {b.text}\n")
    cov = cm.speech_coverage(beats, total)
    print(f"  speech coverage ≈ {cov * 100:.0f}% of {total:.0f}s"
          + ("" if cov >= 0.7 else "   ← thin; raise --max-beats or shorten --duration"))
    for w in cm.check_overruns(beats, total):
        print(f"  ! {w}")
    print("\nOverride any line with a JSON file of {beat key: text} and --script.")


def cmd_table(args):
    st = ds.build_standings(
        championship_slug=args.championship, form_len=args.form, move_lookback=args.lookback
    )
    story = sl.headline(st, prefer=args.story)
    run = _run_dir(st, args.out_dir)
    ratios = [r.strip() for r in (args.ratios or "4x5").split(",") if r.strip()]

    for ratio in ratios:
        s = spec_mod.build_table_spec(
            st, story=story, ratio=ratio, theme=args.theme, title=args.title, hook=args.hook
        )
        spec_path = spec_mod.dump(s, run / "table" / f"spec.{ratio}.json")
        print(f"wrote {spec_path}")
        if not args.no_render:
            _render(s, spec_path, run / "table" / ratio / "table.png", force=args.force)

    _emit(st, str(run / "standings.json"))
    print(f"\nstory: {story['headline']}")


def cmd_race(args):
    st = ds.build_standings(
        championship_slug=args.championship, form_len=args.form, move_lookback=args.lookback
    )
    race = ds.build_race_keyframes(
        championship_slug=args.championship, max_keyframes=args.max_keyframes
    )
    story = sl.headline(st, prefer=args.story)
    run = _run_dir(st, args.out_dir)

    beats, captions = ([], [])
    if args.voice or args.music or args.captions:
        beats, captions = _commentary(st, race, story, args)
        _emit(cm.beats_to_json(beats), str(run / "race" / "beats.json"))

    s = spec_mod.build_race_spec(
        st, race, story=story, theme=args.theme, title=args.title,
        duration_seconds=args.duration,
        captions=captions if args.captions else None,
    )
    spec_path = spec_mod.dump(s, run / "race" / "spec.json")
    print(f"wrote {spec_path}")
    video = run / "race" / "race.mp4"
    if not args.no_render:
        _render(s, spec_path, video, force=args.force)

    if (args.voice or args.music) and not args.no_render:
        total = s["format"]["durationInSeconds"]
        audio = cm.build_audio(beats, run / "race", total_seconds=total,
                               with_voice=args.voice, with_music=args.music)
        if audio:
            _mux(video, audio)

    print(f"\nstory: {story['headline']}")


def cmd_package(args):
    """Standings + storylines + the still table (3 ratios) + the race."""
    st = ds.build_standings(
        championship_slug=args.championship, form_len=args.form, move_lookback=args.lookback
    )
    found = sl.detect(st)
    story = sl.headline(st, prefer=args.story)
    run = _run_dir(st, args.out_dir)

    _emit(st, str(run / "standings.json"))
    _emit(found, str(run / "storylines.json"))

    for ratio in [r.strip() for r in (args.ratios or "4x5,9x16,1x1").split(",") if r.strip()]:
        s = spec_mod.build_table_spec(
            st, story=story, ratio=ratio, theme=args.theme, title=args.title, hook=args.hook
        )
        spec_path = spec_mod.dump(s, run / "table" / f"spec.{ratio}.json")
        if not args.no_render:
            _render(s, spec_path, run / "table" / ratio / "table.png", force=args.force)

    race = ds.build_race_keyframes(
        championship_slug=args.championship, max_keyframes=args.max_keyframes
    )
    beats, captions = ([], [])
    if args.voice or args.music or args.captions:
        beats, captions = _commentary(st, race, story, args)
        _emit(cm.beats_to_json(beats), str(run / "race" / "beats.json"))

    rs = spec_mod.build_race_spec(
        st, race, story=story, theme=args.theme, title=args.title,
        duration_seconds=args.duration,
        captions=captions if args.captions else None,
    )
    rs_path = spec_mod.dump(rs, run / "race" / "spec.json")
    video = run / "race" / "race.mp4"
    if not args.no_render:
        _render(rs, rs_path, video, force=args.force)
        if args.voice or args.music:
            audio = cm.build_audio(beats, run / "race",
                                   total_seconds=rs["format"]["durationInSeconds"],
                                   with_voice=args.voice, with_music=args.music)
            if audio:
                _mux(video, audio)

    print(f"\npackage: {run}")
    print(f"story:   {story['headline']}")
    print("\nCaption is NOT written here — the skill writes caption.txt, because "
          "the words are the creative act and the numbers are not.")


def cmd_render(args):
    spec_path = pathlib.Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)
    s = spec_mod.load(spec_path)
    default = "table.png" if spec_mod.is_still(s) else "race.mp4"
    out = pathlib.Path(args.out or (spec_path.parent / default)).resolve()
    _render(s, spec_path, out, force=args.force)


def main():
    parser = argparse.ArgumentParser(description="Arena creative package (table + race)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, *, render_opts: bool = True):
        p.add_argument("--championship", help="season slug; default the running one")
        p.add_argument("--lookback", type=int, default=5,
                       help="sessions back for the movement chevron (default 5 = a week)")
        p.add_argument("--form", type=int, default=5, help="form-guide length (default 5)")
        if render_opts:
            p.add_argument("--theme", default="midnight")
            p.add_argument("--title", help="override the MATCHDAY N title")
            p.add_argument("--story", help="pin a storyline key (see `storylines`)")
            p.add_argument("--out-dir", help="override the dated output folder")
            p.add_argument("--no-render", action="store_true", help="write specs only")
            p.add_argument("--force", action="store_true", help="render despite spec problems")

    p = sub.add_parser("standings", help="the table, with movement + form")
    common(p, render_opts=False)
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_standings)

    p = sub.add_parser("storylines", help="every hook the table supports")
    common(p, render_opts=False)
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_storylines)

    p = sub.add_parser("table", help="the still league table")
    common(p)
    p.add_argument("--ratios", default="4x5", help="comma list of 4x5,9x16,1x1")
    p.add_argument("--hook", help="override the strap line")
    p.set_defaults(func=cmd_table)

    def audio_opts(p):
        p.add_argument("--voice", action="store_true",
                       help="ElevenLabs commentary, frame-locked to the beats")
        p.add_argument("--music", action="store_true",
                       help="generated music bed, ducked under the voice")
        p.add_argument("--captions", action="store_true", default=None,
                       help="burn the beats in as captions (default: on with --voice)")
        p.add_argument("--script", help="JSON {beat key: line} overriding the written lines")
        p.add_argument("--max-beats", type=int, default=8)

    p = sub.add_parser("commentary", help="the beat sheet, before rendering anything")
    common(p, render_opts=False)
    p.add_argument("--story")
    p.add_argument("--max-keyframes", type=int, default=60)
    p.add_argument("--duration", type=float)
    audio_opts(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_commentary)

    p = sub.add_parser("race", help="the league-table race reel")
    common(p)
    p.add_argument("--max-keyframes", type=int, default=60)
    p.add_argument("--duration", type=float, help="total seconds (default 22)")
    audio_opts(p)
    p.set_defaults(func=cmd_race)

    p = sub.add_parser("package", help="standings + storylines + table + race")
    common(p)
    p.add_argument("--ratios", default="4x5,9x16,1x1")
    p.add_argument("--hook")
    p.add_argument("--max-keyframes", type=int, default=60)
    p.add_argument("--duration", type=float)
    audio_opts(p)
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("render", help="re-render an edited spec")
    p.add_argument("spec")
    p.add_argument("--out")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_render)

    args = parser.parse_args()
    # Captions default to ON whenever there is a voice track: the same beats
    # have to reach the majority of viewers who watch with the sound off.
    if getattr(args, "captions", None) is None:
        args.captions = bool(getattr(args, "voice", False))
    # A voiced race needs more room than a silent one: the beats are fixed to
    # the picture, so a shorter reel does not speed the commentary up, it
    # squeezes each line into fewer words until the sentences stop being worth
    # saying. Explicit --duration still wins.
    if getattr(args, "voice", False) and not getattr(args, "duration", None):
        args.duration = 32.0
    args.func(args)


if __name__ == "__main__":
    main()
