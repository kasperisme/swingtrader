#!/usr/bin/env python3
"""Render a vertical reel that looks like receiving a text and reading the thread.

The conceit: the viewer's own phone lights up with a message from NIS, they tap
it, and the week's market story arrives as a casual back-and-forth instead of a
lecture. Scrolling a chat is a thing people already do; a chart is a thing they
skip.

Three acts, on a true device canvas (geometry, fonts and chrome are reused from
build_notes_meme so this matches the Notes reel exactly):

  1. LOCKSCREEN — wallpaper, big clock, then a Messages banner springs in.
  2. TAP        — the finger dot lands on the banner, which flashes and opens.
  3. THREAD     — bubbles land one at a time, NIS types before each of its own,
                  the thread auto-scrolls once it outgrows the viewport.

Authenticity rules this follows, because they're the tells:
  · Typing indicators only ever precede an INCOMING message — you never watch
    yourself type.
  · A bubble tail is drawn only on the LAST message of a same-sender run.
  · The thread is bottom-anchored: a short conversation sits at the BOTTOM of an
    empty screen, it does not start at the top.
  · Outgoing bubbles say "Delivered" under the final one, not under every one.
  · Timestamps are a centred day divider at the top, not a stamp per bubble.

Content is authored by Claude in a `chat.json` spec; this does layout only.

    python build_chat_reel.py --spec output/chats/<date>/chat.json \
        --out output/chats/<date>/9x16 [--seconds 22] [--fps 30]
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

def _find_device_module() -> pathlib.Path:
    """Device geometry, fonts, chrome and emoji all live in the nis-daily-note
    skill. Importing it instead of copying keeps ONE definition of what an iPhone
    looks like, so the chat reel and the notes reel can never drift apart."""
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "nis-daily-note" / "scripts"
        if (cand / "build_notes_meme.py").exists():
            return cand
    sys.exit("could not find nis-daily-note/scripts/build_notes_meme.py "
             "(the chat reel reuses its device metrics)")


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(_find_device_module()))
import build_notes_meme as nm  # noqa: E402  — device metrics + fonts + emoji

P, W, H = nm.P, nm.W, nm.H
OUT_W, OUT_H = 1080, 1920

# --- messages geometry (iOS points) -------------------------------------------
NAV_TOP = P(59)                     # status bar
NAV_H = P(64)                       # avatar + name block
NAV_BOTTOM = NAV_TOP + NAV_H
INPUT_H = P(50)

# The exported frame is a 9:16 crop of the taller device canvas. The Notes reel is
# top-anchored so it can ignore this, but a THREAD is bottom-anchored: every piece
# of bottom chrome has to sit inside the visible crop or it lands on the cutting
# room floor along with the newest bubble.
VH = int(W * OUT_H / OUT_W)
INPUT_TOP = VH - P(34) - INPUT_H
SIDE = P(12)
BUB_MAXW = int(P(393) * 0.72)
BUB_PADX, BUB_PADY = P(14), P(9)
BUB_RADIUS = P(19)
GAP_SAME, GAP_DIFF = P(3), P(11)
DIV_H = P(34)                       # the 'Today 9:41' day divider
BODY_PT = 17.0

KB_H = P(298)                       # predictive bar + 4 key rows + bottom inset

CHAT = {
    "light": {"in_bg": "#E9E9EB", "in_ink": "#000000",
              "out_bg": "#0A84FF", "out_ink": "#FFFFFF",
              "field": "#FFFFFF", "field_line": "#D1D1D6", "meta": "#8A8A8E",
              "kb_bg": "#D1D4DA", "kb_key": "#FFFFFF", "kb_alt": "#ABB0BA",
              "kb_ink": "#000000", "kb_rule": "#BFC3CB"},
    "dark":  {"in_bg": "#26252A", "in_ink": "#FFFFFF",
              "out_bg": "#0A84FF", "out_ink": "#FFFFFF",
              "field": "#1C1C1E", "field_line": "#3A3A3C", "meta": "#8E8E93",
              "kb_bg": "#161618", "kb_key": "#4A4A4E", "kb_alt": "#2A2A2D",
              "kb_ink": "#FFFFFF", "kb_rule": "#39393C"},
}


def _input_top(kb: float) -> int:
    """Where the input bar sits. With the keyboard up it rides on top of it, which
    also shrinks the thread viewport — that upward shove is most of what makes the
    keyboard read as real."""
    down = VH - P(34) - INPUT_H
    up = VH - KB_H - INPUT_H
    return int(round(down + (up - down) * max(0.0, min(1.0, kb))))


def _send_centre(kb: float) -> tuple[int, int]:
    return W - P(29), _input_top(kb) + P(26)


def _rgba(c: str, a: int = 255):
    return (*nm._hex(c), a)


def _home_bar(d, T) -> None:
    """Home indicator on the VISIBLE bottom edge (nm's draws at the device bottom,
    which this reel crops away)."""
    hi_w, hi_h = P(139), P(5)
    d.rounded_rectangle([(W - hi_w) // 2, VH - P(9) - hi_h, (W + hi_w) // 2, VH - P(9)],
                        radius=hi_h // 2, fill=(*nm._hex(T["ink"]), 190))


def _ease_out_back(t: float, s: float = 1.4) -> float:
    """Overshoot then settle — how a banner and a bubble actually arrive."""
    t = max(0.0, min(1.0, t)) - 1.0
    return t * t * ((s + 1) * t + s) + 1.0


def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


# --- wallpaper ----------------------------------------------------------------

def _find_logo() -> pathlib.Path | None:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "code" / "analytics" / "scripts" / "assets" / "icon.png"
        if cand.exists():
            return cand
    return None


def _heart_points(cx: float, cy: float, size: float, n: int = 300):
    """The classic parametric heart. x spans -16..16, so `size` is its full width."""
    k = size / 32.0
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = (13 * math.cos(t) - 5 * math.cos(2 * t)
             - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * k, cy - y * k))
    return pts


def _nis_heart(img: Image.Image, cy: int, size: int, logo: pathlib.Path | None) -> None:
    """The brand mark inside a hand-drawn heart — a wallpaper someone would
    actually set. Drawn as glow-then-stroke so the heart reads as light rather
    than as a vector outline pasted on top."""
    pts = _heart_points(W / 2, cy, size)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    # The heart is a WINDOW onto the mark, not a frame around a tile: cover-fit the
    # artwork to the heart's bounding box and clip it to the silhouette, so the
    # flames run right out to the edges of the shape.
    if logo and logo.exists():
        bw, bh = int(x1 - x0), int(y1 - y0)
        src = Image.open(logo).convert("RGB")
        sc = max(bw / src.width, bh / src.height)
        src = src.resize((max(1, int(src.width * sc)), max(1, int(src.height * sc))),
                         Image.LANCZOS)
        ox, oy = (src.width - bw) // 2, (src.height - bh) // 2
        layer = Image.new("RGB", img.size, (0, 0, 0))
        layer.paste(src.crop((ox, oy, ox + bw, oy + bh)), (int(x0), int(y0)))
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).polygon(pts, fill=255)
        img.paste(layer, (0, 0), mask)

    # glow and stroke go on TOP of the fill so the silhouette still reads as a heart
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(pts + [pts[0]], fill=(255, 86, 96, 210), width=P(11), joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(P(13)))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))

    ImageDraw.Draw(img).line(pts + [pts[0]], fill=(255, 138, 145, 255),
                             width=P(4), joint="curve")

def _wallpaper(spec: pathlib.Path | None, grad: list[str] | None,
               motif: str = "nis_heart", logo: pathlib.Path | None = None) -> Image.Image:
    """Cover-fit a real photo, else build a deep gradient with a soft glow. The
    lockscreen has to look like SOMEONE'S phone, not like a template — so the
    default motif is the brand mark inside a heart, the way a fan would set it."""
    if spec and spec.exists():
        img = Image.open(spec).convert("RGB")
        sc = max(W / img.width, H / img.height)
        img = img.resize((max(W, int(img.width * sc)), max(H, int(img.height * sc))),
                         Image.LANCZOS)
        return img.crop(((img.width - W) // 2, (img.height - H) // 2,
                         (img.width - W) // 2 + W, (img.height - H) // 2 + H))

    top, bot = (grad or ["#0B1220", "#060911"])[:2]
    t, b = nm._hex(top), nm._hex(bot)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / max(1, H - 1)
        k = k ** 0.85
        d.line([(0, y), (W, y)], fill=tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3)))
    # a single off-centre glow keeps it from reading as a flat CSS gradient
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    gx, gy, gr = int(W * 0.72), int(H * 0.30), int(W * 0.62)
    gd.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(int(W * 0.16)))
    img = Image.composite(Image.new("RGB", (W, H), nm._hex("#1B3358")), img, glow)

    if motif == "nis_heart":
        # dead centre of the visible frame — it is the wallpaper's subject. It
        # clears the clock above it, and the notification sits BELOW it (iOS 17
        # stacks lockscreen notifications at the bottom), so nothing covers it.
        _nis_heart(img, cy=VH // 2, size=P(265), logo=logo or _find_logo())
    return img


def _material(base: Image.Image, box, radius: int, light: bool) -> Image.Image:
    """iOS 'material': the wallpaper behind the panel, blurred and lifted. Drawing
    a flat translucent rect instead is the thing that looks fake."""
    x0, y0, x1, y1 = box
    crop = base.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(P(18)))
    tint = Image.new("RGB", crop.size, (245, 245, 247) if light else (28, 28, 30))
    crop = Image.blend(crop, tint, 0.62 if light else 0.55)
    mask = Image.new("L", crop.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, crop.size[0] - 1, crop.size[1] - 1],
                                           radius=radius, fill=255)
    out = base.copy()
    out.paste(crop, (x0, y0), mask)
    return out


# --- lockscreen ---------------------------------------------------------------

def _messages_icon(img: Image.Image, x: int, cy: int, size: int) -> None:
    """The green Messages app icon — a white speech bubble on a green squircle."""
    d = ImageDraw.Draw(img)
    y0 = cy - size // 2
    d.rounded_rectangle([x, y0, x + size, y0 + size], radius=int(size * 0.24),
                        fill=(52, 199, 89, 255))
    bx0, by0 = x + int(size * 0.17), y0 + int(size * 0.20)
    bx1, by1 = x + int(size * 0.83), y0 + int(size * 0.68)
    d.ellipse([bx0, by0, bx1, by1], fill=(255, 255, 255, 255))
    d.polygon([(x + int(size * 0.30), y0 + int(size * 0.62)),
               (x + int(size * 0.24), y0 + int(size * 0.84)),
               (x + int(size * 0.47), y0 + int(size * 0.66))], fill=(255, 255, 255, 255))


def _lock_frame(base: Image.Image, T, spec: dict, banner_p: float,
                tap_a: float = 0.0, flash: float = 0.0) -> Image.Image:
    """Wallpaper + clock + the notification sliding in. `banner_p` 0..1."""
    frame = base.copy()
    lock = spec.get("lock", {})
    d = ImageDraw.Draw(frame)

    nm._status_only(d, nm.THEMES["dark"], spec.get("clock", "9:41"))

    # date + time, iOS 17 lockscreen proportions
    d.text((W // 2, P(112)), lock.get("date", ""), font=nm._f(17, "medium"),
           fill=(255, 255, 255, 235), anchor="mm")
    d.text((W // 2, P(186)), spec.get("clock", "9:41"), font=nm._f(88, "bold"),
           fill=(255, 255, 255, 255), anchor="mm")

    if banner_p > 0:
        title = lock.get("title") or spec.get("contact", "NIS")
        preview = lock.get("preview", "")
        bw = W - 2 * P(14)
        bx = P(14)
        tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        body_f = nm._f(15, "reg")
        lines = nm._wrap(tmp, preview, body_f, bw - P(28))[:2]
        bh = P(30) + P(21) + len(lines) * P(20) + P(12)

        # iOS 17 stacks lockscreen notifications at the BOTTOM, so it springs UP
        # into place from off-screen — and that leaves the centre of the wallpaper
        # to the artwork, which is the point of having artwork.
        rest = VH - P(64) - bh
        travel = bh + P(40)
        y = int(rest + travel * (1 - _ease_out_back(banner_p)))
        frame = _material(frame, (bx, y, bx + bw, y + bh), P(24), light=True)
        d = ImageDraw.Draw(frame)

        if flash > 0:   # the momentary press highlight before it opens
            ov = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            ImageDraw.Draw(ov).rounded_rectangle([bx, y, bx + bw, y + bh], radius=P(24),
                                                 fill=(255, 255, 255, int(70 * flash)))
            frame = Image.alpha_composite(frame.convert("RGBA"), ov).convert("RGB")
            d = ImageDraw.Draw(frame)

        _messages_icon(frame, bx + P(14), y + P(21), P(22))
        d = ImageDraw.Draw(frame)
        d.text((bx + P(44), y + P(21)), "MESSAGES", font=nm._f(12, "medium"),
               fill=_rgba("#3C3C43", 165), anchor="lm")
        d.text((bx + bw - P(14), y + P(21)), lock.get("when", "now"),
               font=nm._f(12, "reg"), fill=_rgba("#3C3C43", 165), anchor="rm")
        d.text((bx + P(14), y + P(46)), title, font=nm._f(15, "bold"),
               fill=_rgba("#000000"), anchor="lm")
        yy = y + P(66)
        for ln in lines:
            d.text((bx + P(14), yy), ln, font=body_f, fill=_rgba("#000000", 225), anchor="lm")
            yy += P(20)

        if tap_a > 0:
            frame = _touch(frame, W // 2, y + bh // 2, alpha=tap_a)

    _home_bar(ImageDraw.Draw(frame), nm.THEMES["dark"])
    return frame


def _touch(frame, cx, cy, scale=1.0, alpha=1.0):
    if alpha <= 0:
        return frame
    r = int(P(26) * scale)
    ov = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(90, 90, 95, int(70 * alpha)),
               outline=(255, 255, 255, int(190 * alpha)), width=P(2))
    od.ellipse([cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2],
               fill=(120, 120, 125, int(60 * alpha)))
    return Image.alpha_composite(frame.convert("RGBA"), ov).convert("RGB")


# --- thread chrome ------------------------------------------------------------

def _avatar(img: Image.Image, cx: int, cy: int, r: int, initials: str, T) -> None:
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rgba("#8E8E93"))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rgba("#A2A2A8"))
    d.text((cx, cy + P(1)), initials[:3].upper(), font=nm._f(13, "medium"),
           fill=_rgba("#FFFFFF"), anchor="mm")


def _thread_chrome(frame: Image.Image, T, C, spec: dict, kb: float = 0.0,
                   field: str = "", caret: bool = False, send: bool = False) -> None:
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, W, NAV_BOTTOM], fill=nm._hex(T["bg"]))
    nm._status_only(d, T, spec.get("clock", "9:41"))

    tint = _rgba(T["tint"]) if T is nm.THEMES["dark"] else _rgba("#0A84FF")
    cy = NAV_TOP + P(16)
    d.text((P(14), cy + P(4)), "‹", font=nm._f(28, "reg"), fill=tint, anchor="lm")
    # unread pip, the detail that says this thread was actually notifying you
    d.ellipse([P(30), cy - P(3), P(30) + P(14), cy + P(11)], fill=tint)
    d.text((P(37), cy + P(4)), "1", font=nm._f(11, "bold"), fill=_rgba(T["bg"]), anchor="mm")

    _avatar(frame, W // 2, NAV_TOP + P(14), P(15), spec.get("avatar", "NIS"), T)
    d = ImageDraw.Draw(frame)
    d.text((W // 2, NAV_TOP + P(42)), spec.get("contact", "NIS"), font=nm._f(12, "reg"),
           fill=_rgba(T["ink"]), anchor="mm")
    d.text((W // 2 + P(24), NAV_TOP + P(42)), "›", font=nm._f(12, "reg"),
           fill=_rgba(T["mut"]), anchor="mm")
    d.line([(0, NAV_BOTTOM), (W, NAV_BOTTOM)], fill=_rgba(T["rule"], 150), width=2)

    # input bar — rides on top of the keyboard when one is up
    itop = _input_top(kb)
    if kb > 0:
        _keyboard(frame, T, C, itop + INPUT_H, field)
        d = ImageDraw.Draw(frame)
    d.rectangle([0, itop, W, itop + INPUT_H], fill=nm._hex(T["bg"]))
    fx0, fx1 = P(52), W - P(52)
    d.rounded_rectangle([fx0, itop + P(8), fx1, itop + P(40)], radius=P(16),
                        fill=_rgba(C["field"]), outline=_rgba(C["field_line"]), width=2)

    f = nm._f(15, "reg")
    if field:
        # the field scrolls to keep the caret in view, exactly like the real one
        avail = (fx1 - fx0) - P(30)
        shown = field
        while shown and d.textlength(shown, font=f) > avail:
            shown = shown[1:]
        tw = d.textlength(shown, font=f)
        d.text((fx0 + P(14), itop + P(24)), shown, font=f, fill=_rgba(T["ink"]), anchor="lm")
        if caret:
            cx = fx0 + P(14) + tw + P(2)
            d.line([(cx, itop + P(15)), (cx, itop + P(33))], fill=_rgba("#0A84FF"), width=P(2))
    else:
        d.text((fx0 + P(14), itop + P(24)), "iMessage", font=f,
               fill=_rgba(C["meta"]), anchor="lm")

    d.ellipse([P(16), itop + P(14), P(38), itop + P(36)], fill=_rgba(C["meta"], 90))
    d.text((P(27), itop + P(24)), "+", font=nm._f(17, "medium"),
           fill=_rgba(T["bg"]), anchor="mm")

    # send button — dimmed until there is something to send, bright on the press
    live = bool(field)
    col = "#0A84FF" if live else C["meta"]
    d.ellipse([W - P(42), itop + P(13), W - P(16), itop + P(39)],
              fill=_rgba(col, 255 if live else 110))
    # Drawn, not typed: the ↑ glyph is missing from this face and renders as tofu.
    ax, acy = _send_centre(kb)
    d.line([(ax, acy + P(6)), (ax, acy - P(6))], fill=_rgba("#FFFFFF"), width=P(2))
    d.polygon([(ax, acy - P(8)), (ax - P(5), acy - P(2)), (ax + P(5), acy - P(2))],
              fill=_rgba("#FFFFFF"))
    if send:
        ov = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        ImageDraw.Draw(ov).ellipse([W - P(42), itop + P(13), W - P(16), itop + P(39)],
                                   fill=(255, 255, 255, 90))
        frame.paste(Image.alpha_composite(frame.convert("RGBA"), ov).convert("RGB"), (0, 0))
        d = ImageDraw.Draw(frame)
    if kb <= 0:
        _home_bar(d, T)


# --- keyboard -----------------------------------------------------------------

_KB_ROWS = ("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM")


def _key(d, x0, y0, x1, y1, fill, ink, label, pt=22.0, weight="reg"):
    # the 1px shadow under each key is small but it's what stops the keyboard
    # reading as flat coloured rectangles
    d.rounded_rectangle([x0, y0 + P(1), x1, y1 + P(1.5)], radius=P(5),
                        fill=(*nm._hex("#8E8E93"), 90))
    d.rounded_rectangle([x0, y0, x1, y1], radius=P(5), fill=fill)
    if label:
        d.text(((x0 + x1) // 2, (y0 + y1) // 2), label, font=nm._f(pt, weight),
               fill=ink, anchor="mm")


def _suggestions(field: str) -> tuple[str, str, str]:
    """iOS's three predictions. While you type an unrecognised word it shows the
    literal string in quotes plus two cased variants — so they have to track the
    field, not sit there as decoration."""
    word = (field or "").split(" ")[-1].strip()
    if not word:
        return ("I", "The", "I'm")
    return (f"“{word}”", word, word.capitalize())


def _keyboard(frame: Image.Image, T, C, top: int, field: str = "") -> None:
    """A QWERTY that only has to survive a glance at reel scale — real proportions
    matter far more than real glyph shapes."""
    d = ImageDraw.Draw(frame)
    d.rectangle([0, top, W, VH], fill=_rgba(C["kb_bg"]))

    # predictive bar: three suggestions split by hairlines
    pb = top + P(44)
    for i, word in enumerate(_suggestions(field)):
        cx = int(W * (i * 2 + 1) / 6)
        d.text((cx, top + P(22)), word, font=nm._f(16, "medium" if i == 0 else "reg"),
               fill=_rgba(C["kb_ink"]), anchor="mm")
    for i in (1, 2):
        x = int(W * i / 3)
        d.line([(x, top + P(11)), (x, top + P(33))], fill=_rgba(C["kb_rule"]), width=2)

    key_h, gap, side = P(42), P(6), P(3)
    kw = (W - 2 * side - 9 * gap) // 10
    ink = _rgba(C["kb_ink"])
    key, alt = _rgba(C["kb_key"]), _rgba(C["kb_alt"])

    y = pb + P(10)
    for r, row in enumerate(_KB_ROWS):
        n = len(row)
        if r == 0:
            x = side
        elif r == 1:
            x = side + (kw + gap) // 2
        else:
            x = side + kw + gap + (kw + gap) // 2 - (kw + gap) // 2
        if r == 2:
            # shift, then the letters, then delete. Both symbols are DRAWN — ⇧ and
            # ⌫ are absent from this face and would render as tofu.
            sw = int(kw * 1.35)
            _key(d, side, y, side + sw, y + key_h, alt, ink, "")
            sx, sy = side + sw // 2, y + key_h // 2
            d.polygon([(sx, sy - P(9)), (sx - P(9), sy + P(1)), (sx + P(9), sy + P(1))], fill=ink)
            d.rectangle([sx - P(4), sy + P(1), sx + P(4), sy + P(8)], fill=ink)

            _key(d, W - side - sw, y, W - side, y + key_h, alt, ink, "")
            dx, dy = W - side - sw // 2, y + key_h // 2
            d.polygon([(dx - P(11), dy), (dx - P(4), dy - P(8)), (dx + P(10), dy - P(8)),
                       (dx + P(10), dy + P(8)), (dx - P(4), dy + P(8))], fill=ink)
            d.line([(dx - P(1), dy - P(4)), (dx + P(6), dy + P(4))],
                   fill=_rgba(C["kb_alt"]), width=P(2))
            d.line([(dx + P(6), dy - P(4)), (dx - P(1), dy + P(4))],
                   fill=_rgba(C["kb_alt"]), width=P(2))

            x = side + sw + gap + (W - 2 * side - sw * 2 - 2 * gap
                                   - n * kw - (n - 1) * gap) // 2
        for ch in row:
            _key(d, x, y, x + kw, y + key_h, key, ink, ch)
            x += kw + gap
        y += key_h + P(11)

    # bottom row: 123 · emoji · space · return
    bw = int(kw * 1.35)
    _key(d, side, y, side + bw, y + key_h, alt, ink, "123", 16)
    _key(d, side + bw + gap, y, side + bw * 2 + gap, y + key_h, alt, ink, "")
    nm._paste_emoji(frame, "\U0001F642", side + bw + gap + (bw - P(20)) // 2,
                    y + key_h // 2, P(20))
    d = ImageDraw.Draw(frame)
    rw = int(kw * 2.6)
    _key(d, side + bw * 2 + gap * 2, y, W - side - rw - gap, y + key_h, key, ink, "space", 16)
    _key(d, W - side - rw, y, W - side, y + key_h, alt, ink, "return", 15)


# --- bubbles ------------------------------------------------------------------

_EM_PX = P(BODY_PT * 1.18)


def _is_emoji_cp(o: int) -> bool:
    """Emoji proper — deliberately EXCLUDES General Punctuation (— ' …), which is
    text and must stay in the text font."""
    return ((0x1F000 <= o <= 0x1FAFF) or (0x2600 <= o <= 0x27BF)
            or (0x1F1E6 <= o <= 0x1F1FF) or o in (0x203C, 0x2049, 0x2B50, 0x2B06, 0x2B07)
            or o in (0xFE0F, 0x200D) or (0x1F3FB <= o <= 0x1F3FF))


def _tokens(text: str) -> list[tuple[str, str]]:
    """Split into ('w', word) and ('e', emoji-cluster) tokens. A cluster keeps ZWJ
    sequences and skin-tone modifiers together so 🧑‍💻 stays one glyph."""
    out: list[tuple[str, str]] = []
    for word in text.split():
        buf, i = "", 0
        while i < len(word):
            if _is_emoji_cp(ord(word[i])):
                if buf:
                    out.append(("w", buf))
                    buf = ""
                j = i
                while j < len(word) and _is_emoji_cp(ord(word[j])):
                    j += 1
                out.append(("e", word[i:j]))
                i = j
            else:
                buf += word[i]
                i += 1
        if buf:
            out.append(("w", buf))
        out.append(("sp", " "))
    if out and out[-1][0] == "sp":
        out.pop()
    return out


def _tok_w(d, tok: tuple[str, str], f) -> float:
    kind, val = tok
    if kind == "e":
        return _EM_PX
    return d.textlength(val, font=f)


def _wrap_tokens(d, text: str, f, maxw: int) -> list[list[tuple[str, str]]]:
    lines: list[list[tuple[str, str]]] = []
    for para in text.split("\n"):
        line, wid = [], 0.0
        for tok in _tokens(para):
            w = _tok_w(d, tok, f)
            if line and wid + w > maxw and tok[0] != "sp":
                while line and line[-1][0] == "sp":
                    line.pop()
                lines.append(line)
                line, wid = [tok], w
            else:
                line.append(tok)
                wid += w
        while line and line[-1][0] == "sp":
            line.pop()
        lines.append(line)
    return lines


def _bubble_lines(msg: dict):
    """(wrapped token lines, ticker rows). A `rows` bubble renders label/value pairs
    the way someone would paste a list into a message."""
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f = nm._f(BODY_PT, "reg")
    lines = _wrap_tokens(tmp, msg["text"], f, BUB_MAXW - 2 * BUB_PADX) if msg.get("text") else []
    rows = [(r["label"], r["value"]) for r in msg.get("rows", [])]
    return lines, rows


def _bubble_size(msg: dict) -> tuple[int, int]:
    lines, rows = _bubble_lines(msg)
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f, fm = nm._f(BODY_PT, "reg"), nm._f(BODY_PT, "medium")
    wid = 0.0
    for ln in lines:
        wid = max(wid, sum(_tok_w(tmp, t, f) for t in ln))
    for lab, val in rows:
        wid = max(wid, tmp.textlength(lab, font=fm) + tmp.textlength(val, font=fm) + P(40))
    wid = min(BUB_MAXW, int(wid) + 2 * BUB_PADX)
    hgt = 2 * BUB_PADY + len(lines) * P(22) + len(rows) * P(23)
    if lines and rows:
        hgt += P(8)
    return max(wid, P(56)), hgt


def _draw_bubble(frame: Image.Image, msg: dict, x: int, y: int, w: int, h: int,
                 T, C, tail: bool) -> None:
    out = msg.get("from") == "you"
    bg = _rgba(C["out_bg"] if out else C["in_bg"])
    ink = _rgba(C["out_ink"] if out else C["in_ink"])
    d = ImageDraw.Draw(frame)
    d.rounded_rectangle([x, y, x + w, y + h], radius=BUB_RADIUS, fill=bg)

    if tail:
        # Two circles make the iOS tail: a BULGE straddling the bottom corner, then
        # a page-coloured circle just outside it that carves the concave hook. The
        # crescent left behind is the tail. (Drawing the bulge inside the bubble
        # instead leaves a detached blob — that is the tell.)
        t = P(9)
        page = nm._hex(T["bg"])
        if out:
            d.ellipse([x + w - t, y + h - 2 * t, x + w + t, y + h], fill=bg)
            d.ellipse([x + w, y + h - t, x + w + 2 * t, y + h + t], fill=page)
        else:
            d.ellipse([x - t, y + h - 2 * t, x + t, y + h], fill=bg)
            d.ellipse([x - 2 * t, y + h - t, x, y + h + t], fill=page)

    lines, rows = _bubble_lines(msg)
    f, fm = nm._f(BODY_PT, "reg"), nm._f(BODY_PT, "medium")
    yy = y + BUB_PADY + P(11)
    for ln in lines:
        cx = x + BUB_PADX
        for kind, val in ln:
            if kind == "e":
                nm._paste_emoji(frame, val, cx, yy, _EM_PX)
                cx += _EM_PX
            else:
                d.text((cx, yy), val, font=f, fill=ink, anchor="lm")
                cx += d.textlength(val, font=f)
        yy += P(22)
    if lines and rows:
        yy += P(8)
    for lab, val in rows:
        up = not val.strip().startswith("-")
        col = _rgba("#FFFFFF") if out else _rgba(T["pos"] if up else T["neg"])
        d.text((x + BUB_PADX, yy + P(6)), lab, font=fm, fill=ink, anchor="lm")
        d.text((x + w - BUB_PADX, yy + P(6)), val, font=fm, fill=col, anchor="rm")
        yy += P(23)


def _typing_bubble(frame: Image.Image, x: int, y: int, T, C, phase: float) -> None:
    """Three dots that swell in sequence — the wait is what makes it feel live."""
    w, h = P(64), P(38)
    d = ImageDraw.Draw(frame)
    d.rounded_rectangle([x, y, x + w, y + h], radius=P(18), fill=_rgba(C["in_bg"]))
    for i in range(3):
        k = (phase * 3 - i) % 3
        s = 1.0 + 0.35 * max(0.0, math.sin(math.pi * min(1.0, max(0.0, k)))) if k < 1 else 1.0
        r = P(4.5) * s
        cx = x + P(18) + i * P(14)
        cy = y + h // 2
        a = 130 + int(90 * (s - 1.0) / 0.35)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rgba(C["meta"], min(255, a)))


# --- thread layout ------------------------------------------------------------

def _layout(msgs: list[dict]) -> list[dict]:
    """Stack the bubbles top-down in thread space; the frame builder decides which
    slice of that space is on screen."""
    items, y = [], 0
    for i, m in enumerate(msgs):
        w, h = _bubble_size(m)
        prev = msgs[i - 1] if i else None
        y += (GAP_SAME if prev and prev.get("from") == m.get("from") else GAP_DIFF) if i else 0
        nxt = msgs[i + 1] if i + 1 < len(msgs) else None
        items.append({"msg": m, "y": y, "w": w, "h": h,
                      "tail": not nxt or nxt.get("from") != m.get("from")})
        y += h
    return items


def _thread_frame(spec: dict, items: list[dict], T, C, shown: int, typing: bool,
                  enter: float, typ_phase: float, delivered: bool,
                  kb: float = 0.0, field: str = "", caret: bool = False,
                  send: bool = False) -> Image.Image:
    frame = Image.new("RGB", (W, H), nm._hex(T["bg"]))
    vis = items[:shown]
    itop = _input_top(kb)

    content_h = DIV_H + ((vis[-1]["y"] + vis[-1]["h"]) if vis else 0)
    if typing:
        content_h += GAP_DIFF + P(38)
    if delivered:
        content_h += P(18)

    # Bottom-anchored, always: a short thread sits at the bottom of an empty screen,
    # and once it outgrows the viewport the oldest bubbles simply scroll up under
    # the nav bar. That single rule gives both states for free.
    base = itop - P(10) - content_h

    d0 = ImageDraw.Draw(frame)
    dy = base + P(12)
    if NAV_BOTTOM < dy < itop:
        stamp = spec.get("day_stamp", "Today " + spec.get("clock", "9:41"))
        d0.text((W // 2, dy), stamp, font=nm._f(11, "medium"),
                fill=_rgba(C["meta"]), anchor="mm")
    base += DIV_H
    body_h = content_h - DIV_H      # bubble space only; base already past the divider

    for i, it in enumerate(vis):
        m = it["msg"]
        out = m.get("from") == "you"
        x = W - SIDE - it["w"] if out else SIDE
        y = base + it["y"]
        if i == shown - 1 and enter < 1.0:      # newest bubble springs up into place
            y += int(P(26) * (1 - _ease_out_back(enter)))
        if y + it["h"] < NAV_BOTTOM or y > itop:
            continue
        _draw_bubble(frame, m, x, y, it["w"], it["h"], T, C, it["tail"])

    if typing:
        ty = base + (body_h - P(38) - (P(18) if delivered else 0))
        _typing_bubble(frame, SIDE, ty, T, C, typ_phase)

    if delivered and vis and vis[-1]["msg"].get("from") == "you":
        d = ImageDraw.Draw(frame)
        d.text((W - SIDE, base + body_h - P(4)), "Delivered", font=nm._f(11, "reg"),
               fill=_rgba(C["meta"]), anchor="rm")

    _thread_chrome(frame, T, C, spec, kb, field, caret, send)
    return frame


# --- timeline -----------------------------------------------------------------

def _save(frame, tmp, i):
    frame.crop((0, 0, W, int(W * OUT_H / OUT_W))) \
         .resize((OUT_W, OUT_H), Image.LANCZOS) \
         .save(tmp / f"{i:05d}.png")


def render_frames(spec: dict, tmp: pathlib.Path, seconds: float, fps: int,
                  lock_secs: float) -> int:
    theme = spec.get("theme", "light")
    T, C = nm.THEMES[theme], CHAT[theme]
    msgs = spec["messages"]
    items = _layout(msgs)

    lock = spec.get("lock", {})
    paper = _wallpaper(
        pathlib.Path(spec["_dir"]) / lock["wallpaper"] if lock.get("wallpaper") else None,
        lock.get("gradient"),
        motif=lock.get("motif", "nis_heart"),
        logo=(pathlib.Path(spec["_dir"]) / lock["logo"]) if lock.get("logo") else None)

    n = int(round(seconds * fps))
    n_lock = int(round(lock_secs * fps))
    n_trans = max(3, int(0.30 * fps))
    n_conv = max(1, n - n_lock - n_trans)

    # each message gets time proportional to how long it takes to read, plus the
    # fixed overhead of its own performance (typing indicator / keyboard + send)
    weights = []
    for m in msgs:
        chars = len(m.get("text", "")) + sum(len(r["label"]) + 6 for r in m.get("rows", []))
        extra = 0.8 if m.get("from") == "nis" else 1.6
        weights.append(max(1.0, chars / 38.0) + extra)
    tot = sum(weights)
    slots = [max(int(0.55 * fps), int(round(n_conv * w / tot))) for w in weights]

    i = 0
    # --- act 1: lockscreen. Deliberately tight. The banner is the hook, but a
    # lockscreen nobody is touching is dead air, so the dwell between "banner has
    # landed" and "finger taps it" is an EXPLICIT short phase rather than whatever
    # is left over — otherwise a longer --lock-seconds just buys more staring.
    n_blank = max(2, int(0.20 * fps))       # wallpaper alone, so it reads as a phone
    n_spring = max(4, int(0.30 * fps))      # the banner springs in
    n_tap = max(5, int(0.30 * fps))         # finger down, flash, open
    n_read = max(2, n_lock - n_blank - n_spring - n_tap)
    tap_at = n_blank + n_spring + n_read
    for k in range(n_lock):
        bp = 0.0 if k < n_blank else min(1.0, (k - n_blank) / n_spring)
        ta = fl = 0.0
        if k >= tap_at:
            q = (k - tap_at) / max(1, n_lock - tap_at)
            ta = max(0.0, 1 - abs(q - 0.35) / 0.5)
            fl = max(0.0, 1 - abs(q - 0.6) / 0.45)
        _save(_lock_frame(paper, T, spec, bp, ta, fl), tmp, i)
        i += 1

    # --- act 2: the banner opens into the thread
    first = _thread_frame(spec, items, T, C, 1, False, 1.0, 0.0, False)
    last_lock = _lock_frame(paper, T, spec, 1.0, 0.0, 0.9)
    for k in range(n_trans):
        q = _ease_out_cubic((k + 1) / n_trans)
        blend = Image.blend(last_lock, first, q)
        # the incoming screen also scales up very slightly, like a real app open
        _save(blend, tmp, i)
        i += 1

    # --- act 3: the conversation
    kb = 0.0                       # keyboard presence persists between messages
    for idx, slot in enumerate(slots):
        m = msgs[idx]
        nxt = msgs[idx + 1] if idx + 1 < len(msgs) else None
        out = m.get("from") == "you"

        if out:
            # The viewer composes: keyboard rises, the text is typed into the field,
            # the send button lights, the finger taps it, the bubble flies in.
            text = m.get("text", "")
            n_up = 0 if kb >= 1.0 else max(3, int(0.24 * fps))
            n_type = max(5, min(int(1.0 * fps), int(len(text) * 0.030 * fps)))
            n_send = max(4, int(0.22 * fps))
            n_rest = max(int(0.40 * fps), slot - n_up - n_type - n_send)

            for k in range(n_up):
                kb = _ease_out_cubic((k + 1) / n_up)
                _save(_thread_frame(spec, items, T, C, idx, False, 1.0, 0.0, False,
                                    kb=kb, field="", caret=True), tmp, i)
                i += 1
            kb = 1.0
            for k in range(n_type):
                cut = max(1, int(round(len(text) * (k + 1) / n_type)))
                _save(_thread_frame(spec, items, T, C, idx, False, 1.0, 0.0, False,
                                    kb=1.0, field=text[:cut],
                                    caret=(k // 5) % 2 == 0), tmp, i)
                i += 1
            sx, sy = _send_centre(1.0)
            for k in range(n_send):
                q = (k + 1) / n_send
                f = _thread_frame(spec, items, T, C, idx, False, 1.0, 0.0, False,
                                  kb=1.0, field=text, caret=False, send=q > 0.35)
                _save(_touch(f, sx, sy, scale=0.62,
                             alpha=max(0.0, 1 - abs(q - 0.45) / 0.55)), tmp, i)
                i += 1
            drop = max(2, int(0.22 * fps))
            for k in range(n_rest):
                enter = min(1.0, (k + 1) / max(2, int(0.22 * fps)))
                # the keyboard only dismisses when NIS is about to answer
                if nxt and nxt.get("from") == "nis":
                    kb = 1.0 - _ease_out_cubic(min(1.0, k / drop))
                deliver = (idx == len(msgs) - 1 and k > n_rest * 0.4)
                _save(_thread_frame(spec, items, T, C, idx + 1, False, enter, 0.0,
                                    deliver, kb=kb), tmp, i)
                i += 1
        else:
            wants_typing = idx > 0 and m.get("typing", True)
            n_typ = int(slot * 0.38) if wants_typing else 0
            for k in range(n_typ):
                _save(_thread_frame(spec, items, T, C, idx, True, 1.0,
                                    (i / fps) * 0.9, False, kb=kb), tmp, i)
                i += 1
            for k in range(slot - n_typ):
                enter = min(1.0, (k + 1) / max(2, int(0.22 * fps)))
                _save(_thread_frame(spec, items, T, C, idx + 1, False, enter, 0.0,
                                    False, kb=kb), tmp, i)
                i += 1

    while i < n:     # pad the tail so the last beat can breathe
        _save(_thread_frame(spec, items, T, C, len(items), False, 1.0, 0.0,
                            msgs[-1].get("from") == "you", kb=kb), tmp, i)
        i += 1
    return i


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=22.0)
    ap.add_argument("--lock-seconds", type=float, default=1.6,
                    help="the whole lockscreen act (wallpaper → banner → tap). "
                         "Extra time here becomes dwell on the banner, so keep it "
                         "short unless the preview line is long.")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    sp = pathlib.Path(args.spec)
    spec = json.loads(sp.read_text())
    spec["_dir"] = str(sp.parent)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="chatreel-"))
    try:
        n = render_frames(spec, tmp, args.seconds, args.fps, args.lock_seconds)
        mp4 = out / "chat_reel.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(args.fps), "-i", str(tmp / "%05d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(args.fps),
             "-movflags", "+faststart", str(mp4)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.copy(tmp / "00000.png", out / "chat_reel_poster.png")
        for t in (0.06, 0.20, 0.55, 0.92):
            k = min(n - 1, int(t * n))
            shutil.copy(tmp / f"{k:05d}.png", out / f"chat_reel_preview_{int(t*100):02d}.png")
        print(f"reel → {mp4}  ({n} frames, {len(spec['messages'])} messages)")
        print(f"poster → {out / 'chat_reel_poster.png'}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
