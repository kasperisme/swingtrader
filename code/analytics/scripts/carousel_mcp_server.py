#!/usr/bin/env python3
"""
carousel_mcp_server.py — MCP server that renders Instagram carousels.

Exposes two tools over stdio MCP:

  • get_carousel_style_guide()  — returns the design + voice guide. Claude
    Code should call this BEFORE drafting slides, so the cover hook and
    copy match the swingtrader brand.

  • render_carousel(slides, ...) — renders an ordered list of slides to
    1080x1350 PNGs using a Playwright-driven HTML template that mirrors
    the app's light-mode palette (cream bg, amber primary, purple accent,
    Plus Jakarta Sans).

Content generation is intentionally NOT in this server — Claude Code is
the writer, this server is the renderer. That keeps you off the Anthropic
API and lets the model use full conversation context when drafting.

First-time setup:
  cd code/analytics
  .venv/bin/pip install playwright
  .venv/bin/playwright install chromium

Register in .mcp.json (project root) — already wired up there.
Run manually for debugging:
  .venv/bin/python scripts/carousel_mcp_server.py
"""

from __future__ import annotations

import logging
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from fastmcp import FastMCP
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

ANALYTICS_DIR = pathlib.Path(__file__).resolve().parent.parent
ASSETS_DIR = pathlib.Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS_DIR / "icon.png"
DEFAULT_OUT_DIR = ANALYTICS_DIR / "output" / "carousels"
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350


