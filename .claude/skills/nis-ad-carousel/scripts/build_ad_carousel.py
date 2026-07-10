"""Render an ad carousel (feature-led, proof-driven) for Meta + TikTok from a
Claude-authored spec. Light brand theme, both aspect ratios in one pass.

    python build_ad_carousel.py --spec output/ads/<slug>/ad.json

Outputs under output/ads/<slug>/:
    4x5/slide-01.png …      (1080×1350 — Meta feed carousel)
    9x16/slide-01.png …     (1080×1920 — TikTok / Reels)
    ad_copy.txt             (primary text · headline · CTA — paste into Ads Manager)

Spec is authored by Claude (the skill). The renderer does layout only — every
number on a proof slide must already be real (from a setup.json / benchmarks).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import matplotlib.font_manager as _fm
from PIL import Image, ImageDraw, ImageFont

# ---- brand LIGHT theme (mirrors the reels) ----
BG = "#FBF7F1"; INK = "#10182B"; MUT = "#566377"; MUT2 = "#8A93A4"; GRID = "#E4DBCE"
AMBER = "#F59E0B"; POS = "#16A34A"; NEG = "#DC2626"; PANEL = "#FFFFFF"
_ACCENT = {"amber": AMBER, "pos": POS, "green": POS, "neg": NEG, "ink": INK}

_BOLD = _fm.findfont(_fm.FontProperties(weight="bold"))
_REG = _fm.findfont(_fm.FontProperties(weight="normal"))
_MONO = _fm.findfont(_fm.FontProperties(family="monospace"))

SIZES = {"4x5": (1080, 1350), "9x16": (1080, 1920)}
MARGIN = 96


def _f(sz, kind="bold"):
    return ImageFont.truetype({"bold": _BOLD, "reg": _REG, "mono": _MONO}[kind], int(sz))


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(base, top, f):
    a, b = _hex(base), _hex(top)
    return tuple(round(a[i] * (1 - f) + b[i] * f) for i in range(3))


def _wrap(d, text, font, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------
# Elements — each is {h, draw(d, img, y)}; a slide stacks + vertically centers.
# ---------------------------------------------------------------------------
def el_kicker(d, text, accent):
    text = text.upper()
    f = _f(26, "mono")
    tw = d.textlength(text, font=f)

    def draw(dd, img, y):
        x = (W - (tw + 44)) // 2
        dd.rounded_rectangle([x, y, x + tw + 44, y + 52], radius=14,
                             fill=(*_mix("#FFFFFF", accent, 0.12), 255),
                             outline=(*_mix("#FFFFFF", accent, 0.34), 255), width=2)
        dd.text((x + 22, y + 26), text, font=f, fill=(*_hex(accent), 255), anchor="lm")
    return {"h": 52, "draw": draw, "gap": 34}


def el_headline(d, text, size, color, maxw=None):
    maxw = maxw or (W - 2 * MARGIN)
    f = _f(size, "bold")
    lines = _wrap(d, text, f, maxw)
    lh = int(size * 1.16)

    def draw(dd, img, y):
        for i, ln in enumerate(lines):
            dd.text((W // 2, y + i * lh + lh // 2), ln, font=f, fill=(*_hex(color), 255), anchor="mm")
    return {"h": lh * len(lines), "draw": draw, "gap": 26}


def el_body(d, text, size, color, maxw=None):
    maxw = maxw or (W - 2 * MARGIN - 40)
    f = _f(size, "reg")
    lines = _wrap(d, text, f, maxw)
    lh = int(size * 1.34)

    def draw(dd, img, y):
        for i, ln in enumerate(lines):
            dd.text((W // 2, y + i * lh + lh // 2), ln, font=f, fill=(*_hex(color), 255), anchor="mm")
    return {"h": lh * len(lines), "draw": draw, "gap": 40}


def el_screener_mock(d, accent):
    rows = [("NVDA-style leader", "RS 96", True), ("stacked & near highs", "RS 92", True),
            ("volume confirming", "RS 90", True)]
    pw, rh = W - 2 * MARGIN, 80
    ph = 90 + len(rows) * rh + 18

    def draw(dd, img, y):
        x = MARGIN
        dd.rounded_rectangle([x, y, x + pw, y + ph], radius=28, fill=(*_hex(PANEL), 255),
                             outline=(*_hex(GRID), 255), width=2)
        dd.text((x + 34, y + 44), "MARKET SCAN · TODAY", font=_f(22, "mono"), fill=(*_hex(MUT2), 255), anchor="lm")
        for i, (label, rs, ok) in enumerate(rows):
            ry = y + 90 + i * rh
            dd.text((x + 34, ry + rh // 2), label, font=_f(30, "bold"), fill=(*_hex(INK), 255), anchor="lm")
            chip = rs
            cf = _f(24, "mono"); cw = dd.textlength(chip, font=cf)
            cx1 = x + pw - 34
            dd.rounded_rectangle([cx1 - cw - 36, ry + rh // 2 - 24, cx1, ry + rh // 2 + 24], radius=14,
                                 fill=(*_mix("#FFFFFF", POS, 0.14), 255))
            dd.text((cx1 - 18, ry + rh // 2), chip, font=cf, fill=(*_hex(POS), 255), anchor="rm")
            dd.ellipse([x + pw - 34 - cw - 36 - 40, ry + rh // 2 - 6, x + pw - 34 - cw - 36 - 28, ry + rh // 2 + 6],
                       fill=(*_hex(POS), 255))
    return {"h": ph, "draw": draw, "gap": 20}


def el_news_mock(d, accent):
    pw, ph = W - 2 * MARGIN, 300

    def draw(dd, img, y):
        x = MARGIN
        dd.rounded_rectangle([x, y, x + pw, y + ph], radius=28, fill=(*_hex(PANEL), 255),
                             outline=(*_hex(GRID), 255), width=2)
        hl = "“Fed signals rate cut”"
        hf = _f(30, "bold")
        dd.rounded_rectangle([x + 34, y + 40, x + 34 + dd.textlength(hl, font=hf) + 44, y + 40 + 60],
                             radius=16, fill=(*_mix("#FFFFFF", accent, 0.12), 255))
        dd.text((x + 34 + 22, y + 70), hl, font=hf, fill=(*_hex(INK), 255), anchor="lm")
        dd.text((W // 2, y + 150), "▼  scored + linked", font=_f(24, "mono"), fill=(*_hex(MUT2), 255), anchor="mm")
        chips = [("XLF", "+8"), ("KRE", "+7"), ("GS", "+6")]
        cf, cw = _f(28, "bold"), (pw - 68) // 3
        for i, (t, s) in enumerate(chips):
            cx = x + 34 + i * cw
            dd.rounded_rectangle([cx, y + 200, cx + cw - 20, y + 260], radius=16,
                                 fill=(*_mix("#FFFFFF", POS, 0.12), 255), outline=(*_hex(GRID), 255), width=2)
            dd.text((cx + 22, y + 230), t, font=cf, fill=(*_hex(INK), 255), anchor="lm")
            dd.text((cx + cw - 42, y + 230), s, font=_f(24, "mono"), fill=(*_hex(POS), 255), anchor="rm")
    return {"h": ph, "draw": draw, "gap": 20}


def el_proof(d, ticker, ret, spy, accent):
    pw, ph = W - 2 * MARGIN, 330

    def draw(dd, img, y):
        x = MARGIN
        dd.rounded_rectangle([x, y, x + pw, y + ph], radius=28, fill=(*_hex(PANEL), 255),
                             outline=(*_hex(GRID), 255), width=2)
        dd.text((x + 36, y + 46), f"${ticker}", font=_f(56, "bold"), fill=(*_hex(accent), 255), anchor="lm")
        dd.text((x + pw - 36, y + 52), f"+{ret:.0f}%", font=_f(76, "mono"), fill=(*_hex(POS), 255), anchor="rm")
        # two bars: ticker vs S&P
        bx, bw = x + 36, pw - 72
        mx = max(ret, spy, 1)
        for i, (lab, v, col) in enumerate([(ticker, ret, accent), ("S&P 500", spy, MUT)]):
            by = y + 150 + i * 78
            dd.text((bx, by), lab, font=_f(26, "mono"), fill=(*_hex(MUT), 255), anchor="lm")
            tr = bx + bw
            dd.rounded_rectangle([bx, by + 20, tr, by + 52], radius=16, fill=(*_hex("#EBE2D4"), 255))
            fillw = bx + max(0.05, v / mx) * bw
            dd.rounded_rectangle([bx, by + 20, fillw, by + 52], radius=16, fill=(*_hex(col), 255))
            dd.text((tr, by), f"+{v:.0f}%", font=_f(26, "mono"), fill=(*_hex(col), 255), anchor="rm")
    return {"h": ph, "draw": draw, "gap": 30}


def el_url_pill(d, url, accent):
    f = _f(38, "bold")
    tw = d.textlength(url, font=f)

    def draw(dd, img, y):
        x = (W - (tw + 88)) // 2
        dd.rounded_rectangle([x, y, x + tw + 88, y + 84], radius=42, fill=(*_hex(accent), 255))
        dd.text((W // 2, y + 42), url, font=f, fill=(*_hex("#1A1205"), 255), anchor="mm")
    return {"h": 84, "draw": draw, "gap": 30}


def el_note(d, text, accent):
    f = _f(30, "mono")

    def draw(dd, img, y):
        dd.text((W // 2, y + 20), text, font=f, fill=(*_hex(accent), 255), anchor="mm")
    return {"h": 40, "draw": draw, "gap": 24}


# ---------------------------------------------------------------------------
# Slide composition
# ---------------------------------------------------------------------------
def build_elements(d, slide, accent):
    role = slide["role"]
    E = []
    if slide.get("kicker"):
        E.append(el_kicker(d, slide["kicker"], accent))
    if role == "cover":
        E.append(el_headline(d, slide["headline"], 78, INK))
        if slide.get("sub"):
            E.append(el_body(d, slide["sub"], 40, MUT))
    elif role == "problem":
        E.append(el_headline(d, slide["headline"], 62, INK))
        if slide.get("body"):
            E.append(el_body(d, slide["body"], 38, MUT))
    elif role == "feature":
        E.append(el_headline(d, slide["headline"], 58, accent))
        if slide.get("body"):
            E.append(el_body(d, slide["body"], 36, MUT))
        if slide.get("mock") == "screener":
            E.append(el_screener_mock(d, accent))
        elif slide.get("mock") == "news":
            E.append(el_news_mock(d, accent))
    elif role == "proof":
        E.append(el_headline(d, slide.get("headline", "It works."), 56, INK))
        E.append(el_proof(d, slide["ticker"], float(slide["ret"]), float(slide["spy"]), accent))
        if slide.get("sub"):
            E.append(el_body(d, slide["sub"], 34, MUT))
    elif role == "cta":
        E.append(el_headline(d, slide["headline"], 68, INK))
        E.append(el_url_pill(d, slide.get("url", "newsimpactscreener.com"), accent))
        if slide.get("note"):
            E.append(el_note(d, slide["note"], POS))
    return E


def render_slide(slide, ratio, accent, idx, total, brand):
    global W, H
    W, H = SIZES[ratio]
    img = Image.new("RGB", (W, H), _hex(BG))
    d = ImageDraw.Draw(img)
    # TikTok keeps a wider bottom safe band (UI overlays); Meta is tighter.
    safe_top = int(H * (0.11 if ratio == "9x16" else 0.09))
    safe_bot = int(H * (0.80 if ratio == "9x16" else 0.90))

    E = build_elements(d, slide, accent)
    total_h = sum(e["h"] for e in E) + sum(e["gap"] for e in E[:-1])
    y = safe_top + max(0, (safe_bot - safe_top - total_h) // 2)
    for i, e in enumerate(E):
        e["draw"](d, img, y)
        y += e["h"] + (e["gap"] if i < len(E) - 1 else 0)

    # footer: brand wordmark + swipe dots
    d.text((MARGIN, H - int(H * 0.055)), brand, font=_f(26, "bold"), fill=(*_hex(MUT2), 255), anchor="lm")
    dots_w = total * 26
    dx = W - MARGIN - dots_w
    for j in range(total):
        c = _hex(accent) if j == idx else _hex(GRID)
        d.ellipse([dx + j * 26, H - int(H * 0.055) - 6, dx + j * 26 + 12, H - int(H * 0.055) + 6], fill=(*c, 255))
    if slide["role"] == "cta" and slide.get("disclaimer"):
        d.text((W // 2, H - int(H * 0.025)), slide["disclaimer"], font=_f(20, "reg"),
               fill=(*_hex(MUT2), 255), anchor="mm")
    return img


def main():
    ap = argparse.ArgumentParser(description="Render a Meta/TikTok ad carousel from a Claude spec.")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--ratios", default="4x5,9x16")
    args = ap.parse_args()

    spec = json.loads(pathlib.Path(args.spec).read_text())
    slides = spec["slides"]
    accent = _ACCENT.get(spec.get("accent", "amber"), AMBER)
    brand = spec.get("brand", "newsimpactscreener.com")
    out = pathlib.Path(args.spec).resolve().parent
    n = len(slides)

    for ratio in [r.strip() for r in args.ratios.split(",") if r.strip()]:
        rdir = out / ratio; rdir.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(slides):
            render_slide(s, ratio, accent, i, n, brand).save(rdir / f"slide-{i + 1:02d}.png")
        print(f"[{ratio}] {n} slides → {rdir}")

    ad = spec.get("ad", {})
    copy = [f"# Ad copy — {spec.get('slug', out.name)}  (paste into Meta / TikTok Ads Manager)",
            "", "## PRIMARY TEXT", ad.get("primary_text", ""), "",
            f"## HEADLINE\n{ad.get('headline', '')}", "",
            f"## DESCRIPTION\n{ad.get('description', '')}", "",
            f"## CALL TO ACTION\n{ad.get('cta_label', 'Learn More')}   →   {ad.get('destination', brand)}", ""]
    (out / "ad_copy.txt").write_text("\n".join(copy))
    print(f"ad copy → {out / 'ad_copy.txt'}")


if __name__ == "__main__":
    main()
