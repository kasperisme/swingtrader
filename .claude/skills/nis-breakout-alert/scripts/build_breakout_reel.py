"""Breakout-roundup reel: a board of ALL live breakouts → feature the #1.

Renders a short board intro (a "N breakouts, live" count card + a ranked
leaderboard card with the most-significant ticker highlighted), then concatenates
it in front of the featured ticker's chart reel (produced separately by
nis-stock-breakdown/build_chart_reel.py). One reel per hour, the whole board in
view, the headline highlighted.

Reuses build_chart_reel's card/encoder/TTS primitives so the look + audio match.

Usage (run from code/analytics, after build_setup_chart + build_chart_reel for
the featured ticker):
    python build_breakout_reel.py --board board.json \
        --feature-reel output/setups/LQDA/reel_chart.mp4 \
        --out output/breakout_alert/reel_breakout.mp4
where board.json is the JSON printed by breakout_pick.py (action=post).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
from matplotlib.patches import Rectangle
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Reuse the sibling renderer's primitives (W/H, colours, cards, TTS, encoder).
_BCR_DIR = pathlib.Path(__file__).resolve().parents[2] / "nis-stock-breakdown" / "scripts"
sys.path.insert(0, str(_BCR_DIR))
import build_chart_reel as bcr  # noqa: E402

W, H = bcr.W, bcr.H
_BOLD_TTF = _fm.findfont(_fm.FontProperties(weight="bold"))
_REG_TTF = _fm.findfont(_fm.FontProperties(weight="normal"))
_GREEN, _AMBER = bcr._hex(bcr.POS), bcr._hex(bcr.AMBER)
_INK, _MUT = bcr._hex(bcr.INK), bcr._hex(bcr.MUT)


def _font(sz, bold=True):
    return ImageFont.truetype(_BOLD_TTF if bold else _REG_TTF, sz)


# ---------------------------------------------------------------------------
# Animated hero intro — depth via gradient vignette + parallax chips + glow.
# ---------------------------------------------------------------------------
def _radial_bg():
    """Dark navy radial vignette: brighter focal centre, edges fall to near-black."""
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    d = np.sqrt(((xx - W * 0.5) / (W * 0.82)) ** 2 + ((yy - H * 0.40) / (H * 0.52)) ** 2)
    d = np.clip(d, 0, 1) ** 1.2
    inner, outer = np.array(bcr._hex("#18243F"), float), np.array(bcr._hex("#05080E"), float)
    arr = (inner * (1 - d[..., None]) + outer * d[..., None]).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def _glow(color, w, h, rad, alpha=170):
    g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([w * 0.5 - rad, h * 0.5 - rad * 0.72,
                               w * 0.5 + rad, h * 0.5 + rad * 0.72], fill=(*color, alpha))
    return g.filter(ImageFilter.GaussianBlur(rad * 0.5))


def _area_layer(phase):
    """Faint rising market line + fill across the frame — subtle motion via phase."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    n = 60
    pts = []
    for i in range(n + 1):
        base = 0.80 - 0.32 * (i / n)  # rises left→right (uptrend)
        wig = 0.028 * np.sin(i * 0.7 + phase) + 0.018 * np.sin(i * 0.32 + phase * 1.6)
        pts.append((W * i / n, H * (base + wig)))
    d.polygon(pts + [(W, H), (0, H)], fill=(*_GREEN, 20))
    d.line(pts, fill=(*_GREEN, 64), width=3)
    return lay


# Peripheral chip slots (x, y, depth) — avoid the central number zone.
_CHIP_SLOTS = [(0.11, 0.17, 0.50), (0.84, 0.13, 0.42), (0.93, 0.33, 0.62),
               (0.07, 0.40, 0.56), (0.13, 0.66, 0.72), (0.88, 0.62, 0.66),
               (0.30, 0.80, 0.60), (0.71, 0.83, 0.52), (0.50, 0.90, 0.46)]


