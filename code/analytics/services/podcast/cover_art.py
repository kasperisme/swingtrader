"""
Podcast cover-art generation.

Pipeline:
  1. build_image_prompt(script) — deterministic prompt from episode metadata
  2. generate_ai_background(prompt) — OpenAI gpt-image-1 → PIL.Image
  3. compose_cover(...) — overlays brand text + date + title using Pillow

Graceful fallback: if OPENAI_API_KEY is missing or the API call fails for any
reason, returns a pure-Pillow typographic cover (the previous behaviour).
"""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path

from .config import (
    OPENAI_API_KEY,
    OPENAI_IMAGE_MODEL,
    OPENAI_IMAGE_QUALITY,
)

log = logging.getLogger(__name__)

# Apple Podcasts: 1400×1400 min, 3000×3000 max, square, JPEG/PNG, RGB.
# Spotify: same range, square, JPEG/PNG. We ship the recommended max.
_COVER_SIZE = 3000
_AI_SIZE = "1024x1024"          # gpt-image-1 max square output; we upscale to _COVER_SIZE
_BRAND_GOLD = (255, 215, 0)
_TEXT_WHITE = (255, 255, 255)
_TEXT_DIM = (200, 200, 200)


def _px(fraction: float) -> int:
    """Convert a fraction (0..1) of the cover side into a pixel offset."""
    return int(_COVER_SIZE * fraction)


# ── Prompt builder ─────────────────────────────────────────────────────────

def build_image_prompt(script: dict) -> str:
    """Compose a deterministic image-generation prompt from script metadata.

    Strategy: enforce a consistent visual style preset (so episodes feel like
    a coherent series) and inject only the topical theme from the LLM-written
    title + description. We explicitly forbid text in the image because gpt-image-1
    still renders text imperfectly — we'll overlay legible text in Pillow.
    """
    title = (script.get("episode_title") or "").strip()
    description = (script.get("episode_description") or "").strip()[:240]

    style = (
        "Editorial financial illustration, minimalist composition, "
        "deep navy background with rich gold and amber accents, "
        "abstract market motifs (stylised candle charts, rising lines, geometric grids), "
        "high contrast, premium magazine cover aesthetic, vector art style, "
        "no text, no letters, no numbers, no logos, no watermarks."
    )
    subject = f"Theme: {title}. {description}".strip()

    return f"{style}\n\n{subject}"


# ── OpenAI image client ────────────────────────────────────────────────────

def generate_ai_background(prompt: str):
    """Call OpenAI gpt-image-1 and return a PIL.Image.

    Returns None on any failure (missing key, network error, API error). Caller
    should fall back to a pure-Pillow cover.
    """
    if not OPENAI_API_KEY:
        log.info("Cover art: OPENAI_API_KEY not set, skipping AI background")
        return None

    try:
        from openai import OpenAI
        from PIL import Image
    except ImportError as exc:
        log.warning("Cover art: missing dependency (%s), skipping AI background", exc)
        return None

    log.info(
        "Cover art: requesting AI background (model=%s, quality=%s, size=%s, prompt=%d chars)",
        OPENAI_IMAGE_MODEL, OPENAI_IMAGE_QUALITY, _AI_SIZE, len(prompt),
    )

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        result = client.images.generate(
            model=OPENAI_IMAGE_MODEL,
            prompt=prompt,
            size=_AI_SIZE,
            quality=OPENAI_IMAGE_QUALITY,
            n=1,
        )
    except Exception as exc:
        log.warning("Cover art: OpenAI image generation failed (%s), falling back", exc)
        return None

    try:
        b64 = result.data[0].b64_json
        img = Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
        log.info("Cover art: AI background received (%dx%d)", img.width, img.height)
        return img
    except Exception as exc:
        log.warning("Cover art: failed to decode AI image (%s), falling back", exc)
        return None


# ── Hybrid composer ────────────────────────────────────────────────────────

