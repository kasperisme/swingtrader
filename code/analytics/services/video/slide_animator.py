"""
slide_animator.py — Render per-slide animated MP4 clips using matplotlib + ffmpeg.

Each slide is a short MP4 with element-level animations (fade-in, slide-in, grow).
The ticker bar scrolls continuously based on absolute time.
Clips are concatenated in video_assembler.py for the final cut.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle, FancyBboxPatch, Circle, Polygon

from .config import (
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
    BG_COLOR,
    TEXT_COLOR,
    TEXT_COLOR_DIM,
    BRAND_COLOR,
    BRAND_COLOR_DIM,
    ACCENT_GREEN,
    ACCENT_RED,
    ACCENT_YELLOW,
    SAFE_ZONE_RIGHT,
    SAFE_ZONE_BOTTOM,
    OUTPUT_DIR,
)

log = logging.getLogger(__name__)

_DPI = 100
_S = 72.0 / _DPI
_FONT_SANS = "DejaVu Sans"
_FONT_MONO = "DejaVu Sans Mono"
_SAFE_R = SAFE_ZONE_RIGHT

_TICKER_Y0 = 0.834
_TICKER_Y1 = 0.868
_TICKER_Y = 0.851
_TICKER_BADGE_W = 0.13
_TICKER_X0 = 0.14
_HDR_Y = 0.815
_RULE_Y = 0.793


def _sc(score: float) -> str:
    if score > 0.05:
        return ACCENT_GREEN
    if score < -0.05:
        return ACCENT_RED
    return ACCENT_YELLOW


def _sl(score: float) -> str:
    a = abs(score)
    if a >= 0.6:
        t = "STRONG"
    elif a >= 0.3:
        t = "MODERATE"
    elif a >= 0.1:
        t = "MILD"
    else:
        return "NEUTRAL"
    return f"{t} {'▲' if score > 0 else '▼'}"


def _ml(rank: int) -> tuple[str, str]:
    if rank == 0:
        return "TOP", "STORY"
    if rank == 1:
        return "HIGH", "IMPACT"
    if rank == 2:
        return "MED", "IMPACT"
    return "LOW", "IMPACT"


def _eo(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _lr(a: float, b: float, t: float) -> float:
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


# ─── drawing primitives ───


def _t(ax, x, y, s, sz=22, c=TEXT_COLOR, f=_FONT_SANS, b=False,
       ha="left", va="center", a=1.0, z=5):
    ax.text(x, y, s, fontsize=sz * _S, color=c, fontfamily=f,
            fontweight="bold" if b else "normal", ha=ha, va=va,
            alpha=a, clip_on=True, zorder=z)


def _r(ax, x, y, w, h, c=BRAND_COLOR, a=1.0, z=1):
    ax.add_patch(Rectangle((x, y), w, h, facecolor=c, edgecolor="none",
                            alpha=a, zorder=z))


def _hl(ax, y, x0=0.05, x1=None, c=BRAND_COLOR_DIM, lw=1, a=1.0, z=1):
    x1 = x1 if x1 is not None else _SAFE_R
    ax.plot([x0, x1], [y, y], color=c, linewidth=lw,
            solid_capstyle="butt", alpha=a, zorder=z)


def _vl(ax, x, y0, y1, c=BRAND_COLOR_DIM, lw=1, a=1.0, z=1):
    ax.plot([x, x], [y0, y1], color=c, linewidth=lw,
            solid_capstyle="butt", alpha=a, zorder=z)


def _stripe(ax, c=BRAND_COLOR, w=0.014, a=1.0):
    _r(ax, 0, 0, w, 1, c=c, a=a, z=0)


def _ticker(ax, ranking, time_sec):
    if not ranking:
        return
    _r(ax, 0, _TICKER_Y0, _SAFE_R, _TICKER_Y1 - _TICKER_Y0,
       c=BRAND_COLOR_DIM, a=0.55, z=2)
    _hl(ax, _TICKER_Y0, x0=0, x1=_SAFE_R, c=BRAND_COLOR, lw=2, z=3)
    _r(ax, 0, _TICKER_Y0, _TICKER_BADGE_W, _TICKER_Y1 - _TICKER_Y0,
       c=BRAND_COLOR, a=0.12, z=2)
    _t(ax, _TICKER_BADGE_W / 2, _TICKER_Y, "PRE-MARKET",
       sz=17, c=BRAND_COLOR, b=True, ha="center", z=3)

    items = []
    for cl in ranking[:8]:
        label = cl.get("label", cl.get("cluster", "")).upper()
        score = cl.get("score", 0) or 0
        arrow = "▲" if score > 0.05 else ("▼" if score < -0.05 else "●")
        items.append(f"{arrow} {label}")
    full = ("  ·  ".join(items) + "  ·  ") * 4
    offset = -(time_sec * 0.15)
    _t(ax, _TICKER_X0 + offset, _TICKER_Y, full,
       sz=17, c=TEXT_COLOR_DIM, f=_FONT_MONO, b=True)


def _hdr(ax, label, right=None, a=1.0):
    _t(ax, 0.05, _HDR_Y, label, sz=26, c=BRAND_COLOR, b=True, a=a)
    if right:
        _t(ax, _SAFE_R - 0.01, _HDR_Y, right, sz=24,
           c=TEXT_COLOR_DIM, ha="right", a=a)
    _hl(ax, _RULE_Y, c=BRAND_COLOR, lw=2, a=a)


def _speech_bubble(ax, x, y, w, h, text, a=1.0):
    bubble = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.008",
        facecolor="white", edgecolor=TEXT_COLOR, linewidth=2,
        alpha=a, zorder=8,
    )
    ax.add_patch(bubble)

    tail_bx = x + w * 0.55
    tail_pts = [
        (tail_bx - 0.015, y),
        (tail_bx + 0.020, y),
        (tail_bx + 0.035, y - 0.028),
    ]
    tail = Polygon(tail_pts, closed=True, facecolor="white",
                   edgecolor=TEXT_COLOR, linewidth=2, alpha=a, zorder=8)
    ax.add_patch(tail)

    cover = Rectangle(
        (tail_bx - 0.015, y - 0.003), 0.035, 0.006,
        facecolor="white", edgecolor="none", alpha=a, zorder=9,
    )
    ax.add_patch(cover)

    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = f"{cur} {word}" if cur else word
        if len(test) > 36 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = test
    if cur:
        lines.append(cur)
    display = lines[:2]
    if len(lines) > 2:
        display[-1] += " …"

    ax.text(x + w / 2, y + h / 2, "\n".join(display),
            fontsize=36 * _S, color=TEXT_COLOR, fontfamily=_FONT_SANS,
            fontweight="bold", ha="center", va="center",
            alpha=a, clip_on=True, zorder=10,
            linespacing=1.3)


def _sentiment_gauge(ax, score, x_center, y, w=0.80, a=1.0):
    h = 0.013
    x0 = x_center - w / 2
    x1 = x_center + w / 2

    _r(ax, x0, y, w, h, c=BRAND_COLOR_DIM, a=0.3 * a, z=6)
    _r(ax, x0, y, w / 2, h, c=ACCENT_RED, a=0.2 * a, z=6)
    _r(ax, x0 + w / 2, y, w / 2, h, c=ACCENT_GREEN, a=0.2 * a, z=6)

    ns = max(0.0, min(1.0, (score + 1) / 2))
    dot_x = x0 + ns * w
    dot_y = y + h / 2

    dot = Circle((dot_x, dot_y), 0.016, facecolor="white",
                 edgecolor=TEXT_COLOR, linewidth=2.5, alpha=a, zorder=8)
    ax.add_patch(dot)

    _t(ax, dot_x, y + h + 0.028, f"{score:+.2f}",
       sz=36, c=TEXT_COLOR, b=True, ha="center", a=a, z=8)

    _t(ax, x0 - 0.01, y + h / 2, "BEARISH",
       sz=22, c=ACCENT_RED, ha="right", a=a * 0.7, z=6)
    _t(ax, x1 + 0.01, y + h / 2, "BULLISH",
       sz=22, c=ACCENT_GREEN, ha="left", a=a * 0.7, z=6)



# ─── per-slide frame functions ───


def _f_title(ax, fi, total, d):
    fps, ts, t = d["fps"], d["time_offset"] + fi / d["fps"], fi / max(total, 1)

    _stripe(ax)

    ha = _eo(t / 0.10)
    _t(ax, 0.05, 0.93, "PRE-MARKET BRIEF", sz=26, c=BRAND_COLOR, b=True, a=ha)
    _t(ax, _SAFE_R - 0.01, 0.93, d["date_str"].upper(), sz=24,
       c=TEXT_COLOR_DIM, ha="right", a=ha)
    _hl(ax, 0.91, c=BRAND_COLOR, lw=2, a=ha)

    top = d.get("top")
    hook_text = d.get("hook_text", "")

    if top:
        score = top.get("score", 0) or 0
        label = top.get("label", "").upper()
        color = _sc(score)

        if score < -0.3:
            verdict = f"{label} IS TURNING BEARISH"
        elif score < -0.05:
            verdict = f"{label} SHOWING WEAKNESS"
        elif score > 0.3:
            verdict = f"{label} IS TURNING BULLISH"
        elif score > 0.05:
            verdict = f"{label} SHOWING STRENGTH"
        else:
            verdict = f"{label} HOLDING NEUTRAL"

        p1 = _eo((t - 0.12) / 0.10)
        _t(ax, _lr(-0.10, 0.05, p1), 0.82, verdict,
           sz=52, c=color, b=True, a=p1)

        cr = d.get("cr", [])
        scores = [c.get("score", 0) or 0 for c in cr[:6]]
        avg_score = sum(scores) / len(scores) if scores else 0

        p2 = _eo((t - 0.25) / 0.12)
        _sentiment_gauge(ax, avg_score, 0.50, 0.66, a=p2)

        p3 = _eo((t - 0.20) / 0.15)
        _r(ax, 0.014, 0.10, 0.014, 0.78, c=color, a=0.08 * p3)
        _vl(ax, 0.014, 0.10, 0.89, c=color, lw=3, a=p3)

        if hook_text:
            p4 = _eo((t - 0.38) / 0.12)
            _speech_bubble(ax, 0.25, 0.535, 0.42, 0.10, hook_text, a=p4)
    else:
        p = _eo((t - 0.15) / 0.25)
        _t(ax, _lr(-0.10, 0.05, p), 0.700, "PRE-MARKET",
           sz=86, c=TEXT_COLOR, b=True, a=p)
        _t(ax, _lr(-0.10, 0.05, p), 0.590, "BRIEF",
           sz=86, c=BRAND_COLOR, b=True, a=p)
        _t(ax, 0.05, 0.482, d["date_str"].upper(),
           sz=32, c=TEXT_COLOR_DIM, a=p)


def _f_regime(ax, fi, total, d):
    fps, ts, t = d["fps"], d["time_offset"] + fi / d["fps"], fi / max(total, 1)
    accent = d["accent"]
    _stripe(ax, c=accent, w=0.025)
    _r(ax, 0.025, 0, _SAFE_R - 0.025, 1, c=accent, a=0.03, z=0)
    _ticker(ax, d["cr"], ts)

    ha = _eo(t / 0.10)
    _hdr(ax, "MARKET REGIME", right="newsimpactscreener.com", a=ha)

    lbl = d["label"].upper().split()
    p1 = _eo((t - 0.10) / 0.20)
    ox = _lr(-0.12, 0.05, p1)
    if len(lbl) >= 2:
        _t(ax, ox, 0.710, lbl[0], sz=90, c=accent, b=True, a=p1)
        _t(ax, ox, 0.600, " ".join(lbl[1:]), sz=90, c=accent, b=True, a=p1)
        ry = 0.542
    else:
        _t(ax, ox, 0.660, " ".join(lbl), sz=90, c=accent, b=True, a=p1)
        ry = 0.578
    _hl(ax, ry, a=p1)

    words = d["text"].split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 42:
            lines.append(cur.strip())
            cur = w
        else:
            cur += " " + w
    if cur.strip():
        lines.append(cur.strip())

    for j, line in enumerate(lines[:3]):
        pj = _eo((t - 0.30 - j * 0.06) / 0.12)
        _t(ax, 0.05, (ry - 0.062) - j * 0.070, line,
           sz=34, c=TEXT_COLOR_DIM, a=pj)



def _f_signal(ax, fi, total, d):
    fps, ts, t = d["fps"], d["time_offset"] + fi / d["fps"], fi / max(total, 1)
    top = d["cr"][:6]
    _ticker(ax, d["cr"], ts)

    ha = _eo(t / 0.08)
    _hdr(ax, "THE SETUP", a=ha)

    rh, sy = 0.090, 0.742
    for i, cl in enumerate(top):
        label = cl.get("label", cl.get("cluster", ""))
        score = cl.get("score", 0) or 0
        count = cl.get("article_count", 0) or 0
        color = _sc(score)
        tier = _sl(score)
        yc = sy - i * rh
        yb = yc - rh * 0.46

        pi = _eo((t - 0.10 - i * 0.04) / 0.10)
        ox = _lr(-0.08, 0.05, pi)

        _hl(ax, yb, x0=0.05, x1=_SAFE_R, a=pi)
        _r(ax, 0, yb, 0.008, rh * 0.92, c=color, a=pi)

        lsz = 30 if i < 3 else 26
        tsz = 24 if i < 3 else 22
        dc = "▲" if score > 0.05 else ("▼" if score < -0.05 else "●")
        _t(ax, ox, yc + 0.016, f"{dc}  {label}",
           sz=lsz, c=TEXT_COLOR, b=True, a=pi)
        _t(ax, ox, yc - 0.026, f"{count} articles",
           sz=22, c=TEXT_COLOR_DIM, a=pi)
        _t(ax, _SAFE_R, yc, tier,
           sz=tsz, c=color, f=_FONT_MONO, b=True, ha="right", a=pi)



def _f_matters(ax, fi, total, d):
    fps, ts, t = d["fps"], d["time_offset"] + fi / d["fps"], fi / max(total, 1)
    dims = d["dims"]
    labels = [dm["label"] for dm in dims]
    scores = [dm["score"] for dm in dims]
    _ticker(ax, d["cr"], ts)

    ha = _eo(t / 0.08)
    _hdr(ax, "WHY IT MOVES", a=ha)

    zx = 0.50
    mbh = 0.34
    _vl(ax, zx, 0.155, 0.748, c=BRAND_COLOR_DIM, lw=1, a=ha)
    pa = _eo((t - 0.10) / 0.10)
    _t(ax, zx - 0.02, 0.165, "BEARISH ◀", sz=20, c=TEXT_COLOR_DIM,
       ha="right", a=pa)
    _t(ax, zx + 0.02, 0.165, "▶ BULLISH", sz=20, c=TEXT_COLOR_DIM,
       ha="left", a=pa)

    rh, sy = 0.145, 0.726
    for i in range(len(dims)):
        yc = sy - i * rh
        sc = scores[i]
        color = _sc(sc)
        bl = min(abs(sc), 1.0) * mbh

        pb = _eo((t - 0.15 - i * 0.05) / 0.15)
        bar_w = bl * pb
        x0b = zx if sc >= 0 else zx - bar_w
        x1b = zx + bar_w if sc >= 0 else zx

        _r(ax, x0b, yc - 0.040, max(x1b - x0b, 0.001), 0.080,
           c=color, a=0.85 * pb)

        _hl(ax, yc - rh * 0.5, x0=0.05, x1=_SAFE_R, a=pb)

        pt = _eo((t - 0.20 - i * 0.05) / 0.10)
        _t(ax, 0.05, yc + 0.014, labels[i], sz=28, c=TEXT_COLOR, b=True, a=pt)

        tier = _sl(sc)
        sx = min(x1b + 0.015, _SAFE_R) if sc >= 0 else max(x0b - 0.015, 0.03)
        anc = "left" if sc >= 0 else "right"
        _t(ax, sx, yc, tier, sz=22, c=color, f=_FONT_MONO, b=True,
           ha=anc, a=pt)



def _f_watch(ax, fi, total, d):
    fps, ts, t = d["fps"], d["time_offset"] + fi / d["fps"], fi / max(total, 1)
    _ticker(ax, d["cr"], ts)

    ha = _eo(t / 0.08)
    _hdr(ax, "WATCH LIST", a=ha)

    top4 = d["articles"]
    tm = d["tickers_map"]
    rh, sy = 0.155, 0.710

    for i, art in enumerate(top4):
        yc = sy - i * rh
        yt = yc + rh * 0.47
        yb = yc - rh * 0.47

        title = art.get("title", "Untitled")
        if len(title) > 48:
            title = title[:45] + "…"
        tickers = tm.get(art["id"], [])
        ticker_str = "  ·  ".join(tickers[:4])
        mag = art.get("magnitude", 0) or 0
        bc = ACCENT_GREEN if mag > 0 else (ACCENT_RED if mag < 0 else ACCENT_YELLOW)
        l1, l2 = _ml(i)

        pi = _eo((t - 0.10 - i * 0.06) / 0.12)
        ox = _lr(-0.10, 0.05, pi)

        _r(ax, ox, yb + 0.006, 0.012, yt - yb - 0.012, c=bc, a=pi)
        _hl(ax, yb, x0=0.05, x1=_SAFE_R, a=pi)

        _t(ax, 0.105, yc + 0.026, l1, sz=26, c=bc, f=_FONT_MONO, b=True,
           ha="center", a=pi)
        _t(ax, 0.105, yc - 0.016, l2, sz=22, c=bc, f=_FONT_MONO, b=True,
           ha="center", a=pi)

        _vl(ax, 0.135, yb + 0.018, yt - 0.018, c=BRAND_COLOR_DIM, a=pi)

        _t(ax, _lr(0.18, 0.148, pi), yc + 0.024, title,
           sz=26, c=TEXT_COLOR, b=True, a=pi)
        if ticker_str:
            _t(ax, 0.148, yc - 0.042, ticker_str,
               sz=22, c=BRAND_COLOR, f=_FONT_MONO, a=pi)



def _f_contrarian(ax, fi, total, d):
    fps, ts, t = d["fps"], d["time_offset"] + fi / d["fps"], fi / max(total, 1)

    pa = _eo(t / 0.15)
    _stripe(ax, c=ACCENT_RED, w=0.025, a=pa)
    _r(ax, 0.025, 0, _SAFE_R - 0.025, 1, c=ACCENT_RED, a=0.03 * pa, z=0)
    _ticker(ax, d["cr"], ts)

    ha = _eo((t - 0.05) / 0.10)
    _hdr(ax, "THESIS RISK", a=ha)
    _hl(ax, _RULE_Y, c=ACCENT_RED, lw=2, a=ha)

    words = d["text"].split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 34:
            lines.append(cur.strip())
            cur = w
        else:
            cur += " " + w
    if cur.strip():
        lines.append(cur.strip())

    nl = min(len(lines), 4)
    lg = 0.095
    fy = 0.608 + (nl - 1) * 0.040

    for j, line in enumerate(lines[:4]):
        pj = _eo((t - 0.15 - j * 0.06) / 0.12)
        sz = 46 if j == 0 else 40
        _t(ax, _lr(-0.08, 0.05, pj), fy - j * lg, line,
           sz=sz, c=TEXT_COLOR, b=True, a=pj)

    pi = _eo((t - 0.55) / 0.10)
    _hl(ax, 0.221, a=pi)
    _t(ax, 0.05, 0.179, "INVALIDATION SCENARIO",
       sz=26, c=ACCENT_RED, a=pi)



def _f_cta(ax, fi, total, d):
    fps, ts, t = d["fps"], d["time_offset"] + fi / d["fps"], fi / max(total, 1)
    _stripe(ax)
    _ticker(ax, d["cr"], ts)

    ha = _eo(t / 0.10)
    _hdr(ax, "DAILY PRE-MARKET ANALYSIS", a=ha)

    p1 = _eo((t - 0.12) / 0.18)
    fs1 = _lr(40, 88, p1)
    _t(ax, 0.05, 0.680, "FOLLOW", sz=fs1, c=TEXT_COLOR, b=True, a=p1)

    p2 = _eo((t - 0.25) / 0.15)
    _t(ax, _lr(-0.12, 0.05, p2), 0.575, "@newsimpactscrnr",
       sz=44, c=BRAND_COLOR, f=_FONT_MONO, b=True, a=p2)

    p3 = _eo((t - 0.38) / 0.12)
    _hl(ax, 0.520, a=p3)
    _t(ax, 0.05, 0.470, "newsimpactscreener.com",
       sz=26, c=TEXT_COLOR_DIM, a=p3)
    _t(ax, 0.05, 0.408, "#StockMarket  ·  #PreMarket  ·  #Trading",
       sz=20, c=BRAND_COLOR_DIM, a=p3)

    p4 = _eo((t - 0.50) / 0.15)
    _r(ax, 0.014, _lr(0.100, 0.155, p4), _SAFE_R - 0.014, 0.090,
       c=BRAND_COLOR_DIM, a=0.4 * p4)
    _hl(ax, 0.245, x0=0.014, x1=_SAFE_R, c=BRAND_COLOR, a=p4)
    _t(ax, 0.05, 0.200, "500 STOCKS · 40 FACTOR DIMENSIONS · EVERY MORNING",
       sz=18, c=BRAND_COLOR, a=p4)


# ─── render pipeline ───


def _encode_clip(
    draw_func,
    data: dict,
    duration: float,
    fps: int,
    output_path: Path,
    fig: plt.Figure,
    ax,
) -> Path:
    total = max(int(duration * fps), 2)
    log.info("Encoding %s: %.1fs / %d frames", output_path.name, duration, total)

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}", "-pix_fmt", "rgb24",
        "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "18",
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    for fi in range(total):
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_facecolor(BG_COLOR)
        ax.axis("off")

        draw_func(ax, fi, total, data)

        fig.canvas.draw()
        buf = np.asarray(fig.canvas.buffer_rgba())
        rgb = buf[:, :, :3].copy()
        proc.stdin.write(rgb.tobytes())

    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read().decode()[:500]
        raise RuntimeError(f"ffmpeg clip encode failed: {err}")

    log.info("Encoded %s (%d KB)", output_path.name,
             output_path.stat().st_size // 1024)
    return output_path


def render_all_animated_slides(
    summary: dict,
    articles: list[dict],
    tickers_map: dict[int, list[str]],
    date_str: str,
    script: dict,
    durations: list[float],
    output_dir: Path | None = None,
) -> list[Path]:
    output_dir = output_dir or OUTPUT_DIR / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)

    cr = summary.get("cluster_ranking", [])
    fps = VIDEO_FPS
    clips: list[Path] = []
    time_offset = 0.0

    fig = plt.figure(
        figsize=(VIDEO_WIDTH / _DPI, VIDEO_HEIGHT / _DPI),
        dpi=_DPI, facecolor=BG_COLOR,
    )
    ax = fig.add_axes([0, 0, 1, 1])

    slide_specs = [
        ("title", _f_title),
        ("regime", _f_regime),
        ("signal", _f_signal),
        ("matters", _f_matters),
        ("watch", _f_watch),
        ("contrarian", _f_contrarian),
        ("cta", _f_cta),
    ]

    idx = 0
    for name, func in slide_specs:
        dur = durations[idx] if idx < len(durations) else 12.0
        clip_path = output_dir / f"{idx + 1:02d}_{name}.mp4"

        if name == "title":
            top = cr[0] if cr else None
            data = dict(fps=fps, time_offset=time_offset, cr=cr,
                        date_str=date_str, top=top,
                        hook_text=script.get("hook", ""))
        elif name == "regime":
            direction = script.get("regime_direction", "neutral").lower()
            accent = ACCENT_GREEN if direction == "bullish" else (
                ACCENT_RED if direction == "bearish" else ACCENT_YELLOW)
            data = dict(fps=fps, time_offset=time_offset, cr=cr,
                        label=script.get("market_regime_label", "MIXED SIGNALS"),
                        text=script.get("market_regime", ""), accent=accent)
        elif name == "signal":
            data = dict(fps=fps, time_offset=time_offset, cr=cr)
        elif name == "matters":
            dims = summary.get("top_dimensions", [])
            if not dims:
                idx += 1
                time_offset += dur
                continue
            data = dict(fps=fps, time_offset=time_offset, cr=cr, dims=[
                {"label": d.get("label", d.get("key", "")),
                 "score": d.get("avg_score", 0)}
                for d in dims[:4]
            ])
        elif name == "watch":
            if not articles:
                idx += 1
                time_offset += dur
                continue
            data = dict(fps=fps, time_offset=time_offset, cr=cr,
                        articles=articles[:4], tickers_map=tickers_map)
        elif name == "contrarian":
            data = dict(fps=fps, time_offset=time_offset, cr=cr,
                        text=script.get("contrarian", ""))
        elif name == "cta":
            data = dict(fps=fps, time_offset=time_offset, cr=cr)
        else:
            idx += 1
            time_offset += dur
            continue

        log.info("Rendering animated slide %d/%d: %s (%.1fs)",
                 idx + 1, len(slide_specs), name, dur)
        _encode_clip(func, data, dur, fps, clip_path, fig, ax)
        clips.append(clip_path)
        time_offset += dur
        idx += 1

    plt.close(fig)
    log.info("Rendered %d animated clips to %s", len(clips), output_dir)
    return clips