def _chips_layer(board, t):
    """Ticker chips at different depths drifting upward — parallax = depth."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    ticks = [b["ticker"] for b in board] or ["—"]
    for i, (fx, fy, depth) in enumerate(_CHIP_SLOTS):
        y = ((fy - t * 0.015 * depth) % 1.12) - 0.06
        size = int(20 + depth * 28)
        alpha = int(26 + depth * 74)
        d.text((fx * W, y * H), ticks[i % len(ticks)], font=_font(size, True),
               fill=(*_INK, alpha), anchor="mm")
    return lay


def render_hero_frames(frame_dir, n_frames, count_n, board, fps):
    bg = _radial_bg()
    glow = _glow(_GREEN, 980, 760, 380)
    cx, ny = int(W * 0.5), int(H * 0.40)
    for i in range(n_frames):
        t = (i + 1) / fps
        f = bg.copy()
        f.alpha_composite(_area_layer(t * 0.8))
        f.alpha_composite(_chips_layer(board, t))
        pulse = 0.72 + 0.28 * (0.5 + 0.5 * np.sin(t * 2.6))  # breathing glow
        gl = glow.copy()
        gl.putalpha(gl.split()[3].point(lambda v: int(v * pulse)))
        f.alpha_composite(gl, (cx - gl.width // 2, ny - gl.height // 2))
        d = ImageDraw.Draw(f)
        val = int(round(count_n * bcr._ease(min(1.0, t / 0.8))))  # count up 0→N
        d.text((cx, ny - 238), "●  BREAKING OUT — RIGHT NOW", font=_font(34, True),
               fill=(*_GREEN, 255), anchor="mm")
        d.text((cx, ny), str(val), font=_font(340, True), fill=(*_INK, 255), anchor="mm")
        d.text((cx, ny + 210), "stocks just cleared a key level on heavy volume",
               font=_font(29, False), fill=(*_MUT, 255), anchor="mm")
        fade = min(1.0, t / 0.35)
        if fade < 1.0:
            f = Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 255)), f, fade)
        f.convert("RGB").save(frame_dir / f"f{i:05d}.png")


def _composite_alpha(base, layer, a):
    """alpha_composite `layer` onto `base`, scaled by a∈[0,1] (for fades)."""
    if a <= 0:
        return
    if a < 1:
        r, g, b, al = layer.split()
        layer = Image.merge("RGBA", (r, g, b, al.point(lambda v: int(v * a))))
    base.alpha_composite(layer)


_TF = {"daily+1h": "daily + hourly", "daily": "daily only", "1h": "hourly only"}
_PANEL, _BORDER = bcr._hex(bcr.PANEL), bcr._hex("#222E49")
_TRACK, _MUT2 = bcr._hex("#1C2740"), bcr._hex(bcr.MUT2)
_DARK = (5, 8, 14, 255)
_ROW_Y0, _ROW_DY = 470, 210


def _board_chrome(n_total, shown):
    """Static header + column labels + footer + legend (transparent layer)."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.text((70, 150), "●  LIVE — RIGHT NOW", font=_font(28, True), fill=(*_GREEN, 255), anchor="lm")
    d.text((70, 212), "STOCKS BREAKING OUT", font=_font(60, True), fill=(*_INK, 255), anchor="lm")
    d.text((70, 268), "Just cleared a key price level on unusually high volume",
           font=_font(27, False), fill=(*_MUT, 255), anchor="lm")
    d.text((178, 340), "STOCK", font=_font(20, True), fill=(*_MUT2, 255), anchor="lm")
    d.text((640, 340), "VOLUME vs AVG", font=_font(20, True), fill=(*_MUT2, 255), anchor="mm")
    d.text((1010, 340), "TIMEFRAME", font=_font(20, True), fill=(*_MUT2, 255), anchor="rm")
    if n_total > shown:
        d.text((70, 1718), f"+{n_total - shown} more breaking out", font=_font(26, True),
               fill=(*_MUT, 255), anchor="lm")
    d.text((70, 1778), "Bar = today’s volume vs its average   ·   ranked biggest move first",
           font=_font(23, False), fill=(*_MUT2, 255), anchor="lm")
    return lay


