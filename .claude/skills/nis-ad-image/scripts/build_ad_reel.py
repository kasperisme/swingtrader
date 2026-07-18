"""Render a ~15s vertical (9:16) REEL from the SAME ad.json the single-image ad uses.

The News Impact Screener brand sits on screen the whole time; the text elements then
FLY into frame from the left one at a time (fast, with an ease-back overshoot), paced
across the clip and finishing on the CTA — which then breathes with a soft glow to invite
the tap. Reuses nis-ad-image's layout primitives so the reel matches the static ad.

    cd code/analytics
    .venv/bin/python ../../.claude/skills/nis-ad-image/scripts/build_ad_reel.py \
        --spec output/ads/<slug>/<lead-magnet>/ad.json [--seconds 15] [--fps 30] [--music track.mp3]

Outputs next to the spec: 9x16/ad_reel.mp4, 9x16/ad_reel_poster.png, ad_reel_preview_*.png.

Music: leave it silent and add Meta's licensed track in the Reels ad editor (rights-
cleared) — or pass --music with a royalty-free file you own. Never bundle copyrighted audio.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_ad_image as ai  # noqa: E402  — reuse the exact static layout primitives

TRAVEL = 560       # px an element flies in from the left
REVEAL = 0.5       # seconds per fly-in


def _ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def _ease_back(p: float) -> float:   # overshoot, for a lively "fly-in"
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _blocks(spec, W, H):
    """Ordered layout blocks as (kind, height, draw(d, x, y), y_top). Same measuring
    math as build_ad_image.render — draw fns take an x so we can slide them in."""
    T = ai.THEMES.get(spec.get("theme", "dark"), ai.THEMES["dark"])
    accent = ai._ACCENT.get(spec.get("accent", "amber"), ai.AMBER)
    brand = spec.get("brand", "newsimpactscreener.com")
    maxw = W - 2 * ai.MARGIN
    measure = ImageDraw.Draw(Image.new("RGB", (W, H)))

    hl_size = 82
    hl_font = ai._f(hl_size, "bold")
    hl_lines = ai._wrap(measure, spec["headline"], hl_font, maxw)
    hl_lh = int(hl_size * 1.14)
    sub_lines = ai._wrap(measure, spec.get("subhead", ""), ai._f(38, "reg"), maxw) if spec.get("subhead") else []
    sub_lh = int(38 * 1.34)
    proof = spec.get("proof")

    b: list[tuple[str, int, object]] = []
    b.append(("logo", 60, lambda d, x, y: ai._logo(d, x, y, T, accent, brand, spec.get("mark", "NIS"))))
    if spec.get("kicker"):
        kf = ai._f(26, "mono")
        b.append(("kicker", 40, lambda d, x, y, kf=kf: d.text((x, y + 20), spec["kicker"].upper(),
                                                              font=kf, fill=(*ai._hex(accent), 255), anchor="lm")))
    b.append(("headline", hl_lh * len(hl_lines),
              lambda d, x, y: ai._headline_accent(d, x, y + hl_lh // 2, hl_lines, hl_font, T["ink"],
                                                  accent, spec.get("headline_accent", ""), hl_lh)))
    if sub_lines:
        b.append(("subhead", sub_lh * len(sub_lines),
                  lambda d, x, y: [d.text((x, y + i * sub_lh + sub_lh // 2), ln, font=ai._f(38, "reg"),
                                          fill=(*ai._hex(T["mut"]), 255), anchor="lm")
                                   for i, ln in enumerate(sub_lines)]))
    for bl in spec.get("bullets", []):
        b.append(("bullet", 54, lambda d, x, y, bl=bl: ai._check(d, x, y + 22, T, accent, bl)))
    if proof:
        b.append(("proof", 200, lambda d, x, y: ai._proof(d, x, y, W, T, accent, proof["ticker"],
                                                          float(proof["ret"]), float(proof["spy"]))))
    b.append(("cta", 92, lambda d, x, y: ai._cta(d, x, y, T, accent, spec.get("cta_label", "Learn more"))))

    safe_top, safe_bot, gap = int(H * 0.10), int(H * 0.82), 40
    total = sum(h for _, h, _ in b) + gap * (len(b) - 1)
    y = safe_top + max(0, (safe_bot - safe_top - total) // 2)
    placed = []
    for kind, h, fn in b:
        placed.append((kind, h, fn, y))
        y += h + gap
    return placed


def _draw(fn, x, y, W, H, alpha=1.0):
    """Render one element onto its own transparent layer at (x, y), scaled to alpha."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fn(ImageDraw.Draw(ov, "RGBA"), x, y)
    if alpha < 1.0:
        ov.putalpha(ov.split()[3].point(lambda v: int(v * alpha)))
    return ov


