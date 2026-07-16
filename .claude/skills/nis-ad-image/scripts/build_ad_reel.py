"""Render a ~15s vertical (9:16) REEL from the SAME ad.json the single-image ad uses.

The text elements transition in one at a time (fade + slide-up, ease-out), paced
across the clip, finishing on the CTA with a little pop — so the reel is visually
identical to the static ad, just animated. Reuses nis-ad-image's layout primitives.

    cd code/analytics
    .venv/bin/python ../../.claude/skills/nis-ad-image/scripts/build_ad_reel.py \
        --spec output/ads/<slug>/<lead-magnet>/ad.json [--seconds 15] [--fps 30] [--music track.mp3]

Outputs next to the spec:
    9x16/ad_reel.mp4          the reel (silent unless --music)
    9x16/ad_reel_poster.png   thumbnail (settled frame)

Music: leave it silent and add Meta's licensed track in the Reels ad editor (rights-
cleared, and it's what Meta recommends) — or pass --music with a royalty-free file you
own. Do NOT drop in copyrighted music.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_ad_image as ai  # noqa: E402  — reuse the exact static layout primitives

import json  # noqa: E402


def _ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


def _ease_back(p: float) -> float:  # slight overshoot, for the CTA "pop"
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _blocks(spec, W, H):
    """Mirror the static layout: an ordered list of (kind, height, draw(d, y)) plus
    the top y each element settles at. Same measuring math as build_ad_image.render."""
    T = ai.THEMES.get(spec.get("theme", "dark"), ai.THEMES["dark"])
    accent = ai._ACCENT.get(spec.get("accent", "amber"), ai.AMBER)
    brand = spec.get("brand", "newsimpactscreener.com")
    x = ai.MARGIN
    maxw = W - 2 * ai.MARGIN
    measure = ImageDraw.Draw(Image.new("RGB", (W, H)))

    hl_size = 82
    hl_font = ai._f(hl_size, "bold")
    hl_lines = ai._wrap(measure, spec["headline"], hl_font, maxw)
    hl_lh = int(hl_size * 1.14)
    sub_lines = ai._wrap(measure, spec.get("subhead", ""), ai._f(38, "reg"), maxw) if spec.get("subhead") else []
    sub_lh = int(38 * 1.34)
    proof = spec.get("proof")

    blk: list[tuple[str, int, object]] = []
    blk.append(("logo", 60, lambda d, y: ai._logo(d, x, y, T, accent, brand, spec.get("mark", "NIS"))))
    if spec.get("kicker"):
        kf = ai._f(26, "mono")
        blk.append(("kicker", 40, lambda d, y, kf=kf: d.text((x, y + 20), spec["kicker"].upper(),
                                                              font=kf, fill=(*ai._hex(accent), 255), anchor="lm")))
    blk.append(("headline", hl_lh * len(hl_lines),
                lambda d, y: ai._headline_accent(d, x, y + hl_lh // 2, hl_lines, hl_font, T["ink"],
                                                 accent, spec.get("headline_accent", ""), hl_lh)))
    if sub_lines:
        blk.append(("subhead", sub_lh * len(sub_lines),
                    lambda d, y: [d.text((x, y + i * sub_lh + sub_lh // 2), ln, font=ai._f(38, "reg"),
                                         fill=(*ai._hex(T["mut"]), 255), anchor="lm")
                                  for i, ln in enumerate(sub_lines)]))
    for b in spec.get("bullets", []):
        blk.append(("bullet", 54, lambda d, y, b=b: ai._check(d, x, y + 22, T, accent, b)))
    if proof:
        blk.append(("proof", 200, lambda d, y: ai._proof(d, x, y, W, T, accent, proof["ticker"],
                                                         float(proof["ret"]), float(proof["spy"]))))
    blk.append(("cta", 92, lambda d, y: ai._cta(d, x, y, T, accent, spec.get("cta_label", "Learn more"))))

    # vertical-center the stack in the safe band (same as the static ad)
    safe_top, safe_bot, gap = int(H * 0.10), int(H * 0.82), 40
    total = sum(h for _, h, _ in blk) + gap * (len(blk) - 1)
    y = safe_top + max(0, (safe_bot - safe_top - total) // 2)
    placed = []
    for kind, h, fn in blk:
        placed.append((kind, h, fn, y))
        y += h + gap
    return placed


def _fade_alpha(overlay: Image.Image, p: float) -> Image.Image:
    a = overlay.split()[3].point(lambda v: int(v * p))
    overlay.putalpha(a)
    return overlay


def render_reel(spec, out_dir: pathlib.Path, seconds: float, fps: int, music: str | None):
    W, H = ai.SIZES["9x16"]
    T = ai.THEMES.get(spec.get("theme", "dark"), ai.THEMES["dark"])
    accent = ai._ACCENT.get(spec.get("accent", "amber"), ai.AMBER)
    bg_image = (out_dir / spec["background_image"]).resolve() if spec.get("background_image") else None
    background = ai._background(W, H, T, "9x16", bg_image, accent).convert("RGBA")

    placed = _blocks(spec, W, H)
    n = len(placed)
    reveal = 0.6
    # spread reveals across the clip so it plays for the full duration, CTA last
    first, last = 0.3, max(0.3, seconds - reveal - 0.4)
    step = (last - first) / (n - 1) if n > 1 else 0.0
    starts = [first + i * step for i in range(n)]
    slide = 40  # px an element rises as it fades in

    def frame_at(t: float) -> Image.Image:
        img = background.copy()
        for (kind, h, fn, y), start in zip(placed, starts):
            raw = (t - start) / reveal
            if raw <= 0:
                continue
            p = _ease_back(raw) if (kind == "cta" and raw < 1) else _ease_out(min(1.0, raw))
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            fn(ImageDraw.Draw(ov, "RGBA"), int(y + (1 - min(1.0, raw)) * slide))
            if raw < 1:
                ov = _fade_alpha(ov, min(1.0, raw))
            img = Image.alpha_composite(img, ov)
        return img.convert("RGB")

    nframes = int(round(seconds * fps))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ad_reel_"))
    prev_path, prev_key = None, None
    for f in range(nframes):
        t = f / fps
        # a frame only changes while some element is mid-transition; else reuse the last
        key = tuple(0 if (t - s) <= 0 else (2 if (t - s) / reveal >= 1 else 1) for s in starts)
        path = tmp / f"{f:05d}.png"
        if key == prev_key and prev_path is not None:
            path.write_bytes(prev_path.read_bytes())
        else:
            frame_at(t).save(path)
            prev_key = key
        prev_path = path

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

    # a few preview stills for review (delete freely)
    for sec in (1.0, seconds * 0.4, seconds * 0.7, seconds - 0.3):
        frame_at(sec).save(rdir / f"ad_reel_preview_{sec:04.1f}s.png")
    return out_mp4


def main():
    ap = argparse.ArgumentParser(description="Render a 9:16 reel from an nis-ad-image ad.json.")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--music", help="optional royalty-free audio file to mux (else silent)")
    args = ap.parse_args()

    spec = json.loads(pathlib.Path(args.spec).read_text())
    out = pathlib.Path(args.spec).resolve().parent
    mp4 = render_reel(spec, out, args.seconds, args.fps, args.music)
    print(f"reel → {mp4}")
    print(f"poster → {out / '9x16' / 'ad_reel_poster.png'}")
    if not args.music:
        print("(silent — add Meta's licensed music in the Reels ad editor, or pass --music)")


if __name__ == "__main__":
    main()