def _row_layer(b, rank, top, maxvol):
    """One leaderboard row as a depth card on its own transparent layer."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    cy = _ROW_Y0 + rank * _ROW_DY
    tcol = _AMBER if top else _INK

    if top:
        d.rounded_rectangle([60, cy - 94, 1020, cy + 94], radius=28,
                            fill=(*_AMBER, 28), outline=(*_AMBER, 255), width=3)
        rb = "★ MOST SIGNIFICANT — FEATURED NEXT"
        rf = _font(19, True)
        rw = d.textlength(rb, font=rf)
        d.rounded_rectangle([60, cy - 96, 60 + rw + 46, cy - 60], radius=16, fill=(*_AMBER, 255))
        d.text((60 + 23 + rw / 2, cy - 78), rb, font=rf, fill=_DARK, anchor="mm")
    else:
        d.rounded_rectangle([60, cy - 82, 1020, cy + 82], radius=24,
                            fill=(*_PANEL, 160), outline=(*_BORDER, 255), width=2)

    # rank chip
    if top:
        d.ellipse([84, cy - 34, 152, cy + 34], fill=(*_AMBER, 255))
        d.text((118, cy), str(rank + 1), font=_font(34, True), fill=_DARK, anchor="mm")
    else:
        d.ellipse([88, cy - 30, 148, cy + 30], outline=(*bcr._hex("#3A496B"), 255), width=2)
        d.text((118, cy), str(rank + 1), font=_font(27, True), fill=(*_MUT, 255), anchor="mm")

    # ticker (top line) + timeframe pill (top-right)
    d.text((180, cy - 32), b["ticker"], font=_font(52 if top else 40, True),
           fill=(*tcol, 255), anchor="lm")
    tf = _TF.get(b["confirmed_on"], "")
    pf = _font(20, True)
    pw = d.textlength(tf, font=pf)
    px0, px1, py = 1000 - (pw + 34), 1000, cy - 32
    if b["confirmed_on"] == "daily+1h":
        pbg, pfg = (*_GREEN, 48), (*_GREEN, 255)
    else:
        pbg, pfg = (*bcr._hex("#2A3550"), 200), (*_MUT, 255)
    d.rounded_rectangle([px0, py - 21, px1, py + 21], radius=21, fill=pbg)
    d.text(((px0 + px1) / 2, py), tf, font=pf, fill=pfg, anchor="mm")

    # volume bar (bottom line) + ×label
    bx0, bx1, by, bh = 180, 820, cy + 38, 22
    d.rounded_rectangle([bx0, by - bh / 2, bx1, by + bh / 2], radius=bh / 2, fill=(*_TRACK, 255))
    ratio = (b["max_vol"] / maxvol) if maxvol else 0
    fillw = bx0 + max(0.07, ratio) * (bx1 - bx0)
    d.rounded_rectangle([bx0, by - bh / 2, fillw, by + bh / 2], radius=bh / 2,
                        fill=(*(_AMBER if top else _GREEN), 255))
    d.text((852, by), f"{b['max_vol']:.1f}×", font=_font(30 if top else 26, True),
           fill=(*tcol, 255), anchor="lm")
    return lay, cy


def render_board_frames(frame_dir, n_frames, board, featured, fps):
    shown = board[:6]
    maxvol = max((b["max_vol"] for b in shown), default=1.0)
    bg = _radial_bg()
    chrome = _board_chrome(len(board), len(shown))
    rows = [(*_row_layer(b, i, b["ticker"] == featured, maxvol), b["ticker"] == featured)
            for i, b in enumerate(shown)]
    glow = _glow(_AMBER, 1140, 300, 330, alpha=85)
    for fi in range(n_frames):
        t = (fi + 1) / fps
        f = bg.copy()
        for i, (lay, cy, top) in enumerate(rows):
            a = bcr._ease(min(1.0, max(0.0, (t - (0.12 + i * 0.08)) / 0.28)))  # staggered reveal
            if top:
                pulse = 0.68 + 0.32 * (0.5 + 0.5 * np.sin(t * 2.6))
                gl = glow.copy()
                gl.putalpha(gl.split()[3].point(lambda v: int(v * a * pulse)))
                f.alpha_composite(gl, (W // 2 - gl.width // 2, cy - gl.height // 2))
            _composite_alpha(f, lay, a)
        _composite_alpha(f, chrome, 1.0)
        fade = min(1.0, t / 0.3)
        if fade < 1.0:
            f = Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 255)), f, fade)
        f.convert("RGB").save(frame_dir / f"f{fi:05d}.png")


# ---------------------------------------------------------------------------
# Featured breakout — the 1-HOUR chart (the intraday move), NOT the daily
# breakdown. Focused on the level being attacked + the volume surge.
# ---------------------------------------------------------------------------
_DPI = 100


def _fetch_hourly(ticker, max_bars=56):
    """Last ~max_bars of 1-hour OHLCV from FMP (services.screener.fmp)."""
    from services.screener.fmp import fmp
    end = datetime.now().date()
    start = end - timedelta(days=22)
    df = fmp().intraday_chart("1hour", ticker, start.isoformat(), end.isoformat())
    df = df.dropna(subset=["open", "high", "low", "close", "volume"]).reset_index(drop=True)
    if len(df) < 8:
        raise RuntimeError(f"too few 1-hour bars for {ticker} ({len(df)})")
    return df.tail(max_bars).reset_index(drop=True)


class HourlyChart:
    """Animated 1-hour candlestick chart with the breakout level + volume surge."""

    def __init__(self, df, entry):
        self.o = df["open"].to_numpy(float)
        self.h = df["high"].to_numpy(float)
        self.l = df["low"].to_numpy(float)
        self.c = df["close"].to_numpy(float)
        self.v = df["volume"].to_numpy(float)
        self.N = len(self.c)
        self.entry = float(entry) if entry else float(self.h.max())
        avg = pd.Series(self.v).rolling(20, min_periods=4).mean().to_numpy()
        avg = np.nan_to_num(avg, nan=float(np.mean(self.v)))
        self.surge = self.v >= 1.4 * avg
        cross = np.where(self.h >= self.entry)[0]
        self.bk_idx = int(cross[0]) if len(cross) else None
        # S/R from intraday pivots: resistance = the level being attacked (entry);
        # support = nearest pivot-low cluster below current price.
        self.resistance = self.entry
        w = 2
        piv_lo = [i for i in range(w, self.N - w) if self.l[i] == self.l[i - w:i + w + 1].min()]
        price = float(self.c[-1])
        lows = [self.l[i] for i in piv_lo if self.l[i] < price * 0.995]
        self.support = float(max(lows)) if lows else float(self.l.min())
        self.fig = plt.figure(figsize=(W / _DPI, H / _DPI), dpi=_DPI)
        self.fig.patch.set_facecolor(bcr.BG)
        self.axp = self.fig.add_axes([0.085, 0.32, 0.88, 0.62])
        self.axv = self.fig.add_axes([0.085, 0.085, 0.88, 0.18])

    def _style(self, ax):
        ax.set_facecolor(bcr.BG)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xticks([]); ax.set_yticks([])

    def frame(self, rev, emph, sr=0.0):
        axp, axv = self.axp, self.axv
        axp.cla(); axv.cla(); self._style(axp); self._style(axv)
        o, h, l, c, v, N = self.o, self.h, self.l, self.c, self.v, self.N
        reveal = max(1e-6, min(1.0, rev) * (N - 1))
        last = int(np.floor(reveal)); frac = reveal - last
        nxt = min(last + 1, N - 1)
        cur = bcr._lerp(c[last], c[nxt], frac)
        x0, x1 = -0.8, reveal + 0.8
        lo = min(l[:last + 1].min(), cur, self.entry, self.support)
        hi = max(h[:last + 1].max(), cur, self.entry)
        span = (hi - lo) or cur * 0.02
        lo -= span * 0.06
        ylo, yhi = lo, lo + (hi + span * 0.10 - lo) / bcr.HEAD
        cw = 0.62

        if emph > 0 and self.bk_idx is not None and self.bk_idx <= last:
            axp.axvspan(self.bk_idx - 0.5, x1, color=bcr.AMBER, alpha=0.06 * emph, zorder=0)

        def candle(i, a=1.0):
            col = bcr.POS if c[i] >= o[i] else bcr.NEG
            bh = abs(c[i] - o[i]) or 1e-9
            axp.plot([i, i], [l[i], h[i]], color=col, lw=1.5, alpha=a, solid_capstyle="round")
            axp.add_patch(Rectangle((i - cw / 2, min(o[i], c[i])), cw, bh,
                                    facecolor=col, edgecolor=col, lw=0.4, alpha=a))
        for i in range(last + 1):
            candle(i)
        if frac > 1e-3 and nxt > last:
            candle(nxt, min(1.0, frac * 1.4))

        broke = self.bk_idx is not None and self.bk_idx <= last

        # ---- animated support & resistance ----
        # Each level WIPES in from the right edge, its label SLIDES in behind it,
        # and the broken resistance PULSES a glow as price tags through it.
        def level(y, color, label, prog, flash=0.0):
            if prog <= 1e-3:
                return
            p = bcr._ease(min(1.0, prog))
            xl = x1 - p * (x1 - x0)                       # the wipe
            axp.plot([xl, x1], [y, y], color=color, lw=9, alpha=(0.10 + 0.18 * flash) * p,
                     solid_capstyle="round", zorder=1)   # soft glow
            axp.plot([xl, x1], [y, y], color=color, lw=2.2, ls=(0, (7, 5)),
                     alpha=(0.85 + 0.15 * flash) * p, zorder=3)
            # label rides on the LEFT edge (right stays clear for the live price tag),
            # sliding in from off-screen-left as the line wipes.
            axp.text(x0 - (1 - p) * 1.0, y + (yhi - ylo) * 0.006, f"{label}  {y:,.2f}",
                     color=color, fontsize=15, fontweight="bold", ha="left", va="bottom",
                     alpha=p, zorder=6)

        rp = min(1.0, sr / 0.6)                            # resistance draws first…
        sp = max(0.0, (sr - 0.4) / 0.6)                    # …support follows
        flash = emph if (broke and rp >= 1.0) else 0.0
        level(self.resistance, bcr.AMBER, "RESISTANCE", rp, flash=flash)
        level(self.support, bcr.POS, "SUPPORT", sp)

        # breakout arrow at the bar that tagged resistance
        if emph > 0 and broke:
            bi = self.bk_idx
            axp.annotate("", xy=(bi, h[bi] + span * 0.03), xytext=(bi, h[bi] + span * 0.16),
                         arrowprops=dict(arrowstyle="-|>", color=bcr.AMBER, lw=2.4, alpha=emph),
                         zorder=7)

        edge = bcr.POS if cur >= c[0] else bcr.NEG
        axp.plot([reveal], [cur], "o", color=edge, ms=9, zorder=6)
        axp.text(reveal, cur + (yhi - ylo) * 0.012, f"${cur:,.2f}", color=bcr.INK,
                 fontsize=17, fontweight="bold", ha="right", va="bottom", zorder=6)
        axp.text(x0, yhi - (yhi - ylo) * 0.02, " 1-HOUR CHART", color=bcr.MUT2,
                 fontsize=14, fontweight="bold", ha="left", va="top")
        axp.set_xlim(x0, x1); axp.set_ylim(ylo, yhi)

        vmax = max(v[:last + 1].max(), 1.0) * 1.15
        for i in range(last + 1):
            col = bcr.AMBER if self.surge[i] else (bcr.POS if c[i] >= o[i] else bcr.NEG)
            axv.bar(i, v[i], width=cw, color=col)
        if frac > 1e-3 and nxt > last:
            col = bcr.AMBER if self.surge[nxt] else (bcr.POS if c[nxt] >= o[nxt] else bcr.NEG)
            axv.bar(nxt, v[nxt] * frac, width=cw, color=col, alpha=min(1.0, frac * 1.4))
        axv.text(x0, vmax * 0.86, "Volume", color=bcr.MUT2, fontsize=13, ha="left", va="center")
        axv.set_xlim(x0, x1); axv.set_ylim(0, vmax)

        self.fig.canvas.draw()
        return Image.fromarray(np.asarray(self.fig.canvas.buffer_rgba())).convert("RGBA")


def _split2(text):
    """Split a hook into two roughly-even lines for the card."""
    words = text.split()
    if len(words) < 2:
        return text, ""
    best, target = 0, len(text) / 2
    acc = 0
    for i, w in enumerate(words[:-1]):
        acc += len(w) + 1
        if abs(acc - target) < abs((acc - len(words[i + 1]) - 1) - target):
            best = i + 1
            if acc >= target:
                break
    return " ".join(words[:best]), " ".join(words[best:])


def render_feature(tmp, ticker, featured, voice, tempo, hook_text, segs):
    df = _fetch_hourly(ticker)
    entry = (featured.get("1h") or featured.get("daily") or {}).get("entry")
    volx = featured["max_vol"]
    chart = HourlyChart(df, entry)
    res, sup = chart.resistance, chart.support

    hk = hook_text or f"{ticker} just broke out — {volx:.0f} times its normal volume on the hour."
    l1, l2 = _split2(hk)
    c0, c1, c2 = tmp / "fc0.png", tmp / "fc1.png", tmp / "fc2.png"
    bcr.hook_card(c0, ticker, "● BREAKOUT — LIVE · 1-HOUR", l1, l2)
    bcr.text_card(c1, "● THE LEVELS", f"Resistance {res:,.2f}",
                  f"Support {sup:,.2f}   ·   {volx:.1f}× volume", accent=bcr.AMBER)
    bcr.cta_card(c2)

    scenes = [
        dict(vo=hk, rev=(0.0, 0.92), emph=(0, 0), sr=(0, 0), card=c0),
        dict(vo=(f"Watch the levels: resistance at {res:,.2f}, support at {sup:,.2f}. "
                 f"It's driving through on {volx:.1f} times normal volume — the trigger firing live."),
             rev=(0.92, 1.0), emph=(0, 1), sr=(0, 1), card=c1),
        dict(vo="Not financial advice. The screener that caught it — newsimpactscreener dot com.",
             rev=(1.0, 1.0), emph=(1, 1), sr=(1, 1), card=c2),
    ]
    fade = max(1, int(0.3 * bcr.FPS))
    for k, s in enumerate(scenes):
        audio = tmp / f"fvo_{k}.mp3"
        print(f"[feature {k+1}] voicing ({len(s['vo'])} chars)…", flush=True)
        bcr.br.tts(s["vo"], audio, voice)
        dur = bcr.br.probe_dur(audio) / tempo + 0.3
        nf = max(1, round(dur * bcr.FPS))
        fdir = tmp / f"feat_{k}"
        fdir.mkdir()
        card = Image.open(s["card"]).convert("RGBA")
        (r0, r1), (e0, e1), (s0, s1) = s["rev"], s["emph"], s["sr"]
        for i in range(nf):
            t = (i + 1) / nf
            frm = chart.frame(bcr._lerp(r0, r1, t), bcr._lerp(e0, e1, t), bcr._lerp(s0, s1, t))
            a = min(1.0, (i + 1) / fade)
            c = card
            if a < 1:
                rr, gg, bb, al = card.split()
                c = Image.merge("RGBA", (rr, gg, bb, al.point(lambda v: int(v * a))))
            Image.alpha_composite(frm, c).convert("RGB").save(fdir / f"f{i:05d}.png")
        seg = tmp / f"seg_f{k}.mp4"
        bcr.encode_segment(fdir, audio, seg, dur, tempo)
        segs.append(seg)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, help="JSON file from breakout_pick.py (action=post)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice-id", default=None)
    ap.add_argument("--hook-text", default=None, help="live-breakout hook for the feature scene")
    ap.add_argument("--tempo", type=float, default=1.08)
    args = ap.parse_args(argv)

    import os
    data = json.loads(pathlib.Path(args.board).read_text())
    board = data["board"]
    featured = data["featured"]
    ftick = featured["ticker"]
    n = data.get("triggered_count") or len(board)

    voice = (args.voice_id or os.environ.get("ELEVENLABS_PRIMARY_VOICE_ID")
             or os.environ.get("ELEVENLABS_VOICE_ID") or "")
    voice = voice.split("#")[0].split()[0] if voice.strip() else ""
    if not voice:
        sys.exit("no voice id — set ELEVENLABS_PRIMARY_VOICE_ID or pass --voice-id")

    dual = featured["confirmed_on"] == "daily+1h"
    fvol = featured["max_vol"]
    vo1 = (f"{n} stocks just confirmed breakouts — live, right now."
           if n > 1 else "A stock just confirmed a breakout — live, right now.")
    vo2 = ("Here's the board — every stock that just broke above its key level on "
           f"heavy volume. Leading them all: {ftick}, {fvol:.1f} times its normal volume"
           + (", confirmed on both the daily and the hourly." if dual else ".")
           + " That's the one that matters.")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="breakoutreel_"))

    # Scene 0 — animated hero intro (gradient + parallax chips + glow + count-up).
    audio0 = tmp / "bvo_0.mp3"
    print(f"[hero] voicing ({len(vo1)} chars)…", flush=True)
    bcr.br.tts(vo1, audio0, voice)
    dur0 = bcr.br.probe_dur(audio0) / args.tempo + 0.4
    fdir0 = tmp / "hero"
    fdir0.mkdir()
    render_hero_frames(fdir0, max(1, round(dur0 * bcr.FPS)), n, board, bcr.FPS)
    seg0 = tmp / "seg_b0.mp4"
    bcr.encode_segment(fdir0, audio0, seg0, dur0, args.tempo)

    # Scene 1 — animated leaderboard (depth cards + volume bars + glowing #1).
    audio1 = tmp / "bvo_1.mp3"
    print(f"[board] voicing ({len(vo2)} chars)…", flush=True)
    bcr.br.tts(vo2, audio1, voice)
    dur1 = bcr.br.probe_dur(audio1) / args.tempo + 0.4
    fdir1 = tmp / "board"
    fdir1.mkdir()
    render_board_frames(fdir1, max(1, round(dur1 * bcr.FPS)), board, ftick, bcr.FPS)
    seg1 = tmp / "seg_b1.mp4"
    bcr.encode_segment(fdir1, audio1, seg1, dur1, args.tempo)

    segs = [seg0, seg1]

    # Scenes 2-4 — the featured ticker's 1-HOUR breakout (the intraday move).
    render_feature(tmp, ftick, featured, voice, args.tempo, args.hook_text, segs)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    listf = tmp / "list.txt"
    listf.write_text("".join(f"file '{p}'\n" for p in segs))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-c", "copy", "-movflags", "+faststart", str(out)],
                   check=True, capture_output=True)
    print(f"\nbreakout reel: {out}  ({bcr.br.probe_dur(out):.1f}s, board of {n}, featured {ftick})")


if __name__ == "__main__":
    raise SystemExit(main())
