#!/usr/bin/env python3
"""
build_chart_reel.py — the "stacked curiosity" NIS reel: ONE full-frame price chart
that *animates as it expands* across the entire reel — exactly like the viral_reels
PriceChart, candles drawing in one-per-data-point with BOTH axes growing (newest
candle pinned to the right, earlier ones compressing left; the y-range expanding as
new highs/lows arrive) — with the Hot-Take-Arc copy riding on top as **floating
semi-transparent cards that cut in / out**.

Two things are always moving — the chart growing *and* the cards changing — so the eye
never rests (the retention trick the multi-element meme reels use, except the
"background motion" is the actual trade developing). The chart draws in the real
display window, then projects the *validated* breakout to the 2R target.

Mirrors viral_reels/reel/src/components/PriceChart.tsx:
  reveal = progress * (N-1);   x(i) = i/reveal   (revealed data fills full width);
  y-domain = running min/max over revealed candles (leading candle folded in via frac,
  so the range is continuous and never snaps); candles 0..last solid + leading partial.

Nothing is fabricated — levels come from a single live load (so the on-chart
Entry/Stop/Target and the spoken levels can't drift apart); fundamentals from FMP; a
claim is dropped if the number isn't there.

Run from code/analytics with its venv:
  cd code/analytics
  .venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_chart_reel.py \
      --ticker NWPX --hook-text "..."
Requires ELEVENLABS_API_KEY (+ a voice id) and APIKEY (FMP) in env or .env.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import build_setup_chart as bsc   # noqa: E402  (sets sys.path → code/analytics, loads .env)
import animate_breakout as ab     # noqa: E402  (load() + project())
import build_reel as br           # noqa: E402  (tts / probe_dur / walkthrough / verbal_hook)

import io  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.font_manager as _fm  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageFilter  # noqa: E402

import re  # noqa: E402

_BOLD_TTF = _fm.findfont(_fm.FontProperties(weight="bold"))
_REG_TTF = _fm.findfont(_fm.FontProperties(weight="normal"))
_MONO_TTF = _fm.findfont(_fm.FontProperties(family="monospace"))


def _pilfont(sz, bold=True):
    return ImageFont.truetype(_BOLD_TTF if bold else _REG_TTF, int(sz))


def _monofont(sz):
    return ImageFont.truetype(_MONO_TTF, int(sz))

# brand LIGHT theme — mirrors the UI's light tokens (--background 36 60% 98% warm
# off-white, --foreground 222 47% 11% navy ink, --primary 38 92% 50% amber, --border).
BG = "#FBF7F1"; INK = "#10182B"; MUT = "#566377"; MUT2 = "#8A93A4"; GRID = "#E4DBCE"
AMBER = "#F59E0B"; POS = "#16A34A"; NEG = "#DC2626"; PANEL = "#FFFFFF"; FUTURE = "#3B7DE0"
SMA_COL = {"SMA50": "#F59E0B", "SMA150": "#3B7DE0", "SMA200": "#7C5CD6"}
W, H, FPS, DPI = 1080, 1920, 30, 100  # full 9:16 vertical (Reels / TikTok / Shorts)
HEAD = 0.60   # data fills the lower 60% of the price pane; top 40% is card headroom
VOL_SURGE = 1.4
ZOOM_BARS = 22   # when projecting, the camera pushes in to ~this many real bars + the future
ZOOM_SECS = 0.9  # the camera push completes this fast once the projection starts (snap-zoom)


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, f):
    return a + (b - a) * f


def _ease(p):  # ease-out cubic — a smooth camera push, no abrupt zoom snap
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


# ---------------------------------------------------------------------------
# 1) Series: real display window + appended validated-breakout projection
# ---------------------------------------------------------------------------
def prepare_series(full: pd.DataFrame, tt: dict, setup_live: dict, display_days: int) -> dict:
    """Arrays the per-frame renderer draws from. Reuses animate_breakout.project()
    for the projection so the climax matches the breakout-validation logic exactly."""
    df = (full if "date" in full.columns else full.reset_index()).copy()
    df = df.tail(display_days).reset_index(drop=True)
    n_real = len(df)

    avg_vol = float(full["volume"].tail(50).mean())
    adr = float(tt.get("adr_pct") or 5.0)
    proj, _info = ab.project(setup_live, avg_vol, adr, "validated")
    proj[0]["open"] = float(df["close"].iloc[-1])  # stitch onto the last real close

    opens = list(df["open"]) + [b["open"] for b in proj]
    highs = list(df["high"]) + [b["high"] for b in proj]
    lows = list(df["low"]) + [b["low"] for b in proj]
    closes = list(df["close"]) + [b["close"] for b in proj]
    vols = list(df["volume"]) + [b["vol"] for b in proj]

    sma = {}
    for k in ("SMA50", "SMA150", "SMA200"):
        if k in df.columns:
            last = float(df[k].iloc[-1]) if pd.notna(df[k].iloc[-1]) else np.nan
            sma[k] = [float(v) if pd.notna(v) else np.nan for v in df[k]] + [last] * len(proj)

    v = np.array(vols, float)
    avg = pd.Series(v).rolling(50, min_periods=10).mean().to_numpy()
    surge = v >= VOL_SURGE * np.nan_to_num(avg, nan=np.inf)

    tr = setup_live
    return {
        "opens": np.array(opens, float), "highs": np.array(highs, float),
        "lows": np.array(lows, float), "closes": np.array(closes, float),
        "vols": v, "surge": surge, "sma": sma,
        "n_real": n_real, "N": len(opens),
        "pivot": tr["buy_point_pivot"], "stop": tr["stop"], "entry": tr["entry"],
        "target": tr["target_2r"], "buy_lo": tr["buy_range_low"], "buy_hi": tr["buy_range_high"],
    }


# ---------------------------------------------------------------------------
# 2) Per-frame renderer — the expanding chart (one persistent figure, redrawn)
# ---------------------------------------------------------------------------
class ChartRenderer:
    def __init__(self, s: dict):
        self.s = s
        self.fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
        self.fig.patch.set_facecolor(BG)
        # price pane fills most of the frame; volume pane sits along the bottom.
        self.axp = self.fig.add_axes([0.085, 0.30, 0.88, 0.66])
        self.axv = self.fig.add_axes([0.085, 0.075, 0.88, 0.185])

    def _style(self, ax):
        ax.set_facecolor(BG)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xticks([]); ax.set_yticks([])

    def frame(self, progress: float, zoom: float = 0.0) -> Image.Image:
        s = self.s; N = s["N"]
        axp, axv = self.axp, self.axv
        axp.cla(); axv.cla(); self._style(axp); self._style(axv)

        reveal = max(1e-6, min(1.0, progress) * (N - 1))
        last = int(np.floor(reveal)); frac = reveal - last
        nxt = min(last + 1, N - 1)
        o, hi_, lo_, c, vol = s["opens"], s["highs"], s["lows"], s["closes"], s["vols"]
        cur_close = _lerp(c[last], c[nxt], frac)
        n_real = s["n_real"]; boundary = n_real - 0.5

        # Zoom: a fast camera push onto the recent action + the projection so the breakout
        # fills the frame. `zoom` (0..1) is driven by the caller off frame-TIME — it snaps
        # in within ZOOM_SECS rather than crawling across the whole projection draw.
        z = max(0.0, min(1.0, zoom))
        x1 = reveal + 0.6
        x0 = _lerp(-0.6, max(-0.6, boundary - ZOOM_BARS), z)
        vstart = max(0, int(np.floor(x0)) + 1)  # left-most VISIBLE bar

        # y-domain: running min/max over the VISIBLE candles only (so the zoom tightens
        # both axes), leading candle folded in via frac to keep it continuous.
        lo = min(lo_[vstart:last + 1].min(), cur_close, _lerp(cur_close, lo_[nxt], frac))
        hi = max(hi_[vstart:last + 1].max(), cur_close, _lerp(cur_close, hi_[nxt], frac))
        span = (hi - lo) or (cur_close * 0.02)
        lo -= span * 0.10; hi += span * 0.10
        # reserve top headroom so candles never hide behind the floating card
        ylo, yhi = lo, lo + (hi - lo) / HEAD
        cw = 0.62  # candle body width in data units (visually widens as the window zooms in)

        # ---- price pane ----
        projecting = reveal >= n_real - 1  # the "now" line (boundary) splits real | future

        # The future zone is drawn FIRST (under everything) so it reads as a distinct
        # backdrop. Real candles are solid; projected candles are hollow + dashed, so
        # there's no mistaking the hypothetical breakout for tape that already printed.
        if projecting:
            for ax in (axp, axv):
                ax.axvspan(boundary, x1, color=FUTURE, alpha=0.07, zorder=0)
            axp.axvline(boundary, color=FUTURE, lw=1.6, ls=(0, (5, 4)), alpha=0.85, zorder=1)
            axv.axvline(boundary, color=FUTURE, lw=1.6, ls=(0, (5, 4)), alpha=0.85, zorder=1)
            axp.text(boundary, yhi - (yhi - ylo) * 0.015, " NOW", color=FUTURE,
                     fontsize=14, fontweight="bold", ha="left", va="top", zorder=7)
            axp.text(boundary + (x1 - boundary) * 0.5, ylo + (yhi - ylo) * 0.30, "PROJECTED",
                     color=FUTURE, fontsize=15, fontweight="bold", ha="center", va="center",
                     rotation=90, alpha=0.8, zorder=7)
            axp.text(boundary, ylo + (yhi - ylo) * 0.015, "← real    if it confirms →",
                     color=MUT2, fontsize=12, ha="center", va="bottom", zorder=7)

        def candle(i, alpha):
            col = POS if c[i] >= o[i] else NEG
            bh = abs(c[i] - o[i]) or 1e-9
            if i >= n_real:  # projected — hollow body + dashed wick = clearly hypothetical
                axp.plot([i, i], [lo_[i], hi_[i]], color=col, lw=1.4, alpha=alpha * 0.9,
                         ls=(0, (2, 2)), solid_capstyle="round")
                axp.add_patch(Rectangle((i - cw / 2, min(o[i], c[i])), cw, bh, facecolor="none",
                                        edgecolor=col, lw=1.6, alpha=alpha, ls="--"))
            else:            # real — solid
                axp.plot([i, i], [lo_[i], hi_[i]], color=col, lw=1.4, alpha=alpha, solid_capstyle="round")
                axp.add_patch(Rectangle((i - cw / 2, min(o[i], c[i])), cw, bh,
                                        facecolor=col, edgecolor=col, lw=0.4, alpha=alpha))
        # SMAs (under candles) — only over REAL bars; never extended into the projection.
        sma_n = min(last, n_real - 1)
        xs = np.arange(sma_n + 1)
        for k, col in SMA_COL.items():
            if k in s["sma"] and sma_n >= 0:
                axp.plot(xs, np.array(s["sma"][k][:sma_n + 1], float), color=col, lw=1.5, alpha=0.9)
        for i in range(last + 1):
            candle(i, 1.0)
        if frac > 1e-3 and nxt > last:
            candle(nxt, min(1.0, frac * 1.4))

        # Trade levels + buy band — ONLY once we're projecting, and only across the
        # future region (they're the plan for the breakout, not history).
        if projecting:
            if ylo <= s["buy_lo"] <= yhi or ylo <= s["buy_hi"] <= yhi:
                axp.add_patch(Rectangle((boundary, s["buy_lo"]), x1 - boundary,
                                        s["buy_hi"] - s["buy_lo"], facecolor=AMBER, edgecolor="none",
                                        alpha=0.08, zorder=0))
            for y, col, lab, ls in [(s["target"], POS, f"Target {s['target']:,.2f}", (0, (5, 4))),
                                     (s["entry"], AMBER, f"Entry {s['entry']:,.2f}", "-"),
                                     (s["stop"], NEG, f"Stop {s['stop']:,.2f}", (0, (1, 3)))]:
                if ylo <= y <= yhi:
                    axp.plot([boundary, x1], [y, y], color=col, lw=1.5, ls=ls, alpha=0.9)
                    axp.text(x1, y, f" {lab}", color=col, fontsize=14, fontweight="bold",
                             ha="right", va="bottom")
        # live price tag riding the leading edge
        edge_col = POS if cur_close >= c[0] else NEG
        axp.plot([reveal], [cur_close], "o", color=edge_col, ms=9, zorder=6)
        axp.text(reveal, cur_close + (yhi - ylo) * 0.012, f"${cur_close:,.2f}",
                 color=INK, fontsize=17, fontweight="bold", ha="right", va="bottom", zorder=6)
        # a couple of horizontal gridlines + price labels (left)
        for gv in (ylo + (yhi - ylo) * 0.12, lo + span * 0.5, hi):
            axp.axhline(gv, color=GRID, lw=1, alpha=0.6)
            axp.text(x0, gv, f"${gv:,.0f}", color=MUT2, fontsize=14, ha="left", va="bottom")
        axp.set_xlim(x0, x1); axp.set_ylim(ylo, yhi)

        # ---- volume pane ----
        vmax = max(vol[:last + 1].max(), 1.0) * 1.15

        def vbar(i, h, alpha=1.0):
            col = AMBER if s["surge"][i] else (POS if c[i] >= o[i] else NEG)
            if i >= n_real:  # projected volume — hollow + dashed, matches the candles
                axv.bar(i, h, width=cw, facecolor="none", edgecolor=col, lw=1.4, ls="--", alpha=alpha)
            else:
                axv.bar(i, h, width=cw, color=col, alpha=alpha)
        for i in range(last + 1):
            vbar(i, vol[i])
        if frac > 1e-3 and nxt > last:
            vbar(nxt, vol[nxt] * frac, alpha=min(1.0, frac * 1.4))
        axv.text(x0, vmax * 0.86, "Volume", color=MUT2, fontsize=13, ha="left", va="center")
        axv.set_xlim(x0, x1); axv.set_ylim(0, vmax)

        self.fig.canvas.draw()
        buf = np.asarray(self.fig.canvas.buffer_rgba())
        return Image.fromarray(buf).convert("RGBA")


# ---------------------------------------------------------------------------
# 3) Floating content cards — RGBA, transparent background, translucent panel
# ---------------------------------------------------------------------------
def _card_fig():
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off"); ax.patch.set_alpha(0)
    return fig, ax


def _panel(ax, x, y, w, h, *, ec=AMBER, lw=2.0, alpha=0.92):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
                                fc=(*[v / 255 for v in _hex(PANEL)], alpha), ec=ec, lw=lw,
                                mutation_aspect=0.62, zorder=1))


def _save(fig, path):
    fig.savefig(path, transparent=True, dpi=100); plt.close(fig)


def hook_card(path, ticker, lead, l1, l2):
    fig, ax = _card_fig()
    _panel(ax, 0.05, 0.70, 0.90, 0.245)
    ax.add_patch(Rectangle((0.09, 0.905), 0.026, 0.014, color=AMBER, zorder=2))
    ax.text(0.13, 0.911, f"{ticker} · NIS MOMENTUM", color=AMBER, fontsize=21,
            fontweight="bold", va="center", zorder=2)
    ax.text(0.09, 0.865, lead, color=AMBER, fontsize=22, fontweight="bold", va="center", zorder=2)
    fs = max(34, min(56, int(940 / max(len(l1), len(l2), 1))))
    ax.text(0.09, 0.805, l1, color=INK, fontsize=fs, fontweight="bold", va="center", zorder=2)
    ax.text(0.09, 0.745, l2, color=AMBER, fontsize=fs, fontweight="bold", va="center", zorder=2)
    _save(fig, path)


def stat_card(path, big, label, kicker, color):
    fig, ax = _card_fig()
    _panel(ax, 0.05, 0.755, 0.90, 0.19, ec=GRID, lw=1.6)
    ax.text(0.09, 0.915, kicker, color=AMBER, fontsize=18, fontweight="bold", va="center", zorder=2)
    n = len(str(big)); fs = 110 if n <= 4 else 80 if n <= 8 else 56
    ax.text(0.09, 0.83, str(big), color=color, fontsize=fs, fontweight="bold", va="center", zorder=2)
    ax.text(0.92, 0.80, label, color=INK, fontsize=26, ha="right", va="center", zorder=2)
    _save(fig, path)


def breakout_card(path, volx):
    fig, ax = _card_fig()
    _panel(ax, 0.05, 0.755, 0.90, 0.19, ec=POS, lw=2.2)
    ax.text(0.09, 0.915, "● THE BREAKOUT", color=POS, fontsize=20, fontweight="bold", va="center", zorder=2)
    ax.text(0.09, 0.845, "Close above the pivot,", color=INK, fontsize=38, fontweight="bold", va="center", zorder=2)
    vtxt = f"on {volx:.1f}× volume." if volx else "on a volume surge."
    ax.text(0.09, 0.785, vtxt, color=POS, fontsize=38, fontweight="bold", va="center", zorder=2)
    _save(fig, path)


def text_card(path, kicker, title, body, accent=AMBER):
    fig, ax = _card_fig()
    _panel(ax, 0.05, 0.725, 0.90, 0.22, ec=accent, lw=2.0)
    ax.text(0.09, 0.915, kicker, color=accent, fontsize=19, fontweight="bold", va="center", zorder=2)
    ax.text(0.09, 0.85, title, color=INK, fontsize=42, fontweight="bold", va="center", zorder=2)
    ax.text(0.09, 0.775, body, color=MUT, fontsize=25, va="center", linespacing=1.3, zorder=2)
    _save(fig, path)


def cta_card(path):
    fig, ax = _card_fig()
    _panel(ax, 0.05, 0.70, 0.90, 0.245, ec=AMBER, lw=2.0)
    ax.text(0.09, 0.915, "BEFORE YOU TRADE", color=AMBER, fontsize=19, fontweight="bold", va="center", zorder=2)
    ax.text(0.09, 0.85, "Not financial advice.", color=INK, fontsize=40, fontweight="bold", va="center", zorder=2)
    ax.text(0.09, 0.795, "Education only — do your own research.", color=MUT, fontsize=23, va="center", zorder=2)
    ax.add_patch(FancyBboxPatch((0.09, 0.715), 0.62, 0.04, boxstyle="round,pad=0.005",
                                fc=AMBER, ec="none", mutation_aspect=0.5, zorder=2))
    ax.text(0.40, 0.735, "newsimpactscreener.com", color=INK, fontsize=22,
            fontweight="bold", ha="center", va="center", zorder=3)
    _save(fig, path)


# ---------------------------------------------------------------------------
# 3.5) The COVER — an animated TITLE CARD (frame 1 is the ad). Company logo +
# ticker + name, the hook line, and the reel's 3 key facts as chips that stagger
# in. Taste-skill styling: radial-vignette depth, one amber accent, rounded chips,
# a soft glow behind the ticker. NO chart, NO tease flash (that read as a glitch).
# ---------------------------------------------------------------------------
def _radial_bg():
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    d = np.clip(np.sqrt(((xx - W * 0.5) / (W * 0.85)) ** 2 + ((yy - H * 0.40) / (H * 0.56)) ** 2), 0, 1) ** 1.2
    inner, outer = np.array(_hex("#FFFFFF"), float), np.array(_hex("#F0E7D9"), float)
    arr = (inner * (1 - d[..., None]) + outer * d[..., None]).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def _glow(color, w, h, rad, alpha=70):
    g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([w * 0.5 - rad, h * 0.5 - rad * 0.66, w * 0.5 + rad, h * 0.5 + rad * 0.66],
                              fill=(*color, alpha))
    return g.filter(ImageFilter.GaussianBlur(rad * 0.5))


def _alpha(img, a):
    if a >= 1:
        return img
    r, g, b, al = img.split()
    return Image.merge("RGBA", (r, g, b, al.point(lambda v: int(v * a))))


def _fetch_logo(ticker, size=190):
    """Company logo from FMP, circle-cropped on a white disc (logos are often
    dark-on-transparent and would vanish on the dark cover). None if unavailable."""
    key = os.environ.get("APIKEY") or os.environ.get("FMP_API_KEY", "")
    try:
        r = requests.get(f"https://financialmodelingprep.com/image-stock/{ticker}.png",
                         params={"apikey": key}, timeout=10)
        if r.status_code != 200 or len(r.content) < 200:
            return None
        logo = Image.open(io.BytesIO(r.content)).convert("RGBA").resize((size - 24, size - 24))
        disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(disc).ellipse([0, 0, size - 1, size - 1], fill=(255, 255, 255, 255))
        disc.alpha_composite(logo, dest=(12, 12))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(disc, (0, 0), mask)
        # ring so the white disc reads as a chip on the light background
        ImageDraw.Draw(out).ellipse([1, 1, size - 2, size - 2], outline=(*_hex(GRID), 255), width=3)
        return out
    except Exception:
        return None


# ---- fact-card tokens (light theme; accents are the brand green/amber) ----
INFO = "#2563EB"
_ACCENT = {"pos": POS, "green": POS, "bull": POS, "amber": AMBER, "watch": AMBER,
           "trend": AMBER, "neg": NEG, "red": NEG, "bear": NEG, "info": INFO,
           "blue": INFO, "ink": INK}


def _accent(c):
    if isinstance(c, str):
        if c in _ACCENT:
            return _ACCENT[c]
        if c.startswith("#"):
            return c
    return INK


def _mix(base_hex, top_hex, f):
    """`top` at fraction f over `base` (for accent@10% fills / @30% borders on white)."""
    a, b = _hex(base_hex), _hex(top_hex)
    return tuple(round(a[i] * (1 - f) + b[i] * f) for i in range(3))


def _split_headline_number(big):
    """Pull a numeric token out of a headline so the NUMBER can be the right anchor.
    'PROFITS 2×'→('PROFITS','2×'); 'PAY IN 4'→('PAY IN','4'); 'BIG BUYERS'→(…,None)."""
    toks = str(big).split()
    for i, t in enumerate(toks):
        if any(ch.isdigit() for ch in t):
            num = t[:-1] + "×" if t[-1:] in "xX" else t
            return (" ".join(toks[:i] + toks[i + 1:]).strip() or str(big).strip()), num
    return str(big).strip(), None


def _norm_fact(p):
    """Normalise a script point (dict) or fallback tuple → a card model:
    {headline, number, tag, signal, accent}. Explicit headline/number/tag/signal
    win; otherwise headline/number are split out of the legacy `big`."""
    if isinstance(p, dict):
        headline, number = p.get("headline"), p.get("number")
        if headline is None and number is None:
            headline, number = _split_headline_number(p.get("big", "") or "")
        elif headline is None:
            headline, _ = _split_headline_number(p.get("big", "") or "")
        tag = p.get("tag") if p.get("tag") is not None else (p.get("label") or "")
        signal = (p.get("signal") or "none").lower()
        accent = _accent(p.get("color", "ink"))
    else:
        big, label, color = p
        headline, number = _split_headline_number(big)
        tag, signal, accent = (label or ""), "none", _accent(color)
    return {"headline": (headline or "").upper(), "number": (number or None),
            "tag": tag, "signal": signal, "accent": accent}


# card geometry + motion (1080×1920; band ~960 wide, upper-middle third)
_CARD_W, _CARD_H, _CARD_CY, _CARD_M = 960, 210, 600, 50
_ENTER, _EXIT = 0.55, 0.40


def _spring(t):  # easeOutBack — settles with a ~2.5% overshoot (native-to-Reels feel)
    t = min(1.0, max(0.0, t)); s, u = 0.40, t - 1.0
    return 1 + (s + 1) * u * u * u + s * u * u


class CoverRenderer:
    def __init__(self, ticker, name, sub, facts, logo, show_chips=True, hold=1.1, exit_mode="slide"):
        self.ticker, self.name, self.sub, self.logo = ticker, name, sub, logo
        self.show_chips, self.hold, self.exit_mode = show_chips, hold, exit_mode
        self.last_exits = False  # True only for the standalone overlay export
        # REVEAL ORDER = array order, unless points carry an explicit "order" key.
        # The index chip (01/02/03) is assigned from this final order, so the
        # on-screen sequence and the printed indices always agree (#6).
        items = list(facts)
        if items and all(isinstance(f, dict) and "order" in f for f in items):
            items = sorted(items, key=lambda f: f["order"])
        self.facts_n = []
        for i, f in enumerate(items):
            nf = _norm_fact(f); nf["_idx"] = f"{i + 1:02d}"; self.facts_n.append(nf)
        self.ticker_cy = 430 if logo is not None else 320
        self.bg = _radial_bg()
        self.glow = _glow(_hex(AMBER), 760, 320, 250, 34)
        self.static = self._static()

    def card_total(self):
        step = _ENTER + self.hold
        return len(self.facts_n) * step + (_EXIT if self.exit_mode == "slide" else 0.0)

    def _cascade(self, dst, sec):
        """ONE card at a time, sequential, sliding in from the RIGHT (spring + ~2%
        overshoot), holding, then pushed/cut out to the left as the next enters."""
        n = len(self.facts_n)
        if n == 0:
            return
        step = _ENTER + self.hold
        base_x = (W - _CARD_W) // 2
        card_top = _CARD_CY - _CARD_H // 2
        for i, fact in enumerate(self.facts_n):
            t0 = i * step
            if sec < t0:
                continue
            rel = sec - t0
            dx = (1.0 - _spring(rel / _ENTER)) * 1.10 * W if rel < _ENTER else 0.0
            is_last = (i == n - 1)
            t_exit = t0 + step
            if sec >= t_exit:
                if is_last and not self.last_exits:
                    pass  # baked cover: last card holds to the end
                elif self.exit_mode == "cut":
                    continue  # hard cut — disappear as the next enters
                else:
                    eo = (sec - t_exit) / _EXIT
                    if eo >= 1.0:
                        continue
                    dx -= (eo * eo) * 1.10 * W  # ease-in slide out to the left
            spr = self._render_card(fact, max(0.0, rel - _ENTER))
            dst.alpha_composite(spr, (int(base_x + dx) - _CARD_M, card_top - _CARD_M))

    def chips_overlay_frame(self, sec):
        """The cards on a fully TRANSPARENT canvas — frames for the standalone alpha
        video you drop over your talking-head intro."""
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self._cascade(lay, sec)
        return lay

    def _static(self):
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        cx = W // 2
        if self.logo is not None:
            lay.alpha_composite(self.logo, dest=(cx - self.logo.width // 2, 200))
        d.text((cx, self.ticker_cy), f"${self.ticker}", font=_pilfont(98, True),
               fill=(*_hex(AMBER), 255), anchor="mm")
        d.text((cx, self.ticker_cy + 80), self.name, font=_pilfont(34, False),
               fill=(*_hex(MUT), 255), anchor="mm")
        d.text((cx, self.ticker_cy + 178), self.sub, font=_pilfont(54, True),
               fill=(*_hex(INK), 255), anchor="mm")
        d.text((cx, H - 86), "NIS MOMENTUM  ·  newsimpactscreener.com", font=_pilfont(24, True),
               fill=(*_hex(MUT2), 255), anchor="mm")
        return lay

    def _render_card(self, fact, hold_t):
        """One white card: index chip + headline + tag pill (tight LEFT block) and an
        oversized mono NUMBER anchored RIGHT, plus one micro-motion per `signal`."""
        acc, accx = _hex(fact["accent"]), fact["accent"]
        M = _CARD_M
        sw, sh = _CARD_W + 2 * M, _CARD_H + 2 * M
        spr = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        x0, y0, x1, y1 = M, M, M + _CARD_W, M + _CARD_H
        # depth: IDENTICAL elevation on every card — a neutral shadow drives the lift
        # (same for all accents); the accent tint is a faint constant, so green and
        # amber cards read at the same weight.
        s1 = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        ImageDraw.Draw(s1).rounded_rectangle([x0, y0 + 16, x1, y1 + 18], radius=30, fill=(15, 23, 42, 64))
        spr.alpha_composite(s1.filter(ImageFilter.GaussianBlur(26)))
        s2 = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        ImageDraw.Draw(s2).rounded_rectangle([x0, y0 + 18, x1, y1 + 20], radius=30, fill=(*acc, 26))
        spr.alpha_composite(s2.filter(ImageFilter.GaussianBlur(30)))
        d = ImageDraw.Draw(spr)
        d.rounded_rectangle([x0, y0, x1, y1], radius=26, fill=(255, 255, 255, 255),
                            outline=(*_hex(GRID), 255), width=1)
        d.rounded_rectangle([x0, y0 + 20, x0 + 6, y1 - 20], radius=3, fill=(*acc, 255))  # left strip (EVERY card)
        fill10 = _mix("#FFFFFF", accx, 0.10)
        bord = _mix("#FFFFFF", accx, 0.32)
        lx = x0 + 42
        # index chip (mono, accent, bordered)
        idx, ifn, ih = fact["_idx"], _monofont(22), 38
        iw = d.textlength(idx, font=ifn) + 28
        d.rounded_rectangle([lx, y0 + 24, lx + iw, y0 + 24 + ih], radius=10,
                            fill=(*fill10, 255), outline=(*bord, 255), width=1)
        d.text((lx + 14, y0 + 24 + ih / 2), idx, font=ifn, fill=(*acc, 255), anchor="lm")
        # headline (bold display, accent) — its optical center is the GRID line every
        # right-side anchor locks to (#1b, #4).
        anchor_cy = y0 + 96
        hf = _pilfont(52, True)
        while d.textlength(fact["headline"], font=hf) > _CARD_W * 0.56 and hf.size > 30:
            hf = _pilfont(hf.size - 3, True)
        d.text((lx, anchor_cy), fact["headline"], font=hf, fill=(*acc, 255), anchor="lm")
        # tag pill (mono, accent text on accent@10%, accent@30% border)
        if fact["tag"]:
            tf = _monofont(23); tw = d.textlength(fact["tag"], font=tf)
            while tw > _CARD_W * 0.58 and tf.size > 15:
                tf = _monofont(tf.size - 2); tw = d.textlength(fact["tag"], font=tf)
            ty, th = y0 + 150, 40
            d.rounded_rectangle([lx, ty, lx + tw + 30, ty + th], radius=11,
                                fill=(*fill10, 255), outline=(*_mix("#FFFFFF", accx, 0.30), 255), width=1)
            d.text((lx + 15, ty + th / 2), fact["tag"], font=tf, fill=(*acc, 255), anchor="lm")
        # RIGHT anchor — all locked to anchor_cy. Number is the hero when present;
        # otherwise the signal element becomes the centered anchor of equal weight.
        rx = x1 - 46
        if fact["number"]:
            nf = _monofont(88)
            while d.textlength(fact["number"], font=nf) > _CARD_W * 0.40 and nf.size > 46:
                nf = _monofont(nf.size - 4)
            d.text((rx, anchor_cy), fact["number"], font=nf, fill=(*acc, 255), anchor="rm")
            num_left = rx - d.textlength(fact["number"], font=nf)
            self._adorn(spr, d, fact, hold_t, acc, num_left, anchor_cy)   # spark/arrow into the number
        else:
            self._anchor_signal(spr, d, fact, hold_t, acc, accx, rx, anchor_cy)  # full right anchor
        return spr

    def _adorn(self, spr, d, fact, t, acc, num_left, cy):
        """A small signal element bound immediately LEFT of the hero number, on the
        number's baseline, so the two read as ONE unit leading into the figure."""
        sig = fact["signal"]
        if sig == "spark":
            ys = [0.78, 0.62, 0.70, 0.46, 0.52, 0.26, 0.10]   # rising
            n = len(ys)
            xb, xa = num_left - 16, num_left - 16 - 122        # ends right against the number
            band_t, band_h = cy - 34, 64
            pts = [(xa + (xb - xa) * i / (n - 1), band_t + ys[i] * band_h) for i in range(n)]
            m = max(2, int(_ease(min(1.0, t / 0.55)) * (n - 1)) + 1)
            d.line(pts[:m], fill=(*acc, 255), width=8, joint="curve")          # heavier stroke
            hx, hy = pts[m - 1]
            d.ellipse([hx - 8, hy - 8, hx + 8, hy + 8], fill=(*acc, 255))
        elif sig == "arrow":
            ay = cy + int(np.sin(t * 4.0) * 4)
            ax, s = num_left - 30, 34
            d.line([ax, ay + s, ax, ay - s], fill=(*acc, 255), width=11)
            d.line([ax, ay - s, ax - 18, ay - s + 20], fill=(*acc, 255), width=11)
            d.line([ax, ay - s, ax + 18, ay - s + 20], fill=(*acc, 255), width=11)
        elif sig == "live":  # inline pulsing dot just left of the number
            p = 0.5 + 0.5 * float(np.sin(t * 6.0))
            dx, r = num_left - 30, 8 + 3 * p
            d.ellipse([dx - r, cy - r, dx + r, cy + r], fill=(*acc, 255))

    def _anchor_signal(self, spr, d, fact, t, acc, accx, rx, cy):
        """No number → the signal IS the right anchor, centered on the grid line and
        sized to match the 2× / ↑4 numbers."""
        sig = fact["signal"]
        if sig == "live":   # buy-pressure bar group + pulsing 'LIVE VOL'
            p = 0.5 + 0.5 * float(np.sin(t * 5.0))
            bw, gap, n = 17, 13, 5
            heights = [0.42, 0.56, 0.70, 0.85, 1.0]
            ops = [0.55, 0.66, 0.77, 0.88, 1.0]
            Hmax = 74
            group_w = n * bw + (n - 1) * gap
            xL = rx - group_w
            base = cy + 14                                   # bars bottom
            for i in range(n):
                h = heights[i] * Hmax * (0.90 + 0.10 * p if i >= n - 2 else 1.0)
                op = ops[i] * (0.85 + 0.15 * p if i == n - 1 else 1.0)
                bx = xL + i * (bw + gap)
                d.rounded_rectangle([bx, base - h, bx + bw, base], radius=4,
                                    fill=(*_mix("#FFFFFF", accx, op), 255))
            lf, lab = _monofont(20), "LIVE VOL"
            ly = base + 28
            dotx = rx - d.textlength(lab, font=lf) - 20
            r = 6 + 3 * p
            halo = Image.new("RGBA", spr.size, (0, 0, 0, 0))
            ImageDraw.Draw(halo).ellipse([dotx - r - 7, ly - r - 7, dotx + r + 7, ly + r + 7],
                                         fill=(*acc, int(90 * p)))
            spr.alpha_composite(halo.filter(ImageFilter.GaussianBlur(5)))
            d.ellipse([dotx - r, ly - r, dotx + r, ly + r], fill=(*acc, 255))
            d.text((rx, ly), lab, font=lf, fill=(*acc, 255), anchor="rm")
        elif sig == "arrow":   # big centered arrow
            ay = cy + int(np.sin(t * 4.0) * 5); ax, s = rx - 30, 44
            d.line([ax, ay + s, ax, ay - s], fill=(*acc, 255), width=13)
            d.line([ax, ay - s, ax - 24, ay - s + 26], fill=(*acc, 255), width=13)
            d.line([ax, ay - s, ax + 24, ay - s + 26], fill=(*acc, 255), width=13)
        elif sig == "spark":   # big centered sparkline
            ys = [0.80, 0.64, 0.72, 0.48, 0.54, 0.28, 0.08]
            n = len(ys); xb, xa = rx, rx - 230
            band_t, band_h = cy - 44, 84
            pts = [(xa + (xb - xa) * i / (n - 1), band_t + ys[i] * band_h) for i in range(n)]
            m = max(2, int(_ease(min(1.0, t / 0.6)) * (n - 1)) + 1)
            d.line(pts[:m], fill=(*acc, 255), width=8, joint="curve")
            hx, hy = pts[m - 1]
            d.ellipse([hx - 8, hy - 8, hx + 8, hy + 8], fill=(*acc, 255))

    def frame(self, sec):
        f = self.bg.copy()
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * np.sin(sec * 2.4))  # soft breathing glow on the ticker
        f.alpha_composite(_alpha(self.glow, pulse),
                          dest=(W // 2 - self.glow.width // 2, self.ticker_cy - self.glow.height // 2))
        f.alpha_composite(self.static)
        if self.show_chips:  # green-screen leaves them off the cover (exported as an alpha video)
            self._cascade(f, sec)
        return f.convert("RGB")


class ComparisonRenderer:
    """Animated 'HOW IT STACKS UP' leaderboard — the ticker's trailing return vs
    NVDA / MSFT / AAPL / S&P, sorted, the ticker highlighted, bars growing in.
    Honest: real returns; negatives go red; we never assume the ticker is #1."""

    def __init__(self, ticker, benchmarks):
        items = [(k, float(v)) for k, v in (benchmarks.get("returns") or {}).items()]
        items.sort(key=lambda kv: kv[1], reverse=True)
        self.items = items
        self.ticker = ticker
        self.window = benchmarks.get("window_days", 126)
        self.maxret = max((v for _, v in items if v > 0), default=0.01)
        self.bg = _radial_bg()

    def frame(self, sec):
        f = self.bg.copy(); d = ImageDraw.Draw(f)
        months = max(1, round(self.window / 21))
        d.text((90, 215), "HOW IT STACKS UP", font=_pilfont(62, True), fill=(*_hex(INK), 255), anchor="lm")
        d.text((90, 288), f"~{months}-month return  ·  {self.ticker} vs the names everyone knows",
               font=_pilfont(27, False), fill=(*_hex(MUT), 255), anchor="lm")
        y0, dy, tx0, tx1 = 440, 250, 90, 760
        for i, (name, ret) in enumerate(self.items):
            cy = y0 + i * dy
            a = _ease(min(1.0, max(0.0, (sec - (0.20 + i * 0.14)) / 0.30)))
            if a <= 0:
                continue
            top = name == self.ticker
            barcol = _hex(AMBER) if top else (_hex(POS) if ret >= 0 else _hex(NEG))
            d.text((tx0, cy - 40), name, font=_pilfont(42 if top else 34, True),
                   fill=(*(_hex(AMBER) if top else _hex(INK)), 255), anchor="lm")
            d.rounded_rectangle([tx0, cy + 4, tx1, cy + 46], radius=21, fill=(*_hex("#EBE2D4"), 255))
            frac = min(1.0, max(0.035, max(ret, 0) / self.maxret if self.maxret > 0 else 0)) * a
            d.rounded_rectangle([tx0, cy + 4, tx0 + frac * (tx1 - tx0), cy + 46], radius=21, fill=(*barcol, 255))
            d.text((W - 90, cy + 25), f"{ret * 100:+.0f}%", font=_pilfont(46 if top else 38, True),
                   fill=(*barcol, 255), anchor="rm")
        return f.convert("RGB")


class LineCompareRenderer:
    """The ticker vs the S&P 500 as two normalized lines (both start at 100), drawing
    in left→right so you WATCH the ticker pull away from the market. The honest, plain
    answer to 'is it strong?' — no jargon, just two lines."""
    _SPY = "#6E7C92"

    def __init__(self, ticker, benchmarks):
        s = benchmarks["series"]
        self.t = np.array(s["TICKER"], float)
        self.m = np.array(s["S&P 500"], float)
        self.ticker = ticker
        months = max(1, round(benchmarks.get("window_days", 126) / 21))
        self.fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
        self.fig.patch.set_facecolor(BG)
        self.ax = self.fig.add_axes([0.085, 0.18, 0.83, 0.52])
        self.fig.text(0.085, 0.905, "VS THE MARKET", color=INK, fontsize=48, fontweight="bold", va="top")
        self.fig.text(0.085, 0.845, f"{ticker} vs the S&P 500  ·  last {months} months  ·  both start at 100",
                      color=MUT, fontsize=19, va="top")
        self._lt = self.fig.text(0.10, 0.665, "", color=AMBER, fontsize=26, fontweight="bold", va="top")
        self._lm = self.fig.text(0.10, 0.615, "", color=self._SPY, fontsize=22, fontweight="bold", va="top")

    def _style(self, ax):
        ax.set_facecolor(BG)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xticks([]); ax.set_yticks([])

    def frame(self, reveal):
        ax = self.ax; ax.cla(); self._style(ax)
        N = len(self.t)
        k = max(2, int(round(_ease(min(1.0, reveal)) * (N - 1))) + 1)
        x = np.arange(N)
        lo = min(self.t.min(), self.m.min()); hi = max(self.t.max(), self.m.max())
        pad = (hi - lo) * 0.12 or 2.0
        ax.axhline(100, color=GRID, lw=1.2, ls=(0, (4, 4)), alpha=0.6)
        ax.text(-N * 0.015, 100, "100", color=MUT2, fontsize=13, ha="right", va="center")
        ax.plot(x[:k], self.m[:k], color=self._SPY, lw=3.0, alpha=0.95, zorder=3)
        ax.plot(x[:k], self.t[:k], color=AMBER, lw=4.6, solid_capstyle="round", zorder=4)
        ax.plot(x[k - 1], self.m[k - 1], "o", color=self._SPY, ms=9, zorder=5)
        ax.plot(x[k - 1], self.t[k - 1], "o", color=AMBER, ms=12, mec=INK, mew=1.2, zorder=6)
        tnow = self.t[k - 1] / self.t[0] - 1.0
        mnow = self.m[k - 1] / self.m[0] - 1.0
        self._lt.set_text(f"● {self.ticker}   {tnow * 100:+.0f}%")
        self._lm.set_text(f"● S&P 500   {mnow * 100:+.0f}%")
        ax.set_xlim(-N * 0.04, N - 1 + N * 0.04); ax.set_ylim(lo - pad, hi + pad)
        self.fig.canvas.draw()
        return Image.fromarray(np.asarray(self.fig.canvas.buffer_rgba())).convert("RGB")


def _short(text, maxlen=46):
    text = (text or "").strip().rstrip(".")
    if len(text) <= maxlen:
        return text
    return text[:maxlen].rsplit(" ", 1)[0] + "…"


def _slug(text):
    return "".join(c.lower() if c.isalnum() else "-" for c in str(text)).strip("-")[:20] or "card"


# ---------------------------------------------------------------------------
# 4) Compose scene frames: expanding chart + fading card
# ---------------------------------------------------------------------------
def render_scene_frames(renderer, card, frame_dir, n_frames, frac_start, frac_end, zoom_mode="none"):
    """zoom_mode: 'none' (full-frame, real phase) · 'ramp' (snap-zoom in over ZOOM_SECS,
    then hold — the climax scene) · 'full' (stay zoomed — the post-breakout hold cards)."""
    fade_frames = max(1, int(0.3 * FPS))
    zoom_frames = max(1, int(ZOOM_SECS * FPS))
    for i in range(n_frames):
        t = (i + 1) / n_frames
        prog = frac_start + (frac_end - frac_start) * t
        if zoom_mode == "full":
            zoom = 1.0
        elif zoom_mode == "ramp":
            zoom = _ease(min(1.0, (i + 1) / zoom_frames))
        else:
            zoom = 0.0
        frame = renderer.frame(prog, zoom=zoom)
        if card is not None:
            fade = min(1.0, (i + 1) / fade_frames)
            if fade < 1.0:
                r, g, b, a = card.split()
                a = a.point(lambda v: int(v * fade))
                card_f = Image.merge("RGBA", (r, g, b, a))
            else:
                card_f = card
            frame = Image.alpha_composite(frame, card_f)
        frame.convert("RGB").save(frame_dir / f"f{i:05d}.png")


ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-c:a", "aac", "-ar", "44100", "-b:a", "160k", "-vsync", "cfr"]


_VENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-vsync", "cfr"]


def encode_alpha(frame_dir, out, n_frames):
    """RGBA frames → a transparent-background video. ProRes 4444 (.mov) for editors;
    falls back to QTRLE if ProRes isn't built in. Both carry a real alpha channel."""
    base = ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frame_dir / "f%05d.png")]
    pro = base + ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
                  "-frames:v", str(n_frames), str(out)]
    if subprocess.run(pro, capture_output=True).returncode == 0:
        return "prores4444"
    subprocess.run(base + ["-c:v", "qtrle", "-pix_fmt", "argb",
                           "-frames:v", str(n_frames), str(out)], check=True, capture_output=True)
    return "qtrle"