def _draw_typographic_fallback(date_str: str, title: str):
    """Pure-Pillow cover used when AI generation is unavailable.

    Solid navy background gives a brand-consistent look without imagery.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (_COVER_SIZE, _COVER_SIZE), color=(8, 16, 32))  # deep navy
    draw = ImageDraw.Draw(img)
    return img, draw


def _load_fonts():
    """Font sizes scale proportionally with _COVER_SIZE (tuned for 1400 baseline)."""
    from PIL import ImageFont
    scale = _COVER_SIZE / 1400
    sizes = (int(72 * scale), int(48 * scale), int(36 * scale))
    try:
        return tuple(
            ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", s) for s in sizes
        )
    except OSError:
        f = ImageFont.load_default()
        return (f, f, f)


def _wrap_title(title: str, max_chars_per_line: int = 38) -> list[str]:
    words = title.split()
    lines, current = [], []
    for w in words:
        if sum(len(c) + 1 for c in current) + len(w) > max_chars_per_line:
            lines.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        lines.append(" ".join(current))
    return lines[:4]


def generate_cover_art(date_str: str, title: str, script: dict, output_path: Path) -> Path:
    """Build a 1400×1400 podcast cover.

    AI background (gpt-image-1) when available, with a darkened gradient overlay
    on top + bottom for legibility, brand text in gold, episode title in white,
    and a gold strip across the bottom carrying the URL. Falls back to a
    pure-Pillow black-background cover if AI generation isn't available.
    """
    from PIL import Image, ImageDraw

    prompt = build_image_prompt(script)
    bg = generate_ai_background(prompt)

    if bg is None:
        canvas, draw = _draw_typographic_fallback(date_str, title)
    else:
        # Upscale AI image to spec-compliant cover size.
        canvas = bg.resize((_COVER_SIZE, _COVER_SIZE), Image.LANCZOS).convert("RGBA")

        # Top + bottom gradient bands so overlaid text stays legible regardless of bg.
        overlay = Image.new("RGBA", (_COVER_SIZE, _COVER_SIZE), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        top_band = _px(0.30)
        bottom_band = _px(0.26)
        for y in range(top_band):
            alpha = int(170 * (1 - y / top_band))
            ov_draw.line([(0, y), (_COVER_SIZE, y)], fill=(0, 0, 0, alpha))
        for y in range(_COVER_SIZE - bottom_band, _COVER_SIZE):
            alpha = int(170 * ((y - (_COVER_SIZE - bottom_band)) / bottom_band))
            ov_draw.line([(0, y), (_COVER_SIZE, y)], fill=(0, 0, 0, alpha))
        canvas = Image.alpha_composite(canvas, overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)

    font_large, font_medium, font_small = _load_fonts()
    cx = _px(0.50)

    # ── Brand header ─────────────────────────────────────────────────────
    draw.text((cx, _px(0.078)), "The Impact Tape", font=font_large, fill=_BRAND_GOLD, anchor="mm")
    draw.text((cx, _px(0.139)), "Market Intelligence Digest", font=font_small, fill=_TEXT_DIM, anchor="mm")
    draw.text((cx, _px(0.193)), date_str, font=font_medium, fill=_TEXT_WHITE, anchor="mm")

    # ── Episode title (bottom band, where AI bgs are usually emptiest) ───
    title_lines = _wrap_title(title)
    line_h = _px(0.057)
    block_h = line_h * len(title_lines)
    y_start = _COVER_SIZE - _px(0.143) - block_h
    for i, line in enumerate(title_lines):
        draw.text(
            (cx, y_start + i * line_h), line,
            font=font_medium, fill=_TEXT_WHITE, anchor="mm",
        )

    # ── Bottom URL strip ────────────────────────────────────────────────
    strip_top = _px(0.929)
    strip_mid = _px(0.964)
    draw.rectangle([(0, strip_top), (_COVER_SIZE, _COVER_SIZE)], fill=_BRAND_GOLD)
    draw.text((cx, strip_mid), "newsimpactscreener.com", font=font_small, fill=(0, 0, 0), anchor="mm")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(output_path), "PNG")
    log.info(
        "Cover art saved: %s — %dx%d (%s)",
        output_path.name, _COVER_SIZE, _COVER_SIZE,
        "AI+Pillow" if bg else "Pillow-only",
    )
    return output_path
