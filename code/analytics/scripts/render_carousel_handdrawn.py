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
OPENAI_IMAGE_SIZE = "1024x1536"  # portrait 2:3, closest to 1080x1350 (4:5)
TARGET_W, TARGET_H = 1080, 1350


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


def _cover_prompt(slide: dict, index: int, total: int) -> str:
    kicker = slide.get("kicker") or ""
    title = slide["title"]
    subtitle = slide.get("subtitle") or ""
    layout = f"""\
Layout (cover slide):
- A small RED underlined kicker label near the upper area, written casually: '{kicker}' \
  (omit if empty). The underline is a single wavy red pen stroke.
- Across the middle, a LARGE hand-printed title in navy ballpoint, breaking \
  naturally across 2-3 lines: '{title}'
- Below the title, a smaller cursive subtitle in navy ink: '{subtitle}'
- A small red star/asterisk doodle next to the kicker.
- The overall look is the first idea someone scribbled to open a pitch.\
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
        # Resize from 1024x1536 (2:3) to 1080x1350 (4:5) — crop bottom slightly
        # to preserve the framing of the headline and bullets, then resize.
        src_w, src_h = img.size
        target_ratio = TARGET_W / TARGET_H  # 0.8
        src_ratio = src_w / src_h           # ~0.667
        if src_ratio < target_ratio:
            # source is taller than target — crop top+bottom
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))
        else:
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
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