def encode_segment(frame_dir, audio, out, dur, tempo):
    """Frames → segment. With `audio` it muxes the VO; with audio=None it renders
    a SILENT segment (script mode — the user records their own voice over)."""
    if audio is None:
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frame_dir / "f%05d.png"),
                        "-t", f"{dur:.3f}", *_VENC, str(out)], check=True, capture_output=True)
        return
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frame_dir / "f%05d.png"),
                    "-i", str(audio), "-filter_complex", f"[1:a]atempo={tempo:.3f},apad[a]",
                    "-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}", *ENC, str(out)],
                   check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Scenes + reveal schedule
# ---------------------------------------------------------------------------
_COLORS = {"pos": POS, "neg": NEG, "amber": AMBER, "ink": INK, "green": POS, "red": NEG}


def build_scenes(setup, fund, ticker, tmp, hook_text, script=None):
    """The reel body. By default (script=None) the Python templates auto-generate
    every stat card — a fallback. The PRIMARY path is a Claude-authored `script`:
    Claude reads setup.json, picks the **3 most notable things** about the company,
    and writes a punchy human line for each. That's hook → 3 points → trade → CTA.

    script schema (all optional except points/hook handled by the caller):
      {"points": [{"big": "RS 92", "label": "market leader", "color": "pos",
                   "vo": "It's outrunning ninety-two percent of the market."}, …],
       "breakout_vo": "...", "invalidation_vo": "...", "cta_vo": "..."}
    """
    script = script or {}
    t = setup["technical"]; tr = setup["trade_setup"]
    scenes = []
    lead, l1, l2, _viz, _data = bsc.standout(t, fund)
    hc = tmp / "card_hook.png"; hook_card(hc, ticker, lead, l1, l2)
    scenes.append({"vo": hook_text, "card": hc, "group": "real", "pad": 0.35, "tempo": 1.0,
                   "name": "HOOK"})

    kicker = f"{ticker} · NIS MOMENTUM"
    points = script.get("points")
    if points:  # Claude chose & wrote the notable things
        for i, p in enumerate(points):
            card = tmp / f"card_pt_{i:02d}.png"
            # support both the new schema (headline/number/tag) and legacy big/label
            big = p.get("big") or " ".join(x for x in (p.get("headline"), p.get("number")) if x)
            label = p.get("label") or p.get("tag") or ""
            stat_card(card, big, label, kicker, _COLORS.get(p.get("color", "ink"), INK))
            scenes.append({"vo": p["vo"], "card": card, "group": "real", "pad": 0.18,
                           "name": str(label).upper()})
    else:       # fallback: auto-generated walkthrough
        for i, b in enumerate(br.walkthrough(setup, fund, ticker)):
            card = tmp / f"card_stat_{i:02d}.png"
            stat_card(card, b["big"], b["label"], kicker, b["color"])
            scenes.append({"vo": b["vo"], "card": card, "group": "real", "pad": 0.12,
                           "name": str(b["label"]).upper()})

    bc = tmp / "card_breakout.png"; breakout_card(bc, 1.9)
    pivot = br.say_price(tr["buy_point_pivot"]); tgt = br.say_price(tr["target_2r"])
    scenes.append({
        "vo": script.get("breakout_vo") or
              (f"And here's the whole trade in one move — it clears {pivot} on volume and runs "
               f"to {tgt}. Two-to-one. Clean."),
        "card": bc, "group": "proj", "pad": 0.4, "tempo": 1.0, "name": "BREAKOUT"})

    sma50 = br.say_price(t["SMA50"]) if t.get("SMA50") else None
    inv = tmp / "card_inval.png"
    text_card(inv, "KNOW WHERE YOU'RE WRONG", "One rule.",
              (f"Loses the 50-day at {sma50} on volume — the setup is dead."
               if sma50 else "Loses the 50-day on volume — the setup is dead."), accent=NEG)
    scenes.append({
        "vo": script.get("invalidation_vo") or
              (f"Know your out first: back under the fifty-day at {sma50} on volume, and it's dead. Walk away."
               if sma50 else "Know your out first: back under the fifty-day on volume, and it's dead. Walk away."),
        "card": inv, "group": "hold", "pad": 0.4, "name": "INVALIDATION"})

    cta = tmp / "card_cta.png"; cta_card(cta)
    scenes.append({
        "vo": script.get("cta_vo") or
              ("None of this is advice — do your own homework. But the screener that flagged it? "
               "News impact screener dot com."),
        "card": cta, "group": "hold", "pad": 0.4, "name": "CTA"})
    return scenes


