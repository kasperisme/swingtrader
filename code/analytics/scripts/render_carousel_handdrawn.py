#!/usr/bin/env python3
"""
render_carousel_handdrawn.py — regenerate an existing carousel as real
hand-drawn napkin slides via OpenAI's image API.

Reads a slides.json manifest from a previously-rendered carousel and
generates a fresh image per slide that looks like someone sketched the
idea on a white paper napkin with mixed-color ballpoint pens.

Usage:
  .venv/bin/python scripts/render_carousel_handdrawn.py <carousel_dir>

  <carousel_dir> is the timestamped folder under output/carousels/ that
  contains slides.json. Output is written to a sibling folder with a
  '_handdrawn' suffix.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import json
import os
import pathlib
import random
import sys
import time
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[2]
ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"


def _load_env(path: pathlib.Path) -> None:
    """Minimal .env loader so this script runs standalone."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env(ENV_PATH)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
OPENAI_IMAGE_QUALITY = os.environ.get("CAROUSEL_IMAGE_QUALITY", "high")
OPENAI_IMAGE_SIZE = "1024x1536"  # portrait 2:3 (gpt-image-2 native)
# Preserve full source — resize to 1080-wide, height scales to 1620.
# IG carousels render 2:3 portraits fine; cropping was lopping off
# the brand mark / swipe pill at top + bottom.
TARGET_W, TARGET_H = 1080, 1620


# ── Prompt builders ────────────────────────────────────────────────────────

STYLE_BLOCK = """\
A photograph of an idea sketched by hand on a white paper cocktail napkin. \
The napkin has soft fold creases running across it (one vertical, one \
horizontal), visible tissue-fiber texture, and a faint pale-brown coffee \
ring stain near one corner. Soft natural daylight, the napkin lies flat on \
a plain wooden cafe table just barely visible at the edges. \
Everything written on the napkin is drawn by hand with cheap ballpoint pens \
in mixed colors: deep navy blue (primary), warm red (for small labels and \
underlines), forest green (for occasional emphasis), and a touch of black. \
The handwriting is casual and slightly inconsistent — letters tilt a degree \
or two, line spacing varies, some strokes look heavier where the pen pressed \
harder, some lighter where it skipped on the tissue. Small ink bleed at the \
end of strokes. Where rectangles or circles are drawn, the lines wobble a \
little — clearly drawn freehand, not with a ruler. Absolutely no printed \
type, no computer-rendered fonts, no UI chrome, no logos beyond what is \
hand-drawn. The whole image must feel like a real photo of a real napkin.\
"""

FRAME_BLOCK = """\
Common frame elements on every napkin:
- Top-left: hand-printed brand mark 'News Impact Screener' in small navy ink, \
  next to a tiny hand-drawn flame/spark doodle.
- Top-right: page indicator '{index} / {total}' in pencil-thin navy.
- Bottom-left: tiny navy 'newsimpactscreener.com'.
- Bottom-right: small hand-drawn 'swipe →' inside a hand-sketched pill if \
  this is not the last slide, otherwise '@newsimpactscreener' written casually.\
"""


# Bank of weird, low-fidelity doodles that get dropped into the cover slide
# as an unexpected scroll-stop. Phrased as "someone's hand absentmindedly
# scribbled this in the corner while bored on the phone" — quick, lazy,
# 3-second sketches. Not detailed illustrations. Just funny enough to make
# you look twice.
WEIRD_DOODLES = [
    "a googly-eyed dollar bill with stick legs running away from a tiny down-arrow chart, with a small label 'help'",
    "a penguin wearing a tiny business suit and a clip-on tie, holding a briefcase, with a label 'CEO'",
    "a fried egg wearing sunglasses, with a tiny label 'cool egg'",
    "a worried-looking pigeon clutching a stock chart in its beak, eyes very wide",
    "a martini glass with a tiny shark fin sticking out of the liquid, label 'risk'",
    "a skull smoking a tiny pipe with a little curl of smoke",
    "a banana doing a yoga pose (sitting cross-legged), label 'zen'",
    "a tiny rocket with a flame coming out of a toilet, label 'to the moon'",
    "a stick figure on fire, grinning, giving a thumbs up, label 'this is fine'",
    "a hot dog wearing a necktie and tiny glasses, label 'analyst'",
    "a mushroom with sunglasses and a tiny smirk, label 'fungi guy'",
    "a pile of three dollar bills with cartoon eyeballs on each, all looking different directions",
    "a frog wearing a tiny crown and holding a scepter, label 'macro king'",
    "a single floating eyeball with little wings, label 'the market sees'",
    "a tiny man inside a wooden barrel rolling downhill, the hill labeled 'macro'",
    "a chicken at a tiny desk staring at a tiny laptop, label 'day trader'",
    "a confused alien holding a candle chart upside down, label 'bullish?'",
    "a sad slice of pizza with one bite missing, single tear on the cheese, label 'EPS miss'",
    "a tiny shark wearing a name tag that says 'HELLO my name is yield'",
    "a snail with a tiny rocket strapped to its shell, label 'NVDA'",
]


