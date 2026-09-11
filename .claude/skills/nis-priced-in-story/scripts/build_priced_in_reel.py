#!/usr/bin/env python3
"""
build_priced_in_reel.py — voice the priced-in scenes into a postable reel.

Narrates each scene from `animate_priced_in.py` with its OWN line, stretches that
scene's video to that line's duration, and concatenates — so the beat where the
price stops believing something lands on the words that say so. A single clip
stretched to one long voiceover drifts by several seconds before the end, which
is exactly where the payoff is.

    cd code/analytics
    .venv/bin/python ../../.claude/skills/nis-priced-in-story/scripts/build_priced_in_reel.py --ticker ONON
    # options: --voice-id <id>  --tempo 1.06  --no-disclaimer

Reads   output/setups/priced-in/<TICKER>/vo.json  (+ the scene mp4s beside it)
Writes  output/setups/priced-in/<TICKER>/reel.mp4         ← what social_publishing posts
        output/setups/priced-in/<TICKER>/reel_poster.png
        output/setups/priced-in/<TICKER>/vo_script.txt    ← the narration, as read

The reel closes on a disclaimer card. This is a reconstruction of what a price
already contains, not a recommendation, and the card says so in the video itself
rather than only in the caption — a caption is collapsed by default.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                          # noqa: E402
from matplotlib.patches import FancyBboxPatch            # noqa: E402

BG = "#0A0E1A"; INK = "#F5F7FF"; MUT = "#9AA3BC"; MUT2 = "#6B7488"; AMBER = "#F5A623"
W, H, FPS = 1080, 1920, 30
ELEVEN_MODEL = "eleven_multilingual_v2"
ELEVEN_FORMAT = "mp3_44100_128"
# The narrator for this series. Overridable per run, but consistency across the
# catalogue is most of what makes a series feel like one.
DEFAULT_VOICE = "VCgLBmBjldJmfphyB8sZ"

ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-c:a", "aac", "-ar", "44100", "-b:a", "160k", "-vsync", "cfr"]


def _analytics() -> pathlib.Path:
    for p in pathlib.Path(__file__).resolve().parents:
        if (p / "code" / "analytics").exists():
            return p / "code" / "analytics"
    return pathlib.Path.cwd()


ANALYTICS = _analytics()
for _l in ((ANALYTICS / ".env").read_text().splitlines()
           if (ANALYTICS / ".env").exists() else []):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _, _v = _l.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def tts(text: str, out_path: pathlib.Path, voice: str, cache: pathlib.Path | None = None) -> None:
    """Synthesise a line, reusing a cached take of the identical (voice, text).

    Visual iteration is the normal case here — a row that clips, a chip that
    overflows — and re-rendering the video should not re-bill and re-roll the
    narration each time. Keyed on the text AND the voice, so changing either
    still produces a fresh take."""
    if cache is not None:
        import hashlib                                       # noqa: PLC0415
        key = hashlib.sha1(f"{voice}\n{text}".encode()).hexdigest()[:16]
        hit = cache / f"{key}.mp3"
        if hit.exists():
            shutil.copyfile(hit, out_path)
            return
        _tts_call(text, out_path, voice)
        cache.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_path, hit)
        return
    _tts_call(text, out_path, voice)


def _tts_call(text: str, out_path: pathlib.Path, voice: str) -> None:
    from elevenlabs.client import ElevenLabs                  # noqa: PLC0415
    audio = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"]).text_to_speech.convert(
        voice_id=voice, text=text, model_id=ELEVEN_MODEL, output_format=ELEVEN_FORMAT,
        voice_settings={"stability": 0.5, "similarity_boost": 0.75, "style": 0.3,
                        "use_speaker_boost": True})
    out_path.write_bytes(b"".join(audio))


def dur(path: pathlib.Path | str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def disclaimer_card(path: pathlib.Path, ticker: str) -> None:
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.text(0.075, 0.79, "PRICED IN", color=AMBER, fontsize=24, family="monospace",
            fontweight="bold", va="center")
    ax.text(0.075, 0.70, "Not financial", color=INK, fontsize=62, fontweight="bold", va="center")
    ax.text(0.075, 0.635, "advice.", color=INK, fontsize=62, fontweight="bold", va="center")
    ax.text(0.075, 0.545,
            "A reconstruction of what the price already\n"
            "contains — arithmetic over published analyst\n"
            "models, not a forecast and not a target. The\n"
            "reading can be right and the stock can still\n"
            "fall. Do your own research.",
            color=MUT, fontsize=27, va="top", linespacing=1.6)
    # sized to the longest ticker this will ever carry: the chip is drawn from
    # the text width rather than a constant, so a 5-letter symbol cannot clip it
    label = f"newsimpactscreener.com/quote/{ticker}"
    chip_w = min(0.85, 0.052 + 0.0175 * len(label))
    ax.add_patch(FancyBboxPatch((0.075, 0.345), chip_w, 0.055, boxstyle="round,pad=0.008",
                                fc=AMBER, ec="none", mutation_aspect=0.5))
    ax.text(0.075 + chip_w / 2, 0.3725, label, color="#0A0E1A",
            fontsize=21, fontweight="bold", ha="center", va="center")
    ax.text(0.075, 0.295, "@newsimpactscreener", color=MUT2, fontsize=20, va="center")
    fig.savefig(path, facecolor=BG); plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Voice a priced-in reel.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--voice-id", default=None, help=f"ElevenLabs voice (default {DEFAULT_VOICE})")
    ap.add_argument("--tempo", type=float, default=1.0, help="speed the narration up (1.05 is brisk)")
    ap.add_argument("--no-disclaimer", action="store_true")
    ap.add_argument("--no-cache", action="store_true",
                    help="re-synthesise every line instead of reusing cached takes")
    ap.add_argument("--dir", default=None)
    args = ap.parse_args()

    t = args.ticker.upper()
    d = pathlib.Path(args.dir) if args.dir else ANALYTICS / "output" / "setups" / "priced-in" / t
    vo_path = d / "vo.json"
    if not vo_path.exists():
        sys.exit(f"no vo.json at {vo_path} — run animate_priced_in.py --ticker {t} first")
    plan = json.loads(vo_path.read_text())

    voice = (args.voice_id or os.environ.get("NIS_PRICED_IN_VOICE_ID") or DEFAULT_VOICE).strip()
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("need ELEVENLABS_API_KEY in code/analytics/.env")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"pireel_vo_{t}_"))
    segs, script = [], []
    try:
        scenes = list(plan["scenes"])
        if not args.no_disclaimer:
            card = tmp / "disclaimer.png"
            disclaimer_card(card, t)
            scenes.append({"name": "disclaimer", "video": str(card), "still": True,
                           "vo": "This is a reconstruction of what the price already contains — "
                                 "not financial advice. Do your own research."})

        for i, sc in enumerate(scenes):
            print(f"[{i+1}/{len(scenes)}] voicing {sc['name']}…", flush=True)
            au = tmp / f"vo_{i}.mp3"
            tts(sc["vo"], au, voice, cache=None if args.no_cache else d / ".vo_cache")
            script.append(sc["vo"])
            # 0.35s of air after each line, so beats do not run into each other
            length = dur(au) / args.tempo + 0.35
            seg = tmp / f"seg_{i:02d}.mp4"
            if sc.get("still"):
                frames = max(1, round(length * FPS))
                vf = (f"scale=3240:5760,zoompan=z='min(zoom+0.0004,1.03)':d={frames}:"
                      f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps={FPS}:s={W}x{H}")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                                "-i", sc["video"], "-i", str(au), "-filter_complex",
                                f"[0:v]{vf}[v];[1:a]atempo={args.tempo:.3f},apad[a]",
                                "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
                                *ENC, str(seg)], check=True)
            else:
                # stretch THIS scene to THIS line: the ledger row that appears on
                # the word "refuses" has to appear on the word "refuses"
                factor = length / max(dur(sc["video"]), 0.1)
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", sc["video"],
                                "-i", str(au), "-filter_complex",
                                f"[0:v]setpts=PTS*{factor:.4f},fps={FPS}[v];"
                                f"[1:a]atempo={args.tempo:.3f},apad[a]",
                                "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
                                *ENC, str(seg)], check=True)
            segs.append(seg)

        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{s}'\n" for s in segs))
        out = d / "reel.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(out)], check=True)
        # The cover is the SETTLED number scene: a fixed 1.2s landed mid count-up
        # once that scene stretched to its narration, and GOOGL's cover read
        # $286.62 — a price the stock never had on the as-of date.
        poster_t = max(dur(segs[0]) - 0.3, 0.0)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{poster_t:.2f}", "-i", str(out),
                        "-frames:v", "1", str(d / "reel_poster.png")], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    (d / "vo_script.txt").write_text("\n\n".join(script) + "\n")
    print(f"\nreel   → {out}  ({dur(out):.0f}s, voice {voice})")
    print(f"poster → {d / 'reel_poster.png'}")
    print(f"script → {d / 'vo_script.txt'}")
    print(f"\nnext: write {d / 'caption.txt'}, then\n"
          f"  .venv/bin/python -m services.social_publishing.cli publish "
          f"--ticker priced-in/{t} --platforms instagram --dry-run")


if __name__ == "__main__":
    main()
