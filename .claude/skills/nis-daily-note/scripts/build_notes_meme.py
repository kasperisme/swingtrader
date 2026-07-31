#!/usr/bin/env python3
"""Render a daily post as a real iPhone Notes screenshot.

Everything is laid out on a true device canvas (iPhone 15 Pro, 393x852pt @3x =
1179x2556px) using iOS point metrics, so the chrome has the proportions a real
screenshot has — Dynamic Island, status bar, nav bar, home indicator. The feed
images are then CROPS of that screenshot (which is what people actually post),
not a redrawn layout, so the type stays large and the geometry stays honest.

Authenticity rules this follows, because they're the tells:
  · Notes has no right-aligned columns and no coloured text — values run inline,
    and colour comes from emoji-style dots, which a real note can contain.
  · The first line renders in the Title style; the date sits centred above it.
  · Type is iOS-scaled (Title 24pt, Body 17pt), not canvas-scaled.

Content is authored by Claude in a `note.json` spec; this does layout only.

    python build_notes_meme.py --spec output/notes/<date>/note.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
from PIL import Image, ImageDraw, ImageFont

# --- device geometry, iPhone 15 Pro ------------------------------------------
SCALE = 3                       # @3x
PT_W, PT_H = 393, 852           # logical points
W, H = PT_W * SCALE, PT_H * SCALE

# Crops posted to the feed, as a fraction of the device screenshot (top-anchored —
# a shared screenshot is nearly always trimmed from the bottom).
CROPS = {"4x5": (1080, 1350), "9x16": (1080, 1920), "1x1": (1080, 1080)}

_FONT_FILE = "/System/Library/Fonts/HelveticaNeue.ttc"
_FACES = {"reg": 0, "bold": 1, "medium": 10}
_FALLBACK = {"reg": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf", "medium": "DejaVuSans.ttf"}

THEMES = {
    "light": {"bg": "#FFFFFF", "ink": "#000000", "mut": "#8A8A8E", "rule": "#D1D1D6",
              "tint": "#E8B10A", "pos": "#34C759", "neg": "#FF3B30", "island": "#000000"},
    "dark":  {"bg": "#000000", "ink": "#F2F2F7", "mut": "#8E8E93", "rule": "#38383A",
              "tint": "#FFD60A", "pos": "#30D158", "neg": "#FF453A", "island": "#000000"},
}

_font_cache: dict[tuple[int, str], ImageFont.FreeTypeFont] = {}


def _f(pt: float, weight: str = "reg") -> ImageFont.FreeTypeFont:
    """Font sized in iOS POINTS — the scale factor is applied here, once."""
    px = int(round(pt * SCALE))
    key = (px, weight)
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(_FONT_FILE, px, index=_FACES[weight])
        except OSError:
            _font_cache[key] = ImageFont.truetype(_FALLBACK[weight], px)
    return _font_cache[key]


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def P(pt: float) -> int:
    return int(round(pt * SCALE))


def _wrap(d, text: str, font, maxw: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if d.textlength(trial, font=font) <= maxw or not line:
                line = trial
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


# --- iOS chrome ---------------------------------------------------------------

def _status_only(d, T, clock: str) -> None:
    """Dynamic Island + status bar — shared by every screen."""
    ink = (*_hex(T["ink"]), 255)

    # Dynamic Island: 125x37pt pill, 11pt from the top, horizontally centred.
    isl_w, isl_h, isl_top = P(125), P(37), P(11)
    ix = (W - isl_w) // 2
    d.rounded_rectangle([ix, isl_top, ix + isl_w, isl_top + isl_h],
                        radius=isl_h // 2, fill=(*_hex(T["island"]), 255))

    # Status bar: time centred in the left "ear", icons in the right ear.
    bar_cy = isl_top + isl_h // 2
    d.text((P(67), bar_cy), clock, font=_f(17, "bold"), fill=ink, anchor="mm")

    # cellular — four rising bars
    x = W - P(88)
    for i in range(4):
        h = P(3.5) + i * P(2.2)
        d.rounded_rectangle([x + i * P(5.2), bar_cy + P(5) - h, x + i * P(5.2) + P(3.4), bar_cy + P(5)],
                            radius=P(1), fill=ink)
    # wifi — nested arcs over a dot
    wx, wy = W - P(56), bar_cy + P(4)
    for i, r in enumerate((P(9.5), P(6.4), P(3.3))):
        d.arc([wx - r, wy - r, wx + r, wy + r], start=212, end=328, fill=ink, width=P(1.5) - i // 2)
    d.ellipse([wx - P(1.4), wy - P(1.4), wx + P(1.4), wy + P(1.4)], fill=ink)
    # battery — outline, fill, nub
    bx, bw, bh = W - P(38), P(24), P(12)
    d.rounded_rectangle([bx, bar_cy - bh // 2, bx + bw, bar_cy + bh // 2],
                        radius=P(3.5), outline=(*_hex(T["mut"]), 255), width=P(1))
    d.rounded_rectangle([bx + P(2), bar_cy - bh // 2 + P(2), bx + P(16), bar_cy + bh // 2 - P(2)],
                        radius=P(2), fill=ink)
    d.rounded_rectangle([bx + bw + P(1.5), bar_cy - P(2.5), bx + bw + P(3.5), bar_cy + P(2.5)],
                        radius=P(1), fill=(*_hex(T["mut"]), 255))


def _home_indicator(d, T) -> None:
    hi_w, hi_h = P(139), P(5)
    d.rounded_rectangle([(W - hi_w) // 2, H - P(8) - hi_h, (W + hi_w) // 2, H - P(8)],
                        radius=hi_h // 2, fill=(*_hex(T["ink"]), 190))


def _chrome(d, T, clock: str) -> None:
    """Note DETAIL view: '‹ Notes' back button and 'Done'."""
    _status_only(d, T, clock)
    nav_cy = P(59) + P(22)
    tint = (*_hex(T["tint"]), 255)
    d.text((P(16), nav_cy), "‹", font=_f(24, "reg"), fill=tint, anchor="lm")
    d.text((P(27), nav_cy), "Notes", font=_f(17, "reg"), fill=tint, anchor="lm")
    d.text((W - P(20), nav_cy), "Done", font=_f(17, "medium"), fill=tint, anchor="rm")
    _home_indicator(d, T)


def _chrome_list(d, T, clock: str, collapsed: bool = False) -> None:
    """Notes LIST view: '‹ Folders' and the actions button. Once the large title
    scrolls away iOS collapses it into a small centred title over a hairline —
    reproducing that is what sells the scroll as real."""
    _status_only(d, T, clock)
    nav_cy = P(59) + P(22)
    tint = (*_hex(T["tint"]), 255)
    d.text((P(16), nav_cy), "‹", font=_f(24, "reg"), fill=tint, anchor="lm")
    d.text((P(27), nav_cy), "Folders", font=_f(17, "reg"), fill=tint, anchor="lm")
    # actions: a faintly tinted circle with a tinted ellipsis. Blend the fill by hand —
    # ImageDraw on an RGB image discards alpha, which renders it as a solid blob.
    cx, r = W - P(28), P(11)
    bg, tn = _hex(T["bg"]), _hex(T["tint"])
    soft = tuple(int(b + (t - b) * 0.20) for b, t in zip(bg, tn))
    d.ellipse([cx - r, nav_cy - r, cx + r, nav_cy + r], fill=(*soft, 255))
    for k in (-1, 0, 1):
        d.ellipse([cx + k * P(4.6) - P(1.5), nav_cy - P(1.5),
                   cx + k * P(4.6) + P(1.5), nav_cy + P(1.5)], fill=tint)
    if collapsed:
        d.text((W // 2, nav_cy), "Notes", font=_f(17, "medium"),
               fill=(*_hex(T["ink"]), 255), anchor="mm")
        d.line([(0, P(59) + P(44)), (W, P(59) + P(44))], fill=(*_hex(T["rule"]), 160), width=2)


# --- note body ----------------------------------------------------------------

def _dot(d, cx, cy, r, colour):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*_hex(colour), 255))


# Apple Color Emoji is a bitmap font: it only loads at its own strike size, so an
# emoji is rendered there and downscaled. A real note is full of these.
_EMOJI_FILE = "/System/Library/Fonts/Apple Color Emoji.ttc"
_emoji_strike: int | None = None
_emoji_cache: dict[tuple[str, int], Image.Image | None] = {}


def _emoji_font():
    global _emoji_strike
    if _emoji_strike is None:
        _emoji_strike = 0
        for s in (160, 137, 96, 64):
            try:
                ImageFont.truetype(_EMOJI_FILE, s)
                _emoji_strike = s
                break
            except OSError:
                continue
    return ImageFont.truetype(_EMOJI_FILE, _emoji_strike) if _emoji_strike else None


def emoji_img(ch: str, px: int) -> Image.Image | None:
    key = (ch, px)
    if key in _emoji_cache:
        return _emoji_cache[key]
    f = _emoji_font()
    img = None
    if f:
        canvas = Image.new("RGBA", (_emoji_strike * 2, _emoji_strike * 2), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), ch, font=f, embedded_color=True)
        bb = canvas.getbbox()
        if bb:
            img = canvas.crop(bb).resize((px, px), Image.LANCZOS)
    _emoji_cache[key] = img
    return img


def _paste_emoji(target, ch: str, x: int, cy: int, px: int) -> int:
    """Paste an emoji vertically centred on `cy`; returns its right edge."""
    im = emoji_img(ch, px)
    if im is None:
        return x
    target.paste(im, (int(x), int(cy - px / 2)), im)
    return int(x + px)


def _rich(d, x, y, text: str, size_pt: float, T, maxw: int, draw: bool) -> int:
    """Draw a paragraph honouring **bold** spans, wrapping across them.
    Notes supports bold inline, so the copy can use it for emphasis."""
    reg, bold = _f(size_pt, "reg"), _f(size_pt, "bold")
    lh = P(size_pt * 1.42)
    # Tokenise into (word, is_bold, space_before). The space flag has to survive the
    # ** split, else punctuation that hugs a bold span ("**$514B**." ) gets pushed
    # onto its own token and renders as "$514B ."
    tokens, is_b, first, prev_gap = [], False, True, False
    for chunk in text.split("**"):
        # A space can sit on either side of the ** marker — "of **$514B**. next" has
        # it before the span and none after. Both sides have to be checked.
        gap = prev_gap or chunk[:1].isspace()
        for j, w in enumerate(chunk.split()):
            tokens.append((w, is_b, False if first else (gap if j == 0 else True)))
            first = False
        if chunk.split():
            prev_gap = chunk[-1:].isspace()
        else:
            prev_gap = gap or chunk[-1:].isspace()
        is_b = not is_b

    space_w = d.textlength(" ", font=reg)

    def _paint(line, yy):
        cx = x
        for lw, lb, sp in line:
            lf = bold if lb else reg
            if sp:
                cx += space_w
            d.text((cx, yy), lw, font=lf, fill=(*_hex(T["ink"]), 255), anchor="lm")
            cx += d.textlength(lw, font=lf)

    line, width = [], 0.0
    for word, b, sp in tokens:
        f = bold if b else reg
        w_px = d.textlength(word, font=f) + (space_w if sp and line else 0)
        if line and width + w_px > maxw:
            if draw:
                _paint(line, y)
            y += lh
            line, width = [(word, b, False)], d.textlength(word, font=f)
        else:
            width += w_px
            line.append((word, b, sp))
    if line:
        if draw:
            _paint(line, y)
        y += lh
    return y


def _layout(d, spec, T, title_pt: float, body_pt: float, draw: bool,
            start_y: int | None = None, img=None) -> int:
    x, maxw = P(20), W - P(40)
    y = P(108) if start_y is None else start_y

    if spec.get("timestamp"):                       # centred grey date, as in Notes
        if draw:
            d.text((W // 2, y), spec["timestamp"], font=_f(11, "reg"),
                   fill=(*_hex(T["mut"]), 255), anchor="mm")
        y += P(26)

    title_f = _f(title_pt, "bold")
    title_lh = P(title_pt * 1.24)
    for ln in _wrap(d, spec.get("title", ""), title_f, maxw):
        if draw:
            d.text((x, y), ln, font=title_f, fill=(*_hex(T["ink"]), 255), anchor="lm")
        y += title_lh
    y += P(8)

    body_f = _f(body_pt, "reg")
    lh = P(body_pt * 1.42)
    use_dots = spec.get("markers", "dots") == "dots"

    for blk in spec.get("blocks", []):
        kind = blk.get("kind", "text")
        # --- Notes' own paragraph styles -------------------------------------
        if kind == "heading":
            hf = _f(body_pt * 1.28, "bold")
            icon = blk.get("icon")
            hx = x
            if icon and img is not None and draw:
                hx = _paste_emoji(img, icon, x, y, P(body_pt * 1.2)) + P(8)
            elif icon:
                hx = x + P(body_pt * 1.2) + P(8)
            for i_ln, ln in enumerate(_wrap(d, blk.get("text", ""), hf, maxw - (hx - x))):
                if ln and draw:
                    d.text((hx if i_ln == 0 else x, y), ln, font=hf,
                           fill=(*_hex(T["ink"]), 255), anchor="lm")
                y += P(body_pt * 1.28 * 1.34)
            y += int(lh * 0.18)
            continue
        if kind == "subheading":
            sf = _f(body_pt * 1.06, "medium")
            for ln in _wrap(d, blk.get("text", ""), sf, maxw):
                if ln and draw:
                    d.text((x, y), ln, font=sf, fill=(*_hex(T["ink"]), 255), anchor="lm")
                y += P(body_pt * 1.06 * 1.36)
            y += int(lh * 0.14)
            continue
        if kind == "mono":
            # Notes' "Monostyled" — the right style for a column of figures.
            mf = _f(body_pt * 0.92, "reg")
            try:
                mf = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc",
                                        int(body_pt * 0.92 * SCALE))
            except OSError:
                pass
            for ln in blk.get("lines", []):
                if draw:
                    d.text((x, y), ln, font=mf, fill=(*_hex(T["ink"]), 255), anchor="lm")
                y += P(body_pt * 1.34)
            y += int(lh * 0.3)
            continue
        if kind in ("bullet", "checklist", "numbered"):
            for n, item in enumerate(blk.get("items", []), 1):
                text = item if isinstance(item, str) else item.get("label", "")
                if kind == "bullet":
                    mark = item.get("emoji") if isinstance(item, dict) else None
                    if mark:
                        if draw and img is not None:
                            _paste_emoji(img, mark, x, y, P(15))
                        tx = x + P(22)
                    else:
                        if draw:
                            _dot(d, x + P(5), y, P(3), T["ink"])
                        tx = x + P(18)
                elif kind == "numbered":
                    if draw:
                        d.text((x, y), f"{n}.", font=body_f,
                               fill=(*_hex(T["ink"]), 255), anchor="lm")
                    tx = x + P(24)
                else:                                  # checklist
                    done = isinstance(item, dict) and item.get("done")
                    r = P(9)
                    if draw:
                        if done:
                            d.ellipse([x, y - r, x + 2 * r, y + r], fill=(*_hex(T["tint"]), 255))
                            d.line([(x + P(5), y), (x + P(8), y + P(4)), (x + P(13), y - P(5))],
                                   fill=(*_hex("#FFFFFF"), 255), width=P(2))
                        else:
                            d.ellipse([x, y - r, x + 2 * r, y + r],
                                      outline=(*_hex(T["mut"]), 255), width=P(1.5))
                    tx = x + P(26)
                end = _rich(d, tx, y, text, body_pt, T, maxw - (tx - x), draw)
                y = max(y + lh, end)
            y += int(lh * 0.3)
            continue
        # --- plain body ------------------------------------------------------
        if kind == "text":
            for para in blk.get("text", "").split("\n"):
                if not para.strip():
                    y += lh
                    continue
                y = _rich(d, x, y, para, body_pt, T, maxw, draw)
            y += int(lh * 0.3)
        elif kind == "list":
            for item in blk.get("items", []):
                label, value = item.get("label", ""), item.get("value")
                direction = (item.get("dir") or "").lower()
                tx = x
                mark = item.get("emoji")
                if mark:
                    if draw and img is not None:
                        _paste_emoji(img, mark, x, y, P(15))
                    tx = x + P(21)
                elif use_dots and direction in ("up", "down"):
                    if draw:
                        _dot(d, x + P(4.5), y, P(4.5), T["pos"] if direction == "up" else T["neg"])
                    tx = x + P(18)
                elif draw:                           # plain dash for a non-data row
                    d.text((x, y), "–", font=body_f, fill=(*_hex(T["mut"]), 255), anchor="lm")
                    tx = x + P(14)
                else:
                    tx = x + P(14)
                # Values run INLINE — Notes has no right-aligned columns. The value
                # itself carries the colour so a scanner sees up/down instantly.
                if draw:
                    d.text((tx, y), label, font=body_f, fill=(*_hex(T["ink"]), 255), anchor="lm")
                    if value:
                        vx = tx + d.textlength(label + " ", font=body_f)
                        vcol = (T["pos"] if direction == "up"
                                else T["neg"] if direction == "down" else T["ink"])
                        d.text((vx, y), str(value), font=_f(body_pt, "medium"),
                               fill=(*_hex(vcol), 255), anchor="lm")
                y += lh
            y += int(lh * 0.3)
        elif kind == "space":
            y += P(blk.get("pt", 10))
    return y


def render_note_strip(spec: dict, title_pt: float = 24.0,
                      body_pt: float = 17.0) -> Image.Image:
    """The note's body as a tall strip, at natural reading size and NOT shrunk to
    fit a screen — the reel scrolls this under fixed chrome, so a long note is the
    point rather than a problem. Excludes chrome; y=0 is the top of the content."""
    T = THEMES.get(spec.get("theme", "light"), THEMES["light"])
    scratch = ImageDraw.Draw(Image.new("RGB", (W, 16)))
    end = _layout(scratch, spec, T, title_pt, body_pt, draw=False, start_y=P(16))

    strip = Image.new("RGB", (W, end + P(48)), _hex(T["bg"]))
    d = ImageDraw.Draw(strip)
    _layout(d, spec, T, title_pt, body_pt, draw=True, start_y=P(16), img=strip)
    if spec.get("footer"):
        d.text((P(20), end + P(22)), spec["footer"], font=_f(11, "reg"),
               fill=(*_hex(T["mut"]), 255), anchor="lm")
    return strip


def render(spec: dict, limit: int | None = None) -> Image.Image:
    """`limit` is the y the content must fit above. Defaults to the 4:5 feed crop
    (the tightest), but the reel renders this note for a 9:16 frame and passes its
    own — otherwise the type shrinks for a crop that is never taken."""
    T = THEMES.get(spec.get("theme", "light"), THEMES["light"])
    img = Image.new("RGB", (W, H), _hex(T["bg"]))
    d = ImageDraw.Draw(img)
    _chrome(d, T, spec.get("clock", "9:41"))

    if limit is None:
        limit = int(W * 5 / 4) - P(24)
    title_pt, body_pt = 24.0, 17.0
    for step in range(12):
        tp, bp = max(17.0, 24.0 - 0.7 * step), max(12.5, 17.0 - 0.5 * step)
        title_pt, body_pt = tp, bp
        if _layout(d, spec, T, tp, bp, draw=False) <= limit:
            break
    end = _layout(d, spec, T, title_pt, body_pt, draw=True, img=img)

    if spec.get("footer"):
        # Sit below whatever the content actually ended at — pinning to `limit`
        # overlaps the last line whenever the shrink loop bottoms out.
        fy = min(H - P(24), max(limit, end) + P(16))
        d.text((P(20), fy), spec["footer"], font=_f(11, "reg"),
               fill=(*_hex(T["mut"]), 255), anchor="lm")
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a daily note as an iPhone screenshot.")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--ratios", default="4x5,9x16")
    args = ap.parse_args()

    spec_path = pathlib.Path(args.spec)
    spec = json.loads(spec_path.read_text())
    out = spec_path.resolve().parent

    shot = render(spec)
    (out / "screenshot").mkdir(parents=True, exist_ok=True)
    shot.save(out / "screenshot" / "note.png")
    print(f"[device] → {out / 'screenshot' / 'note.png'}  ({W}x{H})")

    for ratio in [r.strip() for r in args.ratios.split(",") if r.strip()]:
        tw, th = CROPS[ratio]
        crop_h = min(H, int(W * th / tw))            # top-anchored crop of the screenshot
        rdir = out / ratio
        rdir.mkdir(parents=True, exist_ok=True)
        shot.crop((0, 0, W, crop_h)).resize((tw, th), Image.LANCZOS).save(rdir / "note.png")
        print(f"[{ratio}] → {rdir / 'note.png'}")


if __name__ == "__main__":
    main()