def _gradient(W, H, T):
    """The static dark brand gradient — rendered once; the motif drifts over it."""
    img = Image.new("RGB", (W, H), ai._hex(T["bg_top"]))
    d = ImageDraw.Draw(img)
    top, bot = ai._hex(T["bg_top"]), ai._hex(T["bg_bot"])
    for y in range(H):
        f = y / H
        d.line([(0, y), (W, y)], fill=tuple(round(top[i] * (1 - f) + bot[i] * f) for i in range(3)))
    return img.convert("RGBA")


def _motif_strip(W, H, T, accent, tickers, chart, scroll_max):
    """A wide (W + scroll) transparent strip — grid + a drifting chart line + an
    optional ticker-tape of the topic's tickers. Rendered ONCE; each frame pans a
    W-window across it (leftward), so the background is alive but cheap. The tickers
    are what tie it to the ad's topic — same motif, different names per topic."""
    sw = W + scroll_max + 40
    strip = Image.new("RGBA", (sw, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(strip, "RGBA")
    grid, step = (*ai._hex(T["grid"]), 55), 108          # 1080/108 = 10 → grid pans cleanly
    for x in range(0, sw, step):
        d.line([(x, 0), (x, H)], fill=grid, width=1)
    for y in range(0, H, step):
        d.line([(0, y), (sw, y)], fill=grid, width=1)
    if chart:
        ac, base_y, amp = ai._hex(accent), int(H * 0.80), int(H * 0.07)
        pts = []
        for i in range(sw // 14 + 1):
            x = i * 14
            y = base_y - (x / sw) * amp * 1.2 + math.sin(i * 0.5) * amp * 0.5 + math.sin(i * 1.7 + 0.5) * amp * 0.25
            pts.append((x, int(y)))
        d.line(pts, fill=(*ac, 55), width=16, joint="curve")   # faux glow (no per-frame blur)
        d.line(pts, fill=(*ac, 165), width=4, joint="curve")
    if tickers:
        tf, ty = ai._f(30, "mono"), int(H * 0.90)
        unit = "    ".join(f"${t}" for t in tickers) + "    "
        uw = max(1, int(d.textlength(unit, font=tf)))
        x = 0
        while x < sw:
            d.text((x, ty), unit, font=tf, fill=(*ai._hex(T["mut2"]), 110), anchor="lm")
            x += uw
    return strip


# ── central rising "stock price" chart ───────────────────────────────────────
# A jagged uptrend across the full width that DRAWS ITSELF left→right over the clip
# (like a live price climbing), with a soft area fill + a glowing leading dot.

def _rising_series(W, H):
    y0, y1, n = int(H * 0.77), int(H * 0.40), 220         # start low-left → end high-right (fine res)
    amp = (y0 - y1) * 0.28
    pts = []
    for i in range(n + 1):
        f = i / n
        wob = (math.sin(f * 17) * 0.5 + math.sin(f * 6.3 + 1.1) * 0.8 + math.sin(f * 2.7) * 0.6) / 1.9
        pts.append((W * f, y0 + (y1 - y0) * f - wob * amp))   # floats — smooth interpolation
    return pts


def _draw_rising(img, t, pts, seconds, accent):
    ac, W, H = ai._hex(accent), img.width, img.height
    n = len(pts) - 1
    prog = min(1.0, t / (seconds * 0.82))                 # drawn in over ~82% of the clip
    fpos = prog * n                                        # fractional position along the line
    k = min(n, int(fpos))
    seg = [(int(x), int(y)) for x, y in pts[:k + 1]]
    if k < n:                                              # interpolate the leading tip → glides
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        f = fpos - k
        seg.append((int(x0 + (x1 - x0) * f), int(y0 + (y1 - y0) * f)))
    if len(seg) < 2:
        seg = [(int(pts[0][0]), int(pts[0][1])), (int(pts[1][0]), int(pts[1][1]))]
    fill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(fill).polygon(seg + [(seg[-1][0], H), (seg[0][0], H)], fill=(*ac, 15))
    img.alpha_composite(fill)
    d = ImageDraw.Draw(img, "RGBA")
    d.line(seg, fill=(*ac, 42), width=14, joint="curve")  # faux glow
    d.line(seg, fill=(*ac, 122), width=5, joint="curve")
    lx, ly = seg[-1]                                       # leading "current price" dot
    d.ellipse([lx - 15, ly - 15, lx + 15, ly + 15], fill=(*ac, 55))
    d.ellipse([lx - 8, ly - 8, lx + 8, ly + 8], fill=(*ac, 210))


# ── icon-driven topic layers ─────────────────────────────────────────────────
# Rather than hand-draw each motif, pull icons from ONE font (Font Awesome) so every
# ad shares a consistent theme, and animate the glyphs. A "layer" is an icon drifting
# across a horizontal band; a "scene" is just a named preset of layers. To theme a new
# topic you NAME icons — you don't draw them.

_ICON_FONT = pathlib.Path(__file__).resolve().parent / "assets" / "fa-solid-900.ttf"
_icon_fonts: dict = {}
_glyph_cache: dict = {}

# semantic name → Font Awesome 6 (Free Solid) codepoint. Add rows freely.
ICON_MAP = {
    "jet": 0xf0fb, "jet-fighter": 0xf0fb, "plane": 0xf072, "rocket": 0xf135,
    "ship": 0xf21a, "tanker": 0xf21a, "truck": 0xf0d1, "satellite": 0xf7bf,
    "chip": 0xf2db, "microchip": 0xf2db, "bolt": 0xf0e7, "gas-pump": 0xf52f,
    "oil": 0xf613, "industry": 0xf275, "coins": 0xf51e, "chart": 0xf201,
    "globe": 0xf0ac, "shield": 0xf3ed, "building": 0xf1ad, "gauge": 0xf624,
}

# Icons that come from a bundled PNG asset instead of the font (richer/thematic art —
# e.g. Game Icons). Recolored + tinted the same way, so they animate identically.
ICON_ASSETS = {"cargo-ship": "cargo-ship.png"}
_asset_cache: dict = {}

# Default facing of directional icons → we auto-flip so the nose matches `dir`.
_ICON_FACES = {"jet": "right", "jet-fighter": "right", "plane": "right",
               "truck": "left", "cargo-ship": "right"}

# Scene presets = named lists of layers. `flip` orients icons that face a fixed way
# (FA jet/plane point left/right) to their travel direction. Keep everything dim.
SCENE_PRESETS = {
    "tanker": [   # geopolitics / oil / Hormuz — cargo ships one way, jets the other
        {"icon": "cargo-ship", "dir": "left", "band": 0.73, "count": 2, "size": 170, "alpha": 85},
        {"icon": "jet", "dir": "right", "band": 0.16, "count": 2, "size": 96, "alpha": 95,
         "speed": 2.3, "trail": True},
    ],
    "ai": [       # AI / semiconductors
        {"icon": "chip", "dir": "left", "band": 0.74, "count": 2, "size": 140, "alpha": 75, "color": "accent"},
        {"icon": "satellite", "dir": "right", "band": 0.16, "count": 1, "size": 100, "alpha": 85, "speed": 1.6},
    ],
    "energy": [
        {"icon": "oil", "dir": "left", "band": 0.74, "count": 2, "size": 140, "alpha": 85},
        {"icon": "bolt", "dir": "right", "band": 0.16, "count": 2, "size": 96, "alpha": 90, "speed": 2.0},
    ],
    "crypto": [
        {"icon": "coins", "dir": "left", "band": 0.74, "count": 2, "size": 140, "alpha": 85, "color": "accent"},
        {"icon": "rocket", "dir": "right", "band": 0.16, "count": 2, "size": 96, "alpha": 90,
         "speed": 2.2, "trail": True},
    ],
}


def _icon_font(size):
    if not _ICON_FONT.exists():
        return None
    if size not in _icon_fonts:
        _icon_fonts[size] = ImageFont.truetype(str(_ICON_FONT), size)
    return _icon_fonts[size]


def _glyph(cp, size, color, alpha, flip):
    key = (cp, size, color, alpha, flip)
    if key in _glyph_cache:
        return _glyph_cache[key]
    f = _icon_font(size)
    if f is None:
        return None
    s = size * 3
    tmp = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((s // 2, s // 2), chr(cp), font=f, fill=(*color, alpha), anchor="mm")
    bb = tmp.getbbox()
    tile = tmp.crop(bb) if bb else tmp
    if flip:
        tile = tile.transpose(Image.FLIP_LEFT_RIGHT)
    _glyph_cache[key] = tile
    return tile


def _asset_tile(name, size, color, alpha, flip):
    """A bundled PNG icon, cropped, scaled to `size`, and re-tinted to `color`."""
    key = (name, size, color, alpha, flip)
    if key in _asset_cache:
        return _asset_cache[key]
    p = _ICON_FONT.parent / ICON_ASSETS[name]
    if not p.exists():
        return None
    im = Image.open(p).convert("RGBA")
    bb = im.getbbox()
    if bb:
        im = im.crop(bb)
    scale = size / max(im.size)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
    a = im.split()[3].point(lambda v: int(v * alpha / 255))   # source shape × layer alpha
    tile = Image.new("RGBA", im.size, (*color, 0))
    tile.putalpha(a)
    if flip:
        tile = tile.transpose(Image.FLIP_LEFT_RIGHT)
    _asset_cache[key] = tile
    return tile


def _draw_layers(img, t, layers, W, H, T, accent):
    """Draw each icon layer (a glyph/asset drifting across a band) onto the frame."""
    for lay in layers:
        name = str(lay.get("icon", "")).lower()
        cp = ICON_MAP.get(name)
        if name not in ICON_ASSETS and cp is None:
            continue
        dirn = lay.get("dir", "left")
        # auto-flip a directional icon so its nose matches travel (explicit `flip` wins)
        faces = _ICON_FACES.get(name)
        flip = lay.get("flip", bool(faces and faces != dirn))
        color = ai._hex(accent) if lay.get("color") == "accent" else ai._hex(T["mut2"])
        size, alpha = int(lay.get("size", 120)), int(lay.get("alpha", 90))
        tile = (_asset_tile(name, size, color, alpha, flip) if name in ICON_ASSETS
                else _glyph(cp, size, color, alpha, flip))
        if tile is None:
            continue
        tw, th = tile.size
        band, count = float(lay.get("band", 0.5)), int(lay.get("count", 1))
        period, span = max(3.0, 22.0 / float(lay.get("speed", 1.0))), W + tw + 320
        trail_dir = 1 if dirn == "left" else -1          # trail sits behind the travel direction
        for k in range(count):
            frac = (t / period + k / max(1, count)) % 1.0
            x = (int(W + tw // 2 + 140 - frac * span) if dirn == "left"
                 else int(-tw // 2 - 140 + frac * span))
            y = int(H * band) + int(math.sin(t * 1.2 + k) * 4)
            if lay.get("trail"):
                d = ImageDraw.Draw(img, "RGBA")
                for i in range(6):
                    cx = x + trail_dir * (tw // 2 + 14 + i * 24)
                    d.line([(cx, y), (cx - trail_dir * 16, y)],
                           fill=(*ai._hex(T["mut2"]), max(0, 55 - i * 9)), width=2)
            img.alpha_composite(tile, (x - tw // 2, y - th // 2))


def render_reel(spec, out_dir: pathlib.Path, seconds: float, fps: int, music: str | None):
    W, H = ai.SIZES["9x16"]
    T = ai.THEMES.get(spec.get("theme", "dark"), ai.THEMES["dark"])
    accent = ai._ACCENT.get(spec.get("accent", "amber"), ai.AMBER)
    x0 = ai.MARGIN
    bg_image = (out_dir / spec["background_image"]).resolve() if spec.get("background_image") else None

    # ── animated background (drifts behind the text; topic-linked via its tickers) ──
    bgspec = spec.get("background") or {}
    motif = bgspec.get("motif", "chart")            # chart | grid | none
    scene = bgspec.get("scene")                     # a preset name (tanker, ai, energy, crypto)
    # explicit icon layers win; else expand the scene preset. Each layer = an animated icon.
    layers = list(bgspec.get("icons") or []) or SCENE_PRESETS.get(str(scene or "").lower(), [])
    rising = bool(bgspec.get("rising"))             # central "stock price" chart drawing upward
    rising_pts = _rising_series(W, H) if rising else None
    bg_tickers = [str(t).upper() for t in (bgspec.get("tickers") or [])]
    scroll_speed = 42.0 * float(bgspec.get("speed", 1.0))   # px/sec leftward drift
    scroll_max = int(scroll_speed * seconds) + 2
    if bg_image or motif == "none":                 # a photo (or opt-out) stays static
        base = ai._background(W, H, T, "9x16", bg_image, accent).convert("RGBA")
        strip = None
    else:
        base = _gradient(W, H, T)
        # the icon layers replace the generic chart line (keeps it uncluttered)
        strip = _motif_strip(W, H, T, accent, bg_tickers, motif == "chart" and not layers, scroll_max)

    def background_at(t: float):
        if strip is None:
            return base.copy()
        off = min(int(t * scroll_speed), strip.width - W)
        b = base.copy()
        b.alpha_composite(strip.crop((off, 0, off + W, H)))
        return b

    placed = _blocks(spec, W, H)
    persistent = [p for p in placed if p[0] == "logo"]          # brand — always on screen
    anim = [p for p in placed if p[0] != "logo"]                # fly in

    # front-loaded pacing: everything flown in by ~55% of the clip, CTA last
    first, window = 0.25, seconds * 0.55
    step = (window - first) / max(1, len(anim) - 1)
    starts = [first + i * step for i in range(len(anim))]
    cta_i = next((i for i, p in enumerate(anim) if p[0] == "cta"), len(anim) - 1)
    cta_settle = starts[cta_i] + REVEAL
    cta_y = anim[cta_i][3]
    cta_font = ai._f(38, "bold")
    cta_w = int(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(
        spec.get("cta_label", "Learn more"), font=cta_font)) + 88

    def cta_glow(t: float) -> Image.Image | None:
        if t < cta_settle:
            return None
        breathe = 0.5 + 0.5 * math.sin(2 * math.pi * (t - cta_settle) / 1.7)
        ga = int(40 + 60 * breathe)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ov).rounded_rectangle(
            [x0 - 18, cta_y - 18, x0 + cta_w + 18, cta_y + 92 + 18], radius=32, fill=(*ai._hex(accent), ga))
        return ov.filter(ImageFilter.GaussianBlur(22))

    def frame_at(t: float) -> Image.Image:
        img = background_at(t)
        if layers:                                              # topic icons, drifting behind the text
            _draw_layers(img, t, layers, W, H, T, accent)
        if rising_pts is not None:                              # central rising stock chart
            _draw_rising(img, t, rising_pts, seconds, accent)
        for _, _, fn, y in persistent:                          # brand, always full opacity
            img = Image.alpha_composite(img, _draw(fn, x0, y, W, H))
        glow = cta_glow(t)
        if glow is not None:
            img = Image.alpha_composite(img, glow)
        for (kind, _, fn, y), start in zip(anim, starts):
            raw = (t - start) / REVEAL
            if raw <= 0:
                continue
            prog = min(1.0, raw)
            x_off = int(-(1 - _ease_back(prog)) * TRAVEL)       # fly from left + overshoot
            img = Image.alpha_composite(img, _draw(fn, x0 + x_off, y, W, H, alpha=min(1.0, raw * 1.9)))
        return img.convert("RGB")

    nframes = int(round(seconds * fps))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ad_reel_"))
    for f in range(nframes):
        frame_at(f / fps).save(tmp / f"{f:05d}.png")

    rdir = out_dir / "9x16"
    rdir.mkdir(parents=True, exist_ok=True)
    out_mp4 = rdir / "ad_reel.mp4"
    frame_at(seconds).save(rdir / "ad_reel_poster.png")

    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tmp / "%05d.png")]
    if music and pathlib.Path(music).exists():
        cmd += ["-i", music, "-c:a", "aac", "-b:a", "128k",
                "-af", f"afade=t=out:st={max(0, seconds - 1):.2f}:d=1", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-movflags", "+faststart", str(out_mp4)]
    subprocess.run(cmd, check=True, capture_output=True)

    for sec in (0.6, seconds * 0.35, seconds * 0.55, seconds - 0.2):
        frame_at(sec).save(rdir / f"ad_reel_preview_{sec:04.1f}s.png")
    return out_mp4


def main():
    ap = argparse.ArgumentParser(description="Render a lively 9:16 reel from an nis-ad-image ad.json.")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--music", help="optional royalty-free audio file to mux (else silent)")
    args = ap.parse_args()

    spec = json.loads(pathlib.Path(args.spec).read_text())
    out = pathlib.Path(args.spec).resolve().parent
    mp4 = render_reel(spec, out, args.seconds, args.fps, args.music)

    # resolved design genome (so nis-ad-launch's manifest/design join works for the reel)
    design = ai._derive_design(spec, out, ["9x16"])
    design.update({"format": "reel", "seconds": args.seconds, "fps": args.fps})
    (out / "design.json").write_text(json.dumps(design, indent=2))

    print(f"reel → {mp4}")
    print(f"poster → {out / '9x16' / 'ad_reel_poster.png'}")
    if not args.music:
        print("(silent — add Meta's licensed music in the Reels ad editor, or pass --music)")


if __name__ == "__main__":
    main()
