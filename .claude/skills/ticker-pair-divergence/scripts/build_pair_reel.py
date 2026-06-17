#!/usr/bin/env python3
"""
build_pair_reel.py — voice the ticker-pair divergence animation into a reel.

Narrates the pair_story animation (hook → stats → divergence/setup → takeaway)
with ElevenLabs, time-stretches the animation to the narration so the comments
track the visuals, and closes on a disclaimer card.

Run from code/analytics (needs pair.json + pair_story.mp4):
  cd code/analytics
  .venv/bin/python ../../.claude/skills/ticker-pair-divergence/scripts/build_pair_reel.py --pair DNUT/MCD
→ output/setups/pairs/<A>_<B>/reel.mp4
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

BG = "#0A0E1A"; INK = "#F5F7FF"; MUT = "#9AA3BC"; MUT2 = "#6B7488"; AMBER = "#F5A623"
W, H, FPS = 1080, 1350, 30
ELEVEN_MODEL = "eleven_multilingual_v2"; ELEVEN_FORMAT = "mp3_44100_128"


def _analytics():
    here = pathlib.Path(__file__).resolve()
    for p in here.parents:
        if (p / "code" / "analytics").exists():
            return p / "code" / "analytics"
    return pathlib.Path.cwd()


ANALYTICS = _analytics()
for line in (ANALYTICS / ".env").read_text().splitlines() if (ANALYTICS / ".env").exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def short_name(name: str) -> str:
    return re.sub(r",?\s+(Inc|Corp|Corporation|Company|Co|Holdings|Ltd|plc|Group)\.?$", "",
                  (name or "").strip(), flags=re.I).strip() or name


def pair_vo(S: dict) -> str:
    A, B, st, tr, rel = S["a"], S["b"], S["stats"], S["trade"], S["relationship"]
    na, nb = short_name(A["name"]), short_name(B["name"])
    hl = st.get("half_life_days"); z = abs(st.get("current_zscore") or 0)
    parts = [f"Here's a pair almost nobody connects: {na} and {nb} — {rel['phrase']}. The prices barely "
             f"look related... until you measure the spread between them."]
    if st.get("is_cointegrated") and hl:
        parts.append(f"It's cointegrated, with an {hl:.0f}-day half-life: stretch apart, snap back.")
    elif hl:
        parts.append(f"They mean-revert, with an {hl:.0f}-day half-life.")
    setup_word = "the trade is live" if tr.get("actionable") else "a setup is forming"
    parts.append(f"Right now they've stretched to {z:.1f} sigma — {setup_word}: long {tr['long']}, "
                 f"short {tr['short']}, betting the gap snaps back.")
    parts.append("Few people watch these relationships. The screener does.")
    return " ".join(parts)


def disclaimer_card(path, pair):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(Rectangle((0.08, 0.78), 0.03, 0.04, color=AMBER))
    ax.text(0.135, 0.79, "PAIRS TRADE", color=AMBER, fontsize=20, fontweight="bold", va="center")
    ax.text(0.08, 0.64, "Not financial", color=INK, fontsize=66, fontweight="bold")
    ax.text(0.08, 0.555, "advice.", color=INK, fontsize=66, fontweight="bold")
    ax.text(0.08, 0.44,
            "For education only. Cointegration breaks. A\nspread can keep stretching before it reverts —\nor never revert at all. Size for that, and do\nyour own research.",
            color=MUT, fontsize=24, va="top", linespacing=1.5)
    ax.add_patch(FancyBboxPatch((0.08, 0.20), 0.52, 0.06, boxstyle="round,pad=0.008",
                                fc=AMBER, ec="none", mutation_aspect=0.5))
    ax.text(0.34, 0.23, "newsimpactscreener.com", color="#0A0E1A", fontsize=22, fontweight="bold",
            ha="center", va="center")
    ax.text(0.08, 0.11, "@newsimpactscreener", color=MUT2, fontsize=18)
    fig.savefig(path, facecolor=BG); plt.close(fig)


def tts(text, out_path, voice):
    from elevenlabs.client import ElevenLabs
    audio = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"]).text_to_speech.convert(
        voice_id=voice, text=text, model_id=ELEVEN_MODEL, output_format=ELEVEN_FORMAT,
        voice_settings={"stability": 0.5, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True})
    out_path.write_bytes(b"".join(audio))


def dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-ar", "44100", "-b:a", "160k", "-vsync", "cfr"]


def main():
    ap = argparse.ArgumentParser(description="Voice a ticker-pair divergence reel.")
    ap.add_argument("--pair", required=True)
    ap.add_argument("--voice-id", default=None)
    ap.add_argument("--tempo", type=float, default=1.0)
    args = ap.parse_args()

    a, b = args.pair.replace(",", "/").split("/")
    a, b = (a.upper(), b.upper()) if a.upper() < b.upper() else (b.upper(), a.upper())
    d = ANALYTICS / "output" / "setups" / "pairs" / f"{a}_{b}"
    S = json.loads((d / "pair.json").read_text())
    voice = (args.voice_id or os.environ.get("ELEVENLABS_PRIMARY_VOICE_ID") or os.environ.get("ELEVENLABS_VOICE_ID") or "")
    voice = voice.split("#")[0].split()[0] if voice.strip() else ""
    if not voice or not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("need ELEVENLABS_API_KEY + a voice id (env or .env)")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"pairreel_{a}_{b}_"))
    disc = tmp / "disc.png"; disclaimer_card(disc, f"{a}/{b}")

    scenes = [{"v": str(d / "pair_story.mp4"), "text": pair_vo(S), "video": True},
              {"v": str(disc), "text": "Not financial advice — education only. Do your own research."}]
    segs = []
    for i, sc in enumerate(scenes):
        au = tmp / f"vo_{i}.mp3"; print(f"[{i+1}/{len(scenes)}] voicing…", flush=True)
        tts(sc["text"], au, voice)
        eff = dur(au) / args.tempo
        seg = tmp / f"seg_{i}.mp4"
        if sc.get("video"):
            vlen = max(eff + 0.4, 0.1); factor = vlen / max(dur(sc["v"]), 0.1)
            subprocess.run(["ffmpeg", "-y", "-i", sc["v"], "-i", str(au), "-filter_complex",
                            f"[0:v]setpts=PTS*{factor:.4f},scale={W}:{H},fps={FPS}[v];[1:a]atempo={args.tempo:.3f},apad[a]",
                            "-map", "[v]", "-map", "[a]", "-t", f"{vlen:.3f}", *ENC, str(seg)], check=True, capture_output=True)
        else:
            t = eff + 0.4; frames = max(1, round(t * FPS))
            vf = (f"scale=3240:4050,zoompan=z='min(zoom+0.0005,1.04)':d={frames}:x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':fps={FPS}:s={W}x{H}")
            subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", sc["v"], "-i", str(au), "-filter_complex",
                            f"[0:v]{vf}[v];[1:a]atempo={args.tempo:.3f},apad[a]", "-map", "[v]", "-map", "[a]",
                            "-t", f"{t:.3f}", *ENC, str(seg)], check=True, capture_output=True)
        segs.append(seg)

    lst = tmp / "l.txt"; lst.write_text("".join(f"file '{s}'\n" for s in segs))
    out = d / "reel.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)],
                   check=True, capture_output=True)
    import shutil; shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nreel: {out}  ({dur(out):.1f}s)\nvo: {pair_vo(S)}")


if __name__ == "__main__":
    main()