def _cover_prompt(slide: dict, index: int, total: int) -> str:
    kicker = slide.get("kicker") or ""
    title = slide["title"]
    subtitle = slide.get("subtitle") or ""
    doodle = random.choice(WEIRD_DOODLES)
    layout = f"""\
Layout (cover slide):
- A small RED underlined kicker label near the upper area, written casually: '{kicker}' \
  (omit if empty). The underline is a single wavy red pen stroke.
- Across the middle, a LARGE hand-printed title in navy ballpoint, breaking \
  naturally across 2-3 lines: '{title}'
- Below the title, a smaller cursive subtitle in navy ink: '{subtitle}'
- A small red star/asterisk doodle next to the kicker.

UNEXPECTED VISUAL HOOK (very important): Somewhere in an empty corner or \
margin of the napkin, draw a SMALL, SILLY, LOW-FIDELITY doodle, as if \
someone got bored and absent-mindedly scribbled it in 5 seconds while on \
the phone. The doodle is: {doodle}. \
Critical rules for this doodle: \
(1) it is TINY relative to the napkin — maybe 8-12% of the napkin width; \
(2) it is QUICK and SLOPPY, the kind of thing a kid would draw, not a \
detailed illustration — basically stick-figure level, with simple lines, \
dots for eyes, no shading; \
(3) it sits OFF to one side in white space, not overlapping the title; \
(4) it is drawn in mixed cheap ballpoint inks (blue, red, or black); \
(5) the tiny handwritten label next to it is in small messy lowercase. \
The doodle should feel completely unrelated to finance, unexpected, and \
mildly amusing — the kind of thing that makes someone pause scrolling \
because it doesn't match what they expected from a markets post.\
"""
    return f"{STYLE_BLOCK}\n\n{FRAME_BLOCK.format(index=index, total=total)}\n\n{layout}"


def _stat_prompt(slide: dict, index: int, total: int) -> str:
    kicker = slide.get("kicker") or ""
    value = slide["stat_value"]
    label = slide["stat_label"]
    context = slide.get("context") or ""
    layout = f"""\
Layout (stat slide):
- Small RED underlined kicker '{kicker}' in the upper-left area (omit if empty).
- One ENORMOUS number drawn very large in red ballpoint, taking up the \
  middle third of the napkin, slightly tilted, with a thicker pen line and \
  a thin navy shadow trace: '{value}'.
- Directly below the number, a navy hand-printed label: '{label}'.
- Below that, a smaller line of context text in navy ink: '{context}'.\
"""
    return f"{STYLE_BLOCK}\n\n{FRAME_BLOCK.format(index=index, total=total)}\n\n{layout}"


def _body_prompt(slide: dict, index: int, total: int) -> str:
    kicker = slide.get("kicker") or ""
    heading = slide["heading"]
    bullets = slide.get("bullets") or []
    body = slide.get("body") or ""
    bullet_lines = "\n".join(
        f"  {i+1}. {b}" for i, b in enumerate(bullets)
    )
    body_extra = f"\n- Below the heading, a short paragraph in navy: '{body}'" if body else ""
    bullets_block = ""
    if bullets:
        bullets_block = (
            "\n- Below the heading, a numbered list. Each bullet is preceded by a "
            "small hand-drawn squarish box containing the number, drawn in navy "
            "ballpoint with wobbly corners. The numbers are in red ink inside the "
            "boxes. The bullet text is in navy ink, with a faint dashed underline "
            "below each bullet drawn in light green:"
            f"\n{bullet_lines}"
        )
    layout = f"""\
Layout (body slide):
- RED underlined kicker '{kicker}' in upper-left (omit if empty).
- Below the kicker, a LARGE navy hand-printed heading, possibly breaking \
  across 2 lines: '{heading}'{body_extra}{bullets_block}\
"""
    return f"{STYLE_BLOCK}\n\n{FRAME_BLOCK.format(index=index, total=total)}\n\n{layout}"