def _icon_data_uri() -> str | None:
    """Read the newsimpactscreener brand icon and return it as a base64 data
    URI so the template stays self-contained (no file:// dependency)."""
    if not ICON_PATH.exists():
        return None
    import base64
    encoded = base64.b64encode(ICON_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"

# MCP stdio uses stdout for protocol — log to stderr only.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("carousel_mcp")


# ---------------------------------------------------------------------------
# Slide schema (Pydantic discriminated union — gives Claude precise JSON Schema)
# ---------------------------------------------------------------------------

class CoverSlide(BaseModel):
    """Opening slide. Must hook the viewer in <2 seconds — it determines
    whether anyone swipes. The title must be specific to the actual content
    in the rest of the carousel, not a generic teaser."""
    type: Literal["cover"]
    title: str = Field(..., description="The hook. Max ~8 words. Specific, not generic. Earns the swipe.")
    subtitle: str | None = Field(None, description="One-line promise that pays off the hook. Max ~14 words.")
    kicker: str | None = Field(None, description="Optional short label above the title, e.g. 'PLAYBOOK' or '5 RULES'.")


class BodySlide(BaseModel):
    """A content slide. Use bullets for lists; use body for narrative.
    Pick one primary mode — don't pad with both unless the paragraph is
    a 1-line setup for the bullets."""
    type: Literal["body"]
    heading: str = Field(..., description="Slide heading. Max ~9 words.")
    body: str | None = Field(None, description="Optional paragraph. Max ~40 words. Plain language.")
    bullets: list[str] | None = Field(None, description="3-5 fragments. Each max ~12 words. Not full sentences.")
    kicker: str | None = None


class StatSlide(BaseModel):
    """One huge number that earns attention, plus context. Use sparingly —
    one per carousel max, ideally as slide 2 or as a punchline near the end."""
    type: Literal["stat"]
    stat_value: str = Field(..., description="The number. Keep short: '73%', '4.2x', '$0', '14 days'.")
    stat_label: str = Field(..., description="What the number means. Max ~6 words.")
    context: str | None = Field(None, description="One-sentence explanation. Max ~25 words.")
    kicker: str | None = None


class QuoteSlide(BaseModel):
    """Pull-quote — use only when you have a genuinely striking line."""
    type: Literal["quote"]
    quote: str = Field(..., description="The quote. Max ~30 words. No quote marks (template adds them).")
    attribution: str | None = Field(None, description="Source. Max ~5 words.")


class CTASlide(BaseModel):
    """Closing slide. Always last. Drives action — read more, save, follow."""
    type: Literal["cta"]
    headline: str = Field(..., description="The ask. Max ~7 words.")
    subline: str | None = Field(None, description="Why they should act. Max ~16 words.")
    cta_text: str | None = Field(None, description="The pill button text, e.g. 'newsimpactscreener.com'.")
    kicker: str | None = None


Slide = Annotated[
    Union[CoverSlide, BodySlide, StatSlide, QuoteSlide, CTASlide],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "carousel"


def _render(slides: list[dict], handle: str, out_dir: pathlib.Path) -> list[pathlib.Path]:
    from playwright.sync_api import sync_playwright

    env = Environment(
        loader=FileSystemLoader(str(ASSETS_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("carousel_template.html")

    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(slides)
    written: list[pathlib.Path] = []
    brand_icon = _icon_data_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": SLIDE_WIDTH, "height": SLIDE_HEIGHT},
            device_scale_factor=2,
        )
        page = context.new_page()
        for i, slide in enumerate(slides, start=1):
            html = template.render(
                slide=slide,
                index=i,
                total=total,
                handle=handle,
                brand_icon=brand_icon,
            )
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            out_path = out_dir / f"slide_{i:02d}.png"
            page.screenshot(path=str(out_path), full_page=False, omit_background=False)
            written.append(out_path)
            log.info("rendered %s (%s)", out_path.name, slide.get("type"))
        browser.close()

    return written


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("carousel-renderer")


STYLE_GUIDE = """\
# Swingtrader Instagram Carousel — Style & Voice Guide

## Audience
Retail swing traders and active investors. Smart, time-poor, allergic to
generic motivational content. They follow accounts that give them an edge,
not vibes.

## Brand voice
- Sharp, specific, plain-spoken. Plain language. No jargon without payoff.
- Concrete > abstract. Numbers, tickers, time windows where natural.
- Confidence without hype. No "TO THE MOON", no emojis, no clichés.
- Active voice. Short sentences. Fragments OK in bullets.

## Slide 1 — the cover (CRITICAL)
The opening slide decides whether anyone swipes. Get this right or
nothing else matters.

A strong cover hook is ALWAYS:
  • Grounded in the actual content of slides 2–N. Read the rest of the
    carousel first, then write the cover that previews its best idea.
    A hook that the carousel doesn't deliver on is the worst sin.
  • Specific, not generic. "5 swing-trade setups" is dead. "The pre-market
    gap pattern that pays 4-to-1" is alive.
  • Concrete with stakes. Name the thing, the number, the time window,
    the consequence. "$0 to $50K trading earnings reactions" beats
    "How I trade earnings".
  • Curiosity gap, not clickbait. The viewer should feel they'll miss
    something real if they don't swipe.

Strong cover patterns that work:
  • "[Specific claim with a number] — here's why"
  • "I [did X surprising thing]. Here's what it cost me."
  • "[Counterintuitive truth]. Most traders get this wrong."
  • "The [specific signal] that called [specific event]"
  • "Stop [doing common thing]. Do [contrarian thing] instead."

Bad cover patterns (avoid):
  • "Tips for swing trading" — generic, no stakes
  • "Things I wish I knew" — vague, no specific payoff
  • "A guide to..." — sounds like SEO content, not a hook
  • Anything that could appear on any account in any niche

## Slide structure (typical carousel)
1. COVER — the hook (must reflect what follows)
2-N. BODY / STAT / QUOTE — one idea per slide, each stands alone
LAST. CTA — drive action to newsimpactscreener.com

Sweet spot: 6-9 slides. More than 10 loses people.

## Per-slide rules
- One idea per slide. If you can't summarise the slide in one sentence,
  split it.
- No forward references ("as we'll see", "more on this later") — each
  slide must work in isolation, in case it gets reshared standalone.
- Headings: max ~9 words. Titles on cover: max ~8 words.
- Paragraphs: max ~40 words. Bullets: 3-5, each max ~12 words.
- Stat slides: pair the big number with a one-sentence "so what".

## Visual style (handled by template — do not change in content)
The aesthetic is intentionally **rough and almost handmade** — sketchbook
energy, not corporate deck. Don't fight it with overly clinical copy;
short, punchy phrases land best on this layout.
- Light mode: cream background (#FDFAF4) with a subtle paper-noise +
  dotted-paper texture, dark navy text (#0F172A)
- Amber primary (#F59E0B) for kickers, bullet numbers, swipe pill,
  doodled starburst accent
- Purple accent (#A78BFA) for gradient highlights on cover/stat + a
  hand-drawn squiggle doodle in the corner
- Handwritten fonts: **Kalam** (body / titles / headings) +
  **Caveat** (kickers, swipe, quote attribution, pager). No sans-serif.
- Hand-drawn touches: wonky asymmetric border-radius on cards, slight
  rotations (-2° to +2°) on bullets/title/CTA, offset shadow blocks (no
  blur — flat sticker-shadow), squiggle SVG underline beneath kickers,
  doodled corner accents replacing clean gradient blobs
- 1080x1350 portrait (Instagram carousel standard)

Copy implications:
- The handwritten layout amplifies any clinical/SEO-flavoured phrasing.
  Write like you're sketching a thought in a notebook, not authoring a
  whitepaper. Fragments and dashes are good.
- Avoid long uppercase blocks — handwritten caps look messy. Use
  Title Case or sentence case for headings and kickers.

## Workflow
1. Decide the ONE idea the carousel teaches. Write it as one sentence.
2. Draft slides 2-N first. They are the substance.
3. Read them back. Find the most surprising / valuable / specific
   moment in the body. That moment is the seed of the cover hook.
4. Write 3 candidate covers. Pick the one with the most specificity
   and the clearest stakes.
5. Write the CTA last. It should connect to the carousel's promise,
   not be a generic "follow us".

## Caption (the Instagram post text)
The carousel earns the swipe; the caption earns the *tap*. Always write
a caption alongside the slides and pass it to render_carousel(caption=...).

Caption rules:
- First 125 characters are the hook (Instagram cuts off there with "...more").
  Make the first line stop the scroll on its own.
- Don't repeat the cover slide verbatim. The caption should ADD context —
  the deeper number, the second beat, the so-what.
- Length: 4-7 short paragraphs. White space between them. Mobile-readable.
- Close with: one-line "swipe" prompt → the CTA → 8-14 hashtags on a
  separate line. Mix big tags (#stocks, #investing) with niche
  (#swingtrading, #MSFT) and topical (#OpenAI, #AI) for reach.
- No emojis. No "🚨". No "👇". Plain text.

Strong caption opener patterns:
  • A single shocking fact: "$1 billion promised. $38 million paid."
  • A specific date/scene: "Monday morning. Oakland. A jury decides..."
  • A reversal: "They were co-founders in 2015. Today they're rivals in court."
  • A line that sounds like a leaked text: "'I will no longer fund OpenAI.'"

## Before calling render_carousel
- Cover hook earned by the body content? (If not, rewrite.)
- Every body slide passes the "would I swipe past this?" test?
- CTA gives a concrete next step, not "follow for more"?
- Caption drafted? First 125 chars hook? Hashtags ready?
"""


@mcp.tool
def get_carousel_style_guide() -> str:
    """Return the swingtrader carousel style + voice guide. Call this FIRST
    before drafting any carousel content. The guide covers the brand voice,
    audience, slide structure, per-slide rules, and (most importantly) what
    makes a strong content-grounded cover hook vs a weak generic one."""
    return STYLE_GUIDE


@mcp.tool
def render_carousel(
    slides: list[Slide],
    topic: str = "carousel",
    handle: str = "@newsimpactscreener",
    caption: str | None = None,
    out_dir: str | None = None,
) -> dict:
    """Render an Instagram carousel from structured slide content.

    The slides list MUST start with a CoverSlide and end with a CTASlide.
    Middle slides can be any mix of BodySlide, StatSlide, QuoteSlide.

    Before calling this, you should have already called
    get_carousel_style_guide() and drafted slides that satisfy its rules —
    especially the rule that the cover hook must be grounded in the
    actual body content. The same applies to the caption: see the style
    guide's 'Caption' section for hook rules and hashtag conventions.

    Args:
        slides: Ordered list of slides. First must be 'cover', last 'cta'.
        topic: Short topic string used in the output folder name.
        handle: Footer handle shown on the final slide.
        caption: The Instagram post caption. First 125 chars must hook.
                 Saved as caption.txt next to the rendered slides. If
                 omitted the carousel still renders, but you should
                 always include one — see the style guide.
        out_dir: Absolute path to output dir. If omitted, a timestamped
                 folder is created under code/analytics/output/carousels/.

    Returns:
        dict with output_dir, slide_count, slide_paths (list of absolute
        PNG paths in order), json_path (the slides.json manifest), and
        caption_path (None if no caption was passed).
    """
    if not slides:
        raise ValueError("slides list is empty")
    if slides[0].type != "cover":
        raise ValueError(f"first slide must be type 'cover', got '{slides[0].type}'")
    if slides[-1].type != "cta":
        raise ValueError(f"last slide must be type 'cta', got '{slides[-1].type}'")

    if out_dir:
        target = pathlib.Path(out_dir).expanduser().resolve()
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = DEFAULT_OUT_DIR / f"{_slugify(topic)}_{ts}"
    target.mkdir(parents=True, exist_ok=True)

    slide_dicts = [s.model_dump(exclude_none=True) for s in slides]

    import json as _json
    manifest = {"topic": topic, "handle": handle, "slides": slide_dicts}
    if caption is not None:
        manifest["caption"] = caption
    json_path = target / "slides.json"
    json_path.write_text(_json.dumps(manifest, indent=2))

    caption_path: pathlib.Path | None = None
    if caption is not None:
        caption_path = target / "caption.txt"
        caption_path.write_text(caption.rstrip() + "\n")

    paths = _render(slide_dicts, handle, target)
    log.info("carousel done: %d slides -> %s", len(paths), target)

    return {
        "output_dir": str(target),
        "slide_count": len(paths),
        "slide_paths": [str(p) for p in paths],
        "json_path": str(json_path),
        "caption_path": str(caption_path) if caption_path else None,
    }


if __name__ == "__main__":
    mcp.run()