def assign_reveal(scenes, n_real, N, effs):
    """real scenes expand 0.08→split by duration; the proj scene expands split→1.0;
    hold scenes stay at 1.0. split = where the real candles end."""
    split = n_real / N
    real_idx = [i for i, s in enumerate(scenes) if s["group"] == "real"]
    real_total = sum(effs[i] for i in real_idx) or 1.0
    fr = 0.08
    spans = [None] * len(scenes)
    for i, s in enumerate(scenes):
        if s["group"] == "real":
            seg = (effs[i] / real_total) * (split - 0.08)
            spans[i] = (fr, fr + seg); fr += seg
        elif s["group"] == "proj":
            spans[i] = (split, 1.0)
        else:
            spans[i] = (1.0, 1.0)
    return spans


def main():
    ap = argparse.ArgumentParser(
        description="Expanding-chart NIS reel. SILENT by default — writes script.txt for you to voice.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--voice-id", default=None)
    ap.add_argument("--hook-text", default=None, help="spoken hook for the cover (else auto from data).")
    ap.add_argument("--hook-style", choices=["tension", "curiosity"], default="tension",
                    help="cover archetype: 'tension' (coil-led, default) or 'curiosity' (thesis-led).")
    ap.add_argument("--cover-line", default=None, help="explicit one-line cover hero (else auto).")
    ap.add_argument("--script", default=None,
                    help="JSON written by Claude: {hook, cover_line, points:[{big,label,color,vo}×3], "
                         "breakout_vo, invalidation_vo, cta_vo}. Overrides the auto templates.")
    ap.add_argument("--display-days", type=int, default=126,
                    help="Real trading days the chart grows through (126 ≈ half a year).")
    ap.add_argument("--tempo", type=float, default=1.08)
    ap.add_argument("--tts", action="store_true",
                    help="bake ElevenLabs VO (needs creds). Default: SILENT reel + script.txt to voice yourself.")
    ap.add_argument("--green-screen", action="store_true",
                    help="clean cover (no baked cards) + export the intro cards as a transparent "
                         "alpha video (intro_cards.mov) to overlay on your talking-head intro.")
    ap.add_argument("--card-hold", type=float, default=1.1, help="seconds each fact card holds (default 1.1).")
    ap.add_argument("--card-exit", choices=["slide", "cut"], default="slide",
                    help="'slide' = card pushes out left; 'cut' = hard cut (trim in your editor).")
    args = ap.parse_args()
    GS = args.green_screen

    ticker = args.ticker.upper().strip()
    d = pathlib.Path(args.dir) if args.dir else bsc.ANALYTICS_DIR / "output" / "setups" / ticker
    setup_json = json.loads((d / "setup.json").read_text())
    script = json.loads(pathlib.Path(args.script).read_text()) if args.script else {}

    voice = ""
    if args.tts:
        voice = (args.voice_id or os.environ.get("ELEVENLABS_PRIMARY_VOICE_ID")
                 or os.environ.get("ELEVENLABS_VOICE_ID") or "")
        voice = voice.split("#")[0].split()[0] if voice.strip() else ""
        if not voice:
            sys.exit("--tts needs a voice id (ELEVENLABS_PRIMARY_VOICE_ID or --voice-id)")
        if not os.environ.get("ELEVENLABS_API_KEY"):
            sys.exit("--tts needs ELEVENLABS_API_KEY (in env or code/analytics/.env)")

    fund = dict(setup_json.get("fundamentals") or {}) or br.fetch_fundamentals(ticker)
    fund.setdefault("company", setup_json.get("company") or ticker)

    # ONE live snapshot drives the chart, the projection, AND the levels, so the
    # on-chart Entry/Stop/Target can't drift from the script. Preserve a real RS rank
    # from setup.json (ab.load can't compute a universe rank solo).
    full, tt, setup_live = ab.load(ticker)
    tech = dict(tt)
    sj_tech = setup_json.get("technical") or {}
    for k in ("RS_Rank", "RSOver70", "rs_line_new_high"):
        if tech.get(k) is None and sj_tech.get(k) is not None:
            tech[k] = sj_tech[k]
    setup = {"technical": tech, "trade_setup": setup_live}

    series = prepare_series(full, tt, setup_live, args.display_days)
    renderer = ChartRenderer(series)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"chartreel_{ticker}_"))
    # Claude's --script wins; then --hook-text; then the auto fallback.
    hook_text = script.get("hook") or args.hook_text or br.verbal_hook(ticker, setup["technical"], fund)
    scenes = build_scenes(setup, fund, ticker, tmp, hook_text, script)
    scenes.pop(0)  # the old fade-up hook is replaced by the COVER poster below

    # Duration per scene: real TTS length, or a word-count estimate (so the silent
    # cuts land where a natural read would) — returns (seconds, audio_path|None).
    def vo_dur_audio(vo, audio_path, tempo, pad):
        if args.tts:
            br.tts(vo, audio_path, voice)
            return br.probe_dur(audio_path) / tempo + pad, audio_path
        # ~2.9 words/sec = a confident trader pace (not slow narration).
        return max(1.2, len(vo.split()) / 2.9 + 0.35) + pad, None

    # ---- COVER: an animated title card (logo + name + the reel's 3 key facts) ----
    if script.get("cover_line"):
        sub = script["cover_line"]
    elif args.cover_line:
        sub = args.cover_line
    elif args.hook_style == "curiosity":
        sub = _short(hook_text)
    else:
        sub = "breaking out — right now" if sj_tech.get("within_buy_range") else "one candle from triggering"

    # the 3 key facts: Claude's script points (dicts: headline/number/tag/signal/color),
    # else the first 3 stat cards as legacy tuples. _norm_fact handles both.
    pts = script.get("points")
    if pts:
        facts = pts[:3]
    else:
        wt = br.walkthrough(setup, fund, ticker)
        facts = [(b["big"], b["label"], b["color"]) for b in wt[1:4]]

    name = br._short_name(setup_json.get("company") or fund.get("company") or ticker)
    cover = CoverRenderer(ticker, name, sub, facts, _fetch_logo(ticker), show_chips=not GS,
                          hold=args.card_hold, exit_mode=args.card_exit)
    cov_dur, cov_audio = vo_dur_audio(hook_text, tmp / "vo_cover.mp3", args.tempo, 0.35)
    if not GS:  # baked cover shows the carousel — make sure it has time to complete
        cov_dur = max(cov_dur, cover.card_total())
    cov_n = max(1, round(cov_dur * FPS))
    cdir = tmp / "frames_cover"; cdir.mkdir()
    for i in range(cov_n):
        cover.frame(i / FPS).save(cdir / f"f{i:05d}.png")
    cov_seg = tmp / "seg_cover.mp4"
    encode_segment(cdir, cov_audio, cov_seg, cov_dur, args.tempo)
    print(f"[cover] {cov_dur:.1f}s  ${ticker} · {sub} · cards={[(f.get('headline') or f.get('big')) if isinstance(f, dict) else f[0] for f in facts]}", flush=True)

    # green-screen: the fact cards (one-at-a-time push carousel) on a STANDALONE alpha
    # video to drop over your talking-head intro. Cover above is left clean (cards off).
    overlay_path = overlay_codec = None
    if GS:
        cover.last_exits = True  # the last card slides out, so the overlay ends clean
        ov_dur = cover.card_total()
        ov_n = max(1, round(ov_dur * FPS))
        odir = tmp / "frames_overlay"; odir.mkdir()
        for i in range(ov_n):
            cover.chips_overlay_frame(i / FPS).save(odir / f"f{i:05d}.png")
        overlay_path = d / "intro_cards.mov"
        overlay_codec = encode_alpha(odir, overlay_path, ov_n)
        print(f"[overlay] intro_cards.mov ({overlay_codec}, {ov_dur:.1f}s, transparent)", flush=True)

    # ---- "vs the market" segment — the ticker vs the S&P 500 (line chart), else a bar
    # leaderboard fallback. Leads the body; replaces any RS jargon. ----
    comp_seg = None; cmp_dur = None; bvo = None
    benchmarks = setup_json.get("benchmarks") or {}
    rr = benchmarks.get("returns") or {}
    if benchmarks.get("series") or len(rr) >= 2:
        months = max(1, round(benchmarks.get("window_days", 126) / 21))
        tret, spy = rr.get(ticker), rr.get("S&P 500")
        bvo = script.get("benchmark_vo") or (
            f"And here's how it stacks up against the market. Over {months} months it ran "
            f"{tret*100:.0f} percent — the S&P did {spy*100:.0f}."
            if tret is not None and spy is not None
            else "And here's how it stacks up against the market.")
        cmp_dur, cmp_audio = vo_dur_audio(bvo, tmp / "vo_compare.mp3", args.tempo, 0.4)
        mdir = tmp / "frames_compare"; mdir.mkdir()
        nf = max(1, round(cmp_dur * FPS))
        if benchmarks.get("series"):  # two lines drawing in
            comp = LineCompareRenderer(ticker, benchmarks)
            for i in range(nf):
                comp.frame(min(1.0, (i / FPS) / max(0.1, cmp_dur * 0.72))).save(mdir / f"f{i:05d}.png")
        else:                          # bar-leaderboard fallback
            comp = ComparisonRenderer(ticker, benchmarks)
            for i in range(nf):
                comp.frame(i / FPS).save(mdir / f"f{i:05d}.png")
        comp_seg = tmp / "seg_compare.mp4"
        encode_segment(mdir, cmp_audio, comp_seg, cmp_dur, args.tempo)
        print(f"[compare] {cmp_dur:.1f}s  {'line vs S&P' if benchmarks.get('series') else 'bars'}  {rr}", flush=True)

    # ---- body scenes ----
    effs = []
    for i, s in enumerate(scenes):
        dur, aud = vo_dur_audio(s["vo"], tmp / f"vo_{i:02d}.mp3", s.get("tempo", args.tempo), s.get("pad", 0.25))
        effs.append(dur); s["audio"] = aud
    spans = assign_reveal(scenes, series["n_real"], series["N"], effs)

    # The comparison LEADS the body — it's the strength proof, in plain numbers,
    # and it replaces any "RS / relative strength" jargon card.
    # GS only swaps the COVER chips for overlays; every mid-reel card stays baked in.
    seg_paths = [cov_seg] + ([comp_seg] if comp_seg is not None else [])
    for i, s in enumerate(scenes):
        n_frames = max(1, round(effs[i] * FPS))
        fdir = tmp / f"frames_{i:02d}"; fdir.mkdir()
        card = Image.open(s["card"]).convert("RGBA") if s.get("card") else None
        f0, f1 = spans[i]
        zoom_mode = {"real": "none", "proj": "ramp", "hold": "full"}[s["group"]]
        render_scene_frames(renderer, card, fdir, n_frames, f0, f1, zoom_mode)
        seg = tmp / f"seg_{i:02d}.mp4"
        encode_segment(fdir, s["audio"], seg, effs[i], s.get("tempo", args.tempo))
        seg_paths.append(seg)

    listf = tmp / "list.txt"
    listf.write_text("".join(f"file '{p}'\n" for p in seg_paths))
    out_mp4 = d / "reel_chart.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-c", "copy", "-movflags", "+faststart", str(out_mp4)],
                   check=True, capture_output=True)

    # ---- the script (record your VO to these cuts) ----
    def _stamp(a, b):
        return f"[{int(a // 60)}:{int(a % 60):02d}–{int(b // 60)}:{int(b % 60):02d}]"
    rows = [f"# Reel script — ${ticker}",
            f"# Silent reel: {out_mp4.name}. {'Baked TTS VO.' if args.tts else 'No voice — record your own to these cuts.'}",
            "# Times are approximate cut points; voice to them or re-time in your editor.",
            "#",
            "# DELIVERY: read it like you're telling one trader friend about a setup —",
            "#   calm, certain, a little opinionated. NOT an announcer. Contractions, pauses,",
            "#   let the numbers land. Don't read the on-screen labels; the card shows the number,",
            "#   you say why it matters. Cut any word you wouldn't say out loud. Make it yours.",
            "",
            f"{_stamp(0, cov_dur)}  COVER   (title card: {ticker} logo + name + the 3 facts — \"${ticker} · {sub}\")",
            f"  VO: {hook_text}", ""]
    t0 = cov_dur
    if comp_seg is not None:  # leads the body — "relative strength" shown as two lines
        rows += [f"{_stamp(t0, t0 + cmp_dur)}  VS THE MARKET  ({ticker} vs the S&P 500 — this IS 'relative strength', no jargon)",
                 f"  VO: {bvo}", ""]
        t0 += cmp_dur
    for i, s in enumerate(scenes):
        a, b = t0, t0 + effs[i]
        rows += [f"{_stamp(a, b)}  {s.get('name', 'SCENE')}", f"  VO: {s['vo']}", ""]
        t0 = b
    rows.append(f"Total ≈ {t0:.0f}s")
    script_path = d / "script.txt"
    script_path.write_text("\n".join(rows))

    mode = "with TTS voice" if args.tts else "SILENT — record your own voice"
    bg = " · clean cover + intro_cards.mov overlay" if GS else ""
    print(f"\nreel: {out_mp4}  ({br.probe_dur(out_mp4):.1f}s, cover + {len(scenes)} scenes, {mode}{bg})")
    print(f"script: {script_path}")
    if GS and overlay_path is not None:
        print(f"intro overlay: {overlay_path}  (transparent {overlay_codec}, "
              f"the 3 fact cards animating — drop over your talking-head intro)")


if __name__ == "__main__":
    main()