def _quote_prompt(slide: dict, index: int, total: int) -> str:
    quote = slide["quote"]
    attr = slide.get("attribution") or ""
    layout = f"""\
Layout (quote slide):
- A LARGE red ballpoint open-quote mark in the upper-left of the writing area, \
  drawn at a slight tilt.
- Below the quote mark, the quote written in casual navy hand-printing, \
  breaking naturally across 3-4 lines: '{quote}'
- Below the quote, an em-dash followed by the attribution in slightly smaller \
  cursive navy ink: '{attr}'\
"""
    return f"{STYLE_BLOCK}\n\n{FRAME_BLOCK.format(index=index, total=total)}\n\n{layout}"


def _cta_prompt(slide: dict, index: int, total: int) -> str:
    kicker = slide.get("kicker") or ""
    headline = slide["headline"]
    subline = slide.get("subline") or ""
    cta = slide.get("cta_text") or ""
    layout = f"""\
Layout (CTA slide, final):
- RED underlined kicker '{kicker}' in upper-left (omit if empty).
- LARGE navy hand-printed headline, possibly across 2 lines: '{headline}'.
- Smaller navy line of supporting copy below: '{subline}'.
- Below that, a hand-drawn pill/oval button outlined in two slightly-offset \
  navy strokes (looks drawn twice for emphasis), with the URL inside in navy \
  ink and a small red arrow at the end: '{cta} →'.\
"""
    return f"{STYLE_BLOCK}\n\n{FRAME_BLOCK.format(index=index, total=total)}\n\n{layout}"


PROMPT_BUILDERS = {
    "cover": _cover_prompt,
    "stat": _stat_prompt,
    "body": _body_prompt,
    "quote": _quote_prompt,
    "cta": _cta_prompt,
}


# ── Image generation ───────────────────────────────────────────────────────

def _generate_one(slide: dict, index: int, total: int, out_path: pathlib.Path) -> tuple[int, pathlib.Path, str | None]:
    """Render one slide via OpenAI. Returns (index, path, error)."""
    from openai import OpenAI
    from PIL import Image
    from io import BytesIO

    builder = PROMPT_BUILDERS.get(slide["type"])
    if not builder:
        return index, out_path, f"unknown slide type: {slide['type']}"
    prompt = builder(slide, index, total)

    client = OpenAI(api_key=OPENAI_API_KEY)
    t0 = time.time()
    try:
        result = client.images.generate(
            model=OPENAI_IMAGE_MODEL,
            prompt=prompt,
            size=OPENAI_IMAGE_SIZE,
            quality=OPENAI_IMAGE_QUALITY,
            n=1,
        )
    except Exception as exc:
        return index, out_path, f"openai error: {exc}"

    try:
        b64 = result.data[0].b64_json
        img = Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
        # No crop — uniform resize preserving aspect ratio. Source is
        # 1024x1536 (2:3); output is 1080x1620, identical aspect.
        img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
        img.save(out_path, "PNG")
        return index, out_path, None
    except Exception as exc:
        return index, out_path, f"decode/save error: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carousel_dir", help="Path to existing carousel folder containing slides.json")
    parser.add_argument("--workers", type=int, default=4, help="Parallel image generations (default 4)")
    parser.add_argument("--out-suffix", default="_handdrawn")
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY not set (in env or .env)", file=sys.stderr)
        return 2

    src = pathlib.Path(args.carousel_dir).expanduser().resolve()
    manifest_path = src / "slides.json"
    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found", file=sys.stderr)
        return 2

    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    slides = manifest["slides"]
    total = len(slides)

    out_dir = src.parent / f"{src.name}{args.out_suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy manifest for traceability
    (out_dir / "slides.json").write_text(json.dumps(manifest, indent=2))
    caption_path = src / "caption.txt"
    if caption_path.exists():
        (out_dir / "caption.txt").write_text(caption_path.read_text())

    print(f"Generating {total} hand-drawn slides via {OPENAI_IMAGE_MODEL} (quality={OPENAI_IMAGE_QUALITY})")
    print(f"Output → {out_dir}")

    jobs = []
    for i, slide in enumerate(slides, start=1):
        out_path = out_dir / f"slide_{i:02d}.png"
        jobs.append((slide, i, total, out_path))

    errors = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(_generate_one, s, i, t, p) for s, i, t, p in jobs]
        for fut in cf.as_completed(futures):
            idx, path, err = fut.result()
            if err:
                print(f"  slide {idx:02d}: FAILED — {err}", file=sys.stderr)
                errors.append((idx, err))
            else:
                print(f"  slide {idx:02d}: ok → {path.name}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. {total - len(errors)}/{total} succeeded.")
    if errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
