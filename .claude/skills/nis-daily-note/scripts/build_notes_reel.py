#!/usr/bin/env python3
"""Render a vertical reel that looks like scrolling the iOS Notes list.

The conceit: each note is one real market story from the period, so scrolling the
list IS the recap. Geometry comes from build_notes_meme (true device metrics), and
the scroll is a sequence of flick-and-settle moves rather than a constant pan —
a linear crawl is the thing that instantly reads as "rendered video", not screen
recording.

    python build_notes_reel.py --rows output/notes/<date>/rows.json \
        --out output/notes/<date>/9x16 [--seconds 16] [--fps 30]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_notes_meme as nm  # noqa: E402  — reuse device metrics + fonts + chrome

P, W, H = nm.P, nm.W, nm.H
OUT_W, OUT_H = 1080, 1920

NAV_BOTTOM = P(59) + P(44)          # status bar + nav bar
ROW_H = P(78)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _split_at_width(d, text: str, font, maxw: int) -> tuple[str, str]:
    """Split `text` at the last WORD boundary that still fits — returns
    (head, tail). Breaking mid-word is the tell that gives away a fake screenshot."""
    if d.textlength(text, font=font) <= maxw:
        return text, ""
    cut, words = 0, text.split(" ")
    for i in range(1, len(words) + 1):
        candidate = " ".join(words[:i])
        if d.textlength(candidate + "…", font=font) > maxw:
            break
        cut = i
    cut = max(1, cut)
    return " ".join(words[:cut]), " ".join(words[cut:])


def _fit(d, text: str, font, maxw: int) -> str:
    head, tail = _split_at_width(d, text, font, maxw)
    return head + ("…" if tail else "")


def _pretty_date(iso: str) -> str:
    y, m, day = iso.split("-")
    return f"{int(day)} {MONTHS[int(m) - 1]}"


def _content_strip(rows, T) -> Image.Image:
    """The scrollable part: large title, search field, then every note row."""
    head_h = P(52) + P(52)                       # large title + search field
    strip = Image.new("RGB", (W, head_h + ROW_H * len(rows) + P(40)), nm._hex(T["bg"]))
    d = ImageDraw.Draw(strip)

    d.text((P(20), P(24)), "Notes", font=nm._f(34, "bold"),
           fill=(*nm._hex(T["ink"]), 255), anchor="lm")

    sy = P(52)
    d.rounded_rectangle([P(16), sy, W - P(16), sy + P(36)], radius=P(10),
                        fill=(*nm._hex("#E4E4E9" if T is nm.THEMES["light"] else "#1C1C1E"), 255))
    mx, my = P(32), sy + P(18)
    d.arc([mx - P(6), my - P(6), mx + P(6), my + P(6)], 0, 360,
          fill=(*nm._hex(T["mut"]), 255), width=P(1.5))
    d.line([(mx + P(4), my + P(4)), (mx + P(8), my + P(8))],
           fill=(*nm._hex(T["mut"]), 255), width=P(1.5))
    d.text((P(46), my), "Search", font=nm._f(17, "reg"), fill=(*nm._hex(T["mut"]), 255), anchor="lm")

    title_f, sub_f = nm._f(17, "medium"), nm._f(15, "reg")
    maxw = W - P(40)
    y = head_h
    for i, r in enumerate(rows):
        claim = r["claim"]
        head, tail = _split_at_width(d, claim, title_f, maxw)
        title = head + ("…" if tail else "")
        # The preview line continues the claim from the next WORD, as Notes previews
        # the body — never mid-word.
        rest = tail or " ".join(r.get("tickers", []))
        d.text((P(20), y + P(24)), title, font=title_f, fill=(*nm._hex(T["ink"]), 255), anchor="lm")
        date_s = _pretty_date(r["date"])
        d.text((P(20), y + P(50)), date_s, font=sub_f, fill=(*nm._hex(T["mut"]), 255), anchor="lm")
        dx = P(20) + d.textlength(date_s + "  ", font=sub_f)
        d.text((dx, y + P(50)), _fit(d, rest, sub_f, maxw - (dx - P(20))),
               font=sub_f, fill=(*nm._hex(T["mut"]), 255), anchor="lm")
        if i < len(rows) - 1:
            d.line([(P(20), y + ROW_H), (W, y + ROW_H)], fill=(*nm._hex(T["rule"]), 255), width=2)
        y += ROW_H
    return strip


def _scroll_curve(total: int, n: int, fps: int, flicks: int | None = None,
                  slow: bool = False):
    """Flick → decelerate → rest, repeatedly. Real thumb scrolling, not a pan.

    `flicks` fixes how many separate swipes cover the distance; `slow` stretches
    each drag over most of its slot and eases in AND out, which reads as a
    deliberate read-through rather than a flick. Navigating wants many quick
    flicks; reading a note wants a couple of slow ones.

    Returns (offsets, swipes) where swipes[i] is None when no finger is down, or
    0..1 through the drag — so the gesture can be drawn in sync with the content
    it is actually moving."""
    hold_start = min(int(0.7 * fps), max(2, n // 6))
    hold_end = min(int(0.5 * fps), max(2, n // 8))
    moving = max(1, n - hold_start - hold_end)
    if flicks is None:
        flicks = max(2, round((n / fps) / 1.2))
    flicks = max(1, flicks)
    drag_frac = 0.70 if slow else 0.62      # of the slot the content is moving for
    finger_frac = 0.62 if slow else 0.5     # of the slot the finger is down for
    per = moving / flicks
    travel = total / flicks

    offsets, swipes = [], []
    for i in range(n):
        if i < hold_start:
            offsets.append(0)
            swipes.append(None)
            continue
        if i >= n - hold_end:
            offsets.append(total)
            swipes.append(None)
            continue
        k = i - hold_start
        idx = min(int(k // per), flicks - 1)
        local = (k - idx * per) / per                  # 0..1 within this flick
        glide = min(1.0, local / drag_frac)
        # smoothstep for a slow drag (eases in and out); ease-out cubic for a flick
        # (starts fast, coasts to a stop under its own inertia).
        eased = glide * glide * (3 - 2 * glide) if slow else 1 - (1 - glide) ** 3
        offsets.append(int(min(total, travel * (idx + eased))))
        # The finger is down for the drag itself; the rest of the slot is inertia.
        swipes.append(local / finger_frac if local < finger_frac else None)
    return offsets, swipes


def _list_frame(strip, off, T, clock, viewport_h, highlight=None):
    """One frame of the scrolling list. `highlight` is a strip-space y-range to
    paint as a pressed row."""
    frame = Image.new("RGB", (W, H), nm._hex(T["bg"]))
    window = strip.crop((0, off, W, min(strip.height, off + viewport_h))).copy()
    if highlight:
        top, bot = highlight[0] - off, highlight[1] - off
        if bot > 0 and top < viewport_h:
            press = Image.new("RGB", (W, max(1, int(bot - top))),
                              nm._hex("#D1D1D6" if T is nm.THEMES["light"] else "#2C2C2E"))
            # Re-draw the row over the press colour so the text stays legible.
            row = strip.crop((0, max(0, highlight[0]), W, highlight[1]))
            press.paste(Image.blend(press, row.convert("RGB"), 0.72), (0, 0))
            window.paste(press, (0, int(top)))
    frame.paste(window, (0, NAV_BOTTOM))
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, W, NAV_BOTTOM], fill=nm._hex(T["bg"]))
    nm._chrome_list(d, T, clock, collapsed=off > P(30))
    return frame


def _detail_frame(note_strip, off, T, clock, viewport_h):
    """The opened note, scrolled by `off` under fixed detail chrome."""
    frame = Image.new("RGB", (W, H), nm._hex(T["bg"]))
    window = note_strip.crop((0, off, W, min(note_strip.height, off + viewport_h)))
    frame.paste(window, (0, NAV_BOTTOM))
    d = ImageDraw.Draw(frame)
    d.rectangle([0, 0, W, NAV_BOTTOM], fill=nm._hex(T["bg"]))
    nm._chrome(d, T, clock)
    return frame


def _touch(frame, cx, cy, scale=1.0, alpha=1.0):
    """The translucent finger dot iOS screen recordings show for a tap — it's what
    makes the tap legible as a tap rather than a cut."""
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


def _swipe(frame, p):
    """Finger dragging upward — what is actually causing the scroll."""
    if p is None:
        return frame
    y0, y1 = int(H * 0.70), int(H * 0.34)
    cy = int(y0 + (y1 - y0) * p)
    fade = min(1.0, p / 0.18, (1 - p) / 0.18)
    return _touch(frame, int(W * 0.52), cy, scale=1.0, alpha=max(0.0, fade))


def _save(frame, tmp, i):
    frame.crop((0, 0, W, int(W * OUT_H / OUT_W))) \
         .resize((OUT_W, OUT_H), Image.LANCZOS) \
         .save(tmp / f"{i:05d}.png")


def render_frames(rows, spec, summary, tmp: pathlib.Path, seconds: float, fps: int,
                  nav: float = 3.0) -> int:
    """Scroll the relevant news, then tap into the summary note and hold on it."""
    T = nm.THEMES.get(spec.get("theme", "light"), nm.THEMES["light"])
    clock = spec.get("clock", "9:41")
    strip = _content_strip(rows, T)
    # The reel crops the device screenshot to 9:16, so the visible content area is
    # SHORTER than the device viewport. Scrolling against the device height leaves
    # the final row (the summary note) below the crop, invisible when it's tapped.
    crop_h = int(W * OUT_H / OUT_W)
    viewport_h = crop_h - NAV_BOTTOM
    total = max(0, strip.height - viewport_h)

    n_total = int(seconds * fps)
    n_hover = max(1, int(0.34 * fps))
    n_press = max(1, int(0.20 * fps))
    n_push = max(1, int(0.30 * fps))
    # Navigation is setup, not payload: getting to the note is capped at `nav`
    # seconds and EVERYTHING left over is spent reading it.
    n_nav = max(int(1.2 * fps), int(nav * fps))
    n_scroll = max(int(0.5 * fps), n_nav - n_hover - n_press - n_push)

    offsets, swipes = _scroll_curve(total, n_scroll, fps)
    i = 0
    for off, sw in zip(offsets, swipes):
        _save(_swipe(_list_frame(strip, off, T, clock, viewport_h), sw), tmp, i)
        i += 1

    if not summary:
        return i

    # The summary note is the last row: hover onto it, press, then push the note in.
    head_h = P(52) + P(52)
    row_top = head_h + ROW_H * (len(rows) - 1)
    band = (row_top, row_top + ROW_H)
    row_cy = NAV_BOTTOM + (row_top - total) + ROW_H // 2
    tap_x = int(W * 0.42)

    for k in range(n_hover):
        p = (k + 1) / n_hover
        eased = 1 - (1 - p) ** 3
        cx = int(W * 0.78 + (tap_x - W * 0.78) * eased)
        cy = int(row_cy + P(120) * (1 - eased))
        _save(_touch(_list_frame(strip, total, T, clock, viewport_h), cx, cy,
                     scale=1.0, alpha=min(1.0, p * 2)), tmp, i)
        i += 1

    for k in range(n_press):
        p = (k + 1) / n_press
        _save(_touch(_list_frame(strip, total, T, clock, viewport_h, highlight=band),
                     tap_x, row_cy, scale=1 - 0.22 * p, alpha=1.0), tmp, i)
        i += 1

    base = _list_frame(strip, total, T, clock, viewport_h)
    # The pushed-in view is the top of the very strip the read phase scrolls, so
    # the transition lands on frame-0 of the read with no jump.
    _pre_strip = nm.render_note_strip(summary)
    detail = _detail_frame(_pre_strip, 0, T, clock, viewport_h)
    for k in range(n_push):
        p = (k + 1) / n_push
        eased = 1 - (1 - p) ** 3                      # iOS push easing
        frame = Image.new("RGB", (W, H), nm._hex(T["bg"]))
        frame.paste(base, (-int(W * 0.25 * eased), 0))     # outgoing view drifts left
        frame.paste(detail, (int(W * (1 - eased)), 0))     # incoming slides from right
        # The status bar does NOT travel with a push — both views carry their own,
        # so without this the Dynamic Island and clock visibly slide across.
        fd = ImageDraw.Draw(frame)
        fd.rectangle([0, 0, W, P(59)], fill=nm._hex(T["bg"]))
        nm._status_only(fd, T, clock)
        frame = _touch(frame, tap_x, row_cy, scale=0.78, alpha=max(0.0, 1 - p * 2.5))
        _save(frame, tmp, i)
        i += 1

    # Read phase — scroll the note itself for the whole remaining runtime.
    note_strip = nm.render_note_strip(summary)
    note_total = max(0, note_strip.height - viewport_h)
    n_read = max(1, n_total - i)
    if note_total == 0:
        for _ in range(n_read):
            _save(detail, tmp, i)
            i += 1
        return i
    # Two slow swipes for the whole note — it is being read, not skimmed.
    r_offsets, r_swipes = _scroll_curve(note_total, n_read, fps, flicks=2, slow=True)
    for off, sw in zip(r_offsets, r_swipes):
        _save(_swipe(_detail_frame(note_strip, off, T, clock, viewport_h), sw), tmp, i)
        i += 1
    return i


def main() -> None:
    ap = argparse.ArgumentParser(description="Notes-list scrolling reel.")
    ap.add_argument("--rows", required=True)
    ap.add_argument("--summary", help="note.json for the recap note the reel opens at the end")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=18.0)
    ap.add_argument("--nav", type=float, default=3.0,
                    help="seconds budgeted to reach and open the summary note; all "
                         "remaining runtime is spent scrolling the note itself")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--theme", default="light")
    ap.add_argument("--clock", default="9:41")
    args = ap.parse_args()

    rows = json.loads(pathlib.Path(args.rows).read_text())
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    spec = {"theme": args.theme, "clock": args.clock}

    summary = None
    if args.summary:
        summary = json.loads(pathlib.Path(args.summary).read_text())
        summary.setdefault("theme", args.theme)
        summary.setdefault("clock", args.clock)
        # The note the reel opens has to exist in the list it was opened from.
        rows = rows + [{"date": summary.get("date") or rows[0]["date"],
                        "claim": summary.get("list_title") or summary.get("title", ""),
                        "tickers": summary.get("list_preview_tickers", [])}]

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="notes_reel_"))
    try:
        n = render_frames(rows, spec, summary, tmp, args.seconds, args.fps, args.nav)
        mp4 = out / "note_reel.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(args.fps), "-i", str(tmp / "%05d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(args.fps),
             "-movflags", "+faststart", str(mp4)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.copy(tmp / "00000.png", out / "note_reel_poster.png")
        for t in (0.05, 0.45, 0.85):
            k = min(n - 1, int(t * n))
            shutil.copy(tmp / f"{k:05d}.png", out / f"note_reel_preview_{int(t*100):02d}.png")
        print(f"reel → {mp4}  ({n} frames, {len(rows)} notes)")
        print(f"poster → {out / 'note_reel_poster.png'}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
