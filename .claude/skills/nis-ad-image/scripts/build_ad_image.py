"""Render ONE single-image ad (Meta + TikTok) from a Claude-authored spec.

    python build_ad_image.py --spec output/ads/<slug>/ad.json          # all ratios
    python build_ad_image.py --spec output/ads/<slug>/ad.json --ratios 4x5

Outputs under output/ads/<slug>/:
    4x5/ad.png      (1080×1350 — Meta feed)
    9x16/ad.png     (1080×1920 — TikTok / Reels / Stories)
    1x1/ad.png      (1080×1080 — square)
    ad_copy.txt     (primary text · headline · CTA — paste into Ads Manager)

One image, one message — the eToro pattern: brand mark → bold headline (one accent) →
subhead → green-check benefits → optional proof stat → CTA button, over a branded hero
(generated financial motif, or a real photo via `background_image`). No slides, no swipe.
Every number must be real (from a trend brief / setup.json) — the renderer only lays out.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import matplotlib.font_manager as _fm
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---- themes ---------------------------------------------------------------
AMBER = "#F59E0B"; POS = "#22C55E"; NEG = "#EF4444"
_ACCENT = {"amber": AMBER, "pos": POS, "green": POS, "neg": NEG}

# Reusable microcopy — accurate for EVERY screening (all are free email/Telegram subs).
# The withheld-tail tease must never read paywalled; override per-ad via impact_list.more_label.
IMPACT_MORE_CTA = "see them free →"
THEMES = {
    # dark: eToro-style punch (default for ads)
    "dark": {"bg_top": "#0A0F1C", "bg_bot": "#141E33", "ink": "#F4F7FB",
             "mut": "#9BA9C0", "mut2": "#6B7791", "panel": "#131C30",
             "grid": "#22304C", "scrim": (6, 10, 20)},
    # light: matches the site / reels
    "light": {"bg_top": "#FDFBF7", "bg_bot": "#F4ECE0", "ink": "#10182B",
              "mut": "#566377", "mut2": "#8A93A4", "panel": "#FFFFFF",
              "grid": "#E4DBCE", "scrim": (251, 247, 241)},
}

_BOLD = _fm.findfont(_fm.FontProperties(weight="bold"))
_REG = _fm.findfont(_fm.FontProperties(weight="normal"))
_MONO = _fm.findfont(_fm.FontProperties(family="monospace"))

SIZES = {"4x5": (1080, 1350), "9x16": (1080, 1920), "1x1": (1080, 1080)}
MARGIN = 96


def _f(sz, kind="bold"):
    return ImageFont.truetype({"bold": _BOLD, "reg": _REG, "mono": _MONO}[kind], int(sz))


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(base, top, f):
    a, b = _hex(base) if isinstance(base, str) else base, _hex(top) if isinstance(top, str) else top
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


_TZ_ABBR = {"America/New_York": "ET", "America/Chicago": "CT", "America/Denver": "MT",
            "America/Los_Angeles": "PT", "Europe/London": "GMT",
            "Europe/Copenhagen": "CET", "UTC": "UTC"}


def cadence_from_schedule(cron: str, tz: str = "") -> dict:
    """Turn a screening's cron schedule + timezone into reusable microcopy, so the
    eyebrow cadence + CTA trust-line are driven by REAL platform data, not hand-copy:
        cadence_from_schedule("0 7 * * 1-5", "America/New_York")
        → {"cadence": "Updated weekdays", "cta_note": "Free · weekdays 7am ET"}
    Author pulls (category, schedule, timezone) off the market_screenings row and
    passes the resolved strings into ad.json."""
    out = {"cadence": "", "cta_note": ""}
    try:
        mn, hr, _dom, _mon, dow = str(cron).split()
    except ValueError:
        return out
    tzab = _TZ_ABBR.get(tz, (tz.split("/")[-1][:3].upper() if tz else ""))
    if dow in ("1-5",):
        freq = "weekdays"
    elif dow in ("0,6", "6,0", "6", "0"):
        freq = "weekends" if "," in dow else "weekly"
    elif dow in ("*", "?"):
        freq = "daily"
    elif dow.isdigit():
        freq = "weekly"
    else:
        freq = "daily"
    tstr = ""
    if hr.isdigit():
        h = int(hr); ap = "am" if h < 12 else "pm"; h12 = h % 12 or 12
        mns = f":{int(mn):02d}" if (mn.isdigit() and int(mn)) else ""
        tstr = f"{h12}{mns}{ap}"
    out["cadence"] = f"Updated {freq}"
    out["cta_note"] = "Free · " + freq + (f" {tstr}" if tstr else "") + (f" {tzab}" if tstr and tzab else "")
    return out


def _kicker_text(spec):
    """The eyebrow: explicit `kicker` wins; else compose from the screening's
    category tag + cadence (e.g. 'Thematic · Updated weekdays')."""
    if spec.get("kicker"):
        return spec["kicker"]
    parts = [p for p in (spec.get("category"), spec.get("cadence")) if p]
    return " · ".join(parts) if parts else None


# ---- background: real photo (cover + scrim) or generated financial motif ---
def _background(W, H, T, ratio, bg_image: pathlib.Path | None, accent):
    img = Image.new("RGB", (W, H), _hex(T["bg_top"]))
    d = ImageDraw.Draw(img)
    # vertical gradient
    top, bot = _hex(T["bg_top"]), _hex(T["bg_bot"])
    for y in range(H):
        f = y / H
        d.line([(0, y), (W, y)], fill=tuple(round(top[i] * (1 - f) + bot[i] * f) for i in range(3)))

    if bg_image and bg_image.exists():
        photo = Image.open(bg_image).convert("RGB")
        # cover-fit
        s = max(W / photo.width, H / photo.height)
        photo = photo.resize((int(photo.width * s) + 1, int(photo.height * s) + 1))
        photo = photo.crop((0, 0, W, H))
        img.paste(photo, (0, 0))
        # readability scrim: darker/lighter toward the content side (top-left/bottom)
        scrim = Image.new("L", (W, H), 0)
        sd = ImageDraw.Draw(scrim)
        for y in range(H):
            sd.line([(0, y), (W, y)], fill=int(210 * (0.35 + 0.65 * (y / H))))
        tint = Image.new("RGB", (W, H), T["scrim"])
        img = Image.composite(tint, img, scrim)
        return img

    # generated motif: faint grid + a rising line chart with a soft accent glow
    d = ImageDraw.Draw(img, "RGBA")
    grid = (*_hex(T["grid"]), 70)
    step = 96
    for x in range(0, W, step):
        d.line([(x, 0), (x, H)], fill=grid, width=1)
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=grid, width=1)
    # rising jagged line low in the frame — decorative, never over the copy block
    import math
    base_y = int(H * (0.86 if ratio != "9x16" else 0.80))
    amp = int(H * 0.06)
    pts = []
    n = 26
    for i in range(n + 1):
        x = int(W * i / n)
        drift = (i / n) * amp * 1.6                       # overall rise
        wobble = math.sin(i * 0.9) * amp * 0.35 + math.sin(i * 2.3) * amp * 0.15
        pts.append((x, int(base_y - drift + wobble)))
    ac = _hex(accent)
    # glow underlay
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(pts, fill=(*ac, 90), width=14, joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(20))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    d.line(pts, fill=(*ac, 160), width=4, joint="curve")
    return img


# ---- content elements (left-aligned stack) --------------------------------
def _logo(d, x, y, T, accent, brand, mark_text="NIS"):
    s = 60
    d.rounded_rectangle([x, y, x + s, y + s], radius=16, fill=(*_hex(accent), 255))
    d.text((x + s // 2, y + s // 2 + 2), mark_text, font=_f(26, "bold"),
           fill=(*_hex("#0A0F1C"), 255), anchor="mm")
    d.text((x + s + 22, y + s // 2), brand, font=_f(30, "bold"), fill=(*_hex(T["ink"]), 255), anchor="lm")
    return s


def _headline_accent(d, x, y, lines, font, base, accent, accent_words, lh):
    aset = {w.strip(".,!?'\"").lower() for w in accent_words.split()} if accent_words else set()
    for i, ln in enumerate(lines):
        cx, ly = x, y + i * lh
        for word in ln.split():
            col = accent if word.strip(".,!?'\"").lower() in aset else base
            d.text((cx, ly), word, font=font, fill=(*_hex(col), 255), anchor="lm")
            cx += d.textlength(word + " ", font=font)


def _check(d, x, y, T, accent, text, size=34):
    r = 16
    cy = y
    d.ellipse([x, cy - r, x + 2 * r, cy + r], fill=(*_hex(POS), 255))
    d.line([(x + 9, cy), (x + 15, cy + 7), (x + 24, cy - 8)], fill=(*_hex("#04140A"), 255), width=4, joint="curve")
    d.text((x + 2 * r + 20, cy), text, font=_f(size, "reg"), fill=(*_hex(T["ink"]), 255), anchor="lm")


def _proof(d, x, y, W, T, accent, ticker, ret, spy):
    pw = W - 2 * MARGIN
    ph = 200
    d.rounded_rectangle([x, y, x + pw, y + ph], radius=24,
                        fill=(*_mix(T["panel"], "#FFFFFF", 0.02 if T is THEMES["dark"] else 0), 235),
                        outline=(*_hex(T["grid"]), 255), width=2)
    d.text((x + 30, y + 40), f"${ticker}", font=_f(44, "bold"), fill=(*_hex(accent), 255), anchor="lm")
    d.text((x + pw - 30, y + 44), f"+{ret:.0f}%", font=_f(60, "mono"), fill=(*_hex(POS), 255), anchor="rm")
    bx, bw = x + 30, pw - 60
    mx = max(ret, spy, 1)
    for i, (lab, v, col) in enumerate([(ticker, ret, accent), ("S&P 500", spy, T["mut"])]):
        by = y + 96 + i * 52
        d.text((bx, by), lab, font=_f(22, "mono"), fill=(*_hex(T["mut"]), 255), anchor="lm")
        track_l = bx + 150
        d.rounded_rectangle([track_l, by - 12, bx + bw, by + 12], radius=12, fill=(*_hex(T["grid"]), 255))
        fillw = track_l + max(0.05, v / mx) * (bx + bw - track_l)
        d.rounded_rectangle([track_l, by - 12, fillw, by + 12], radius=12, fill=(*_hex(col), 255))
    return ph


def _impact_rows(il):
    """Resolve an impact_list spec into (items, shown, hidden). `reveal:"partial"`
    shows `shown` rows and hides the rest behind a tease (the curiosity gap);
    `reveal:"full"` shows everything (the proof play)."""
    items = il.get("items", []) or []
    reveal = (il.get("reveal") or "full").lower()
    shown = il.get("shown", 3) if reveal == "partial" else len(items)
    shown = max(0, min(int(shown), len(items)))
    hidden = (len(items) - shown) if reveal == "partial" else 0
    return items, shown, hidden


def _impact_height(il):
    items, shown, hidden = _impact_rows(il)
    rows = shown + (1 if hidden > 0 else 0)
    head = 54 if il.get("title") else 0
    return 28 + head + rows * 58 + 20


def _impact_list(d, x, y, W, T, accent, il):
    """A compact 'impact board': ranked $TICKER → move rows. When partial, a final
    '+N more · unlock →' row opens the curiosity gap (the rest lives behind the click
    + email). Every number must be real — the renderer only lays out."""
    items, shown, hidden = _impact_rows(il)
    pw = W - 2 * MARGIN
    ph = _impact_height(il)
    d.rounded_rectangle([x, y, x + pw, y + ph], radius=24,
                        fill=(*_mix(T["panel"], "#FFFFFF", 0.02 if T is THEMES["dark"] else 0), 235),
                        outline=(*_hex(T["grid"]), 255), width=2)
    yy = y + 28
    if il.get("title"):
        d.text((x + 30, yy + 8), il["title"].upper(), font=_f(22, "mono"),
               fill=(*_hex(T["mut"]), 255), anchor="lm")
        yy += 54
    tick_f, move_f = _f(40, "bold"), _f(40, "mono")
    for it in items[:shown]:
        col = NEG if str(it.get("dir", "up")).lower() == "down" else POS
        d.text((x + 30, yy + 29), f"${it.get('ticker', '')}", font=tick_f,
               fill=(*_hex(T["ink"]), 255), anchor="lm")
        d.text((x + pw - 30, yy + 29), str(it.get("move", "")), font=move_f,
               fill=(*_hex(col), 255), anchor="rm")
        yy += 58
    if hidden > 0:
        d.text((x + 30, yy + 29), f"+ {hidden} more", font=_f(36, "bold"),
               fill=(*_hex(accent), 255), anchor="lm")
        d.text((x + pw - 30, yy + 29), il.get("more_label") or IMPACT_MORE_CTA,
               font=_f(30, "mono"), fill=(*_hex(accent), 255), anchor="rm")
    return ph


def _cta(d, x, y, T, accent, label):
    f = _f(38, "bold")
    tw = d.textlength(label, font=f)
    w, h = tw + 88, 92
    d.rounded_rectangle([x, y, x + w, y + h], radius=20, fill=(*_hex(accent), 255))
    d.text((x + w // 2, y + h // 2), label, font=f, fill=(*_hex("#0A0F1C"), 255), anchor="mm")
    return h


# ---- compose one image ----------------------------------------------------
def render(spec, ratio, out_dir):
    W, H = SIZES[ratio]
    T = THEMES.get(spec.get("theme", "dark"), THEMES["dark"])
    accent = _ACCENT.get(spec.get("accent", "amber"), AMBER)
    brand = spec.get("brand", "newsimpactscreener.com")
    bg_image = None
    if spec.get("background_image"):
        bg_image = (out_dir / spec["background_image"]).resolve()

    img = _background(W, H, T, ratio, bg_image, accent)
    d = ImageDraw.Draw(img, "RGBA")

    x = MARGIN
    safe_top = int(H * (0.10 if ratio == "9x16" else 0.075))
    safe_bot = int(H * (0.82 if ratio == "9x16" else 0.90))
    maxw = W - 2 * MARGIN

    # measure the stack so we can vertically center it in the safe band
    hl_size = 82 if ratio != "1x1" else 74
    hl_font = _f(hl_size, "bold")
    hl_lines = _wrap(d, spec["headline"], hl_font, maxw)
    hl_lh = int(hl_size * 1.14)
    sub_lines = _wrap(d, spec.get("subhead", ""), _f(38, "reg"), maxw) if spec.get("subhead") else []
    sub_lh = int(38 * 1.34)
    bullets = spec.get("bullets", [])
    proof = spec.get("proof")
    impact = spec.get("impact_list")

    blocks = []  # (height, drawfn)
    blocks.append((60, lambda yy: _logo(d, x, yy, T, accent, brand, spec.get("mark", "NIS"))))
    kicker = _kicker_text(spec)
    if kicker:
        kf = _f(26, "mono")
        blocks.append((40, lambda yy, kf=kf, kt=kicker: d.text((x, yy + 20), kt.upper(), font=kf,
                                                               fill=(*_hex(accent), 255), anchor="lm")))
    blocks.append((hl_lh * len(hl_lines),
                   lambda yy: _headline_accent(d, x, yy + hl_lh // 2, hl_lines, hl_font, T["ink"],
                                               accent, spec.get("headline_accent", ""), hl_lh)))
    if sub_lines:
        blocks.append((sub_lh * len(sub_lines),
                       lambda yy: [d.text((x, yy + i * sub_lh + sub_lh // 2), ln, font=_f(38, "reg"),
                                          fill=(*_hex(T["mut"]), 255), anchor="lm")
                                   for i, ln in enumerate(sub_lines)]))
    if impact and impact.get("items"):
        blocks.append((_impact_height(impact),
                       lambda yy: _impact_list(d, x, yy, W, T, accent, impact)))
    for b in bullets:
        blocks.append((54, lambda yy, b=b: _check(d, x, yy + 22, T, accent, b)))
    if proof:
        blocks.append((200, lambda yy: _proof(d, x, yy, W, T, accent, proof["ticker"],
                                              float(proof["ret"]), float(proof["spy"]))))
    cta_note = spec.get("cta_note")

    def _cta_block(yy):
        _cta(d, x, yy, T, accent, spec.get("cta_label", "Learn more"))
        if cta_note:                              # trust/cadence line under the button
            d.text((x, yy + 92 + 20), cta_note, font=_f(24, "reg"),
                   fill=(*_hex(T["mut"]), 255), anchor="lm")
    blocks.append((92 + (34 if cta_note else 0), _cta_block))

    gaps = {0: 46, 1: 30}  # after logo / kicker; default below
    total = sum(h for h, _ in blocks) + sum(28 for _ in blocks[:-1]) + 40
    y = safe_top + max(0, (safe_bot - safe_top - total) // 2)
    for i, (h, fn) in enumerate(blocks):
        fn(y)
        y += h + 40  # comfortable rhythm

    # footer: brand + disclaimer
    d.text((x, H - int(H * 0.05)), brand, font=_f(24, "bold"), fill=(*_hex(T["mut2"]), 255), anchor="lm")
    if spec.get("disclaimer"):
        d.text((W // 2, H - int(H * 0.022)), spec["disclaimer"], font=_f(19, "reg"),
               fill=(*_hex(T["mut2"]), 255), anchor="mm")

    return img.convert("RGB")


def _derive_design(spec: dict, out_dir: pathlib.Path, ratios: list[str]) -> dict:
    """Factual design attributes of the rendered ad — auto-derived so the record is
    objective and consistent across every ad (Claude can't forget or fudge them).
    Merged with the authored `design` block into design.json for later engagement
    analysis (join on ad_id via the launch manifest, or on utm_content)."""
    ad = spec.get("ad", {}) or {}
    dest = ad.get("destination") or spec.get("destination", "")
    utm = {k: v[0] for k, v in parse_qs(urlparse(dest).query).items()}
    hl = spec.get("headline", "") or ""
    sub = spec.get("subhead", "") or ""
    bullets = spec.get("bullets", []) or []
    il = spec.get("impact_list") or {}
    il_items = il.get("items") or []
    il_reveal = (il.get("reveal") or "full").lower() if il_items else "none"
    il_shown = (min(int(il.get("shown", 3)), len(il_items))
                if il_reveal == "partial" else len(il_items)) if il_items else 0
    # provenance from the saved-content convention: …/<campaign>/<lead-magnet>/
    lead_magnet = out_dir.name
    campaign = out_dir.parent.name

    derived = {
        # factual creative attributes (the levers to test)
        "theme": spec.get("theme", "dark"),
        "accent": spec.get("accent", "amber"),
        "background_type": "photo" if spec.get("background_image") else "motif",
        "has_kicker": bool(spec.get("kicker")),
        "headline_words": len(hl.split()),
        "headline_chars": len(hl),
        "has_headline_accent": bool(spec.get("headline_accent")),
        "has_subhead": bool(sub),
        "subhead_words": len(sub.split()),
        "bullet_count": len(bullets),
        "has_proof": bool(spec.get("proof")),
        "proof_type": "ticker_vs_spy" if spec.get("proof") else "none",
        # curiosity-gap levers: the impact board + how much it reveals
        "has_impact_list": bool(il_items),
        "impact_list_reveal": il_reveal,          # full | partial | none
        "impact_list_shown": il_shown,
        "impact_list_total": len(il_items),
        "cta_label": spec.get("cta_label"),
        "cta_words": len((spec.get("cta_label") or "").split()),
        "has_cta_note": bool(spec.get("cta_note")),
        "category": spec.get("category"),
        "cadence": spec.get("cadence"),
        "primary_text_chars": len(ad.get("primary_text") or ""),
        "formats": ratios,
        # provenance / join keys
        "slug": spec.get("slug"),
        "lead_magnet": lead_magnet,
        "campaign": campaign,
        "brand": spec.get("brand"),
        "destination": dest,
        "utm_content": utm.get("utm_content"),
        "utm_campaign": utm.get("utm_campaign"),
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # authored intent (controlled vocab) wins for its own keys; derived facts win on overlap
    merged = {**(spec.get("design") or {}), **derived}
    # curiosity genome — authored value wins; otherwise infer from the impact board so
    # every ad carries a comparable value (a partial list IS a curiosity mechanism).
    merged.setdefault("curiosity_type",
                      "partial_list" if il_reveal == "partial" else "none")
    merged.setdefault("curiosity_strength",
                      2 if il_reveal == "partial" else (1 if il_items else 0))
    return merged


def main():
    ap = argparse.ArgumentParser(description="Render a single-image Meta/TikTok ad from a Claude spec.")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--ratios", default="4x5,9x16,1x1")
    args = ap.parse_args()

    spec = json.loads(pathlib.Path(args.spec).read_text())
    out = pathlib.Path(args.spec).resolve().parent

    ratios = [r.strip() for r in args.ratios.split(",") if r.strip()]
    for ratio in ratios:
        rdir = out / ratio
        rdir.mkdir(parents=True, exist_ok=True)
        render(spec, ratio, out).save(rdir / "ad.png")
        print(f"[{ratio}] → {rdir / 'ad.png'}")

    # resolved design metadata (authored + auto-derived) for engagement analysis
    design = _derive_design(spec, out, ratios)
    (out / "design.json").write_text(json.dumps(design, indent=2))
    print(f"design → {out / 'design.json'}")

    ad = spec.get("ad", {})
    copy = [f"# Ad copy — {spec.get('slug', out.name)}  (paste into Meta / TikTok Ads Manager)",
            "", "## PRIMARY TEXT", ad.get("primary_text", ""), "",
            f"## HEADLINE\n{ad.get('headline', spec.get('headline', ''))}", "",
            f"## DESCRIPTION\n{ad.get('description', spec.get('subhead', ''))}", "",
            f"## CALL TO ACTION\n{ad.get('cta_label', spec.get('cta_label', 'Learn More'))}"
            f"   →   {ad.get('destination', spec.get('destination', 'newsimpactscreener.com'))}", ""]
    (out / "ad_copy.txt").write_text("\n".join(copy))
    print(f"ad copy → {out / 'ad_copy.txt'}")


if __name__ == "__main__":
    main()
