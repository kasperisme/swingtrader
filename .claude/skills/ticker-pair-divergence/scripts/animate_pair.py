#!/usr/bin/env python3
"""
animate_pair.py — the hero visual for a ticker-pair divergence reel.

Two normalized price lines (indexed to 100) draw left→right with each company's
LOGO riding the right end of its line. As the graph evolves the stats fill in
(correlation, cointegration p-value, half-life); when the lines pull apart the
divergence is shaded and flagged, and the mean-reversion trade setup is called
out. Opens on a non-obvious-relationship hook card, closes on the trade + CTA.

Run from code/analytics (needs pair.json from pair_data.py):
  cd code/analytics
  .venv/bin/python ../../.claude/skills/ticker-pair-divergence/scripts/animate_pair.py --pair DNUT/MCD
→ output/setups/pairs/<A>_<B>/pair_story.mp4 (+ .gif)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from datetime import date as _date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.offsetbox import OffsetImage, AnnotationBbox  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

BG = "#0A0E1A"; INK = "#F5F7FF"; MUT = "#9AA3BC"; MUT2 = "#6B7488"; GRID = "#1C2740"
AMBER = "#F5A623"; CA = "#F5A623"; CB = "#5B8FF9"; POS = "#3DD68C"; NEG = "#FF6B6B"
W, H, FPS = 1080, 1350, 30


def _ease(p):
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def _fig():
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); fig.patch.set_facecolor(BG)
    return fig


def _imread(path):
    try:
        return plt.imread(path)
    except Exception:
        return None


def _oimg(arr, zoom):  # fresh OffsetImage per frame (artists can't be reused)
    return OffsetImage(arr, zoom=zoom) if arr is not None else None


def main():
    ap = argparse.ArgumentParser(description="Animate a ticker-pair divergence line chart.")
    ap.add_argument("--pair", help="e.g. DNUT/MCD (else uses --dir)")
    ap.add_argument("--dir", default=None)
    args = ap.parse_args()

    if args.dir:
        d = pathlib.Path(args.dir)
    else:
        a, b = (args.pair or "").replace(",", "/").split("/")
        a, b = (a.upper(), b.upper()) if a.upper() < b.upper() else (b.upper(), a.upper())
        # find analytics output dir
        here = pathlib.Path(__file__).resolve()
        root = next((p for p in here.parents if (p / "code" / "analytics").exists()), None)
        base = (root / "code" / "analytics") if root else pathlib.Path.cwd()
        d = base / "output" / "setups" / "pairs" / f"{a}_{b}"
    S = json.loads((d / "pair.json").read_text())

    A, B = S["a"], S["b"]
    ser = S["series"]; st = S["stats"]; tr = S["trade"]; rel = S["relationship"]
    an, bn, z = ser["a_norm"], ser["b_norm"], ser["z"]
    n = len(an); div_idx = ser["divergence_idx"]
    ylo, yhi = min(min(an), min(bn)), max(max(an), max(bn))
    pad = (yhi - ylo) * 0.12; ylo, yhi = ylo - pad, yhi + pad
    img_a = _imread(A["logo"]) if A.get("logo") else None
    img_b = _imread(B["logo"]) if B.get("logo") else None

    # x-axis time period: ~6 month ticks across the window
    dts = [_date.fromisoformat(s) for s in ser["dates"]]
    tick_idx = sorted({int(round(i * (n - 1) / 5)) for i in range(6)})
    tick_lbl = [dts[i].strftime("%b '%y") if (j == 0 or dts[i].month == 1) else dts[i].strftime("%b")
                for j, i in enumerate(tick_idx)]
    zr = max(2.6, max(abs(v) for v in z) + 0.3); zlo, zhi = -zr, zr

    coint = (f"cointegrated · p={st['coint_pvalue']:.2f}" if st.get("is_cointegrated")
             else f"p={st['coint_pvalue']:.2f}" if st.get("coint_pvalue") is not None else "")
    hl = f"{st['half_life_days']:.0f}-day half-life" if st.get("half_life_days") else ""
    corr = f"correlation {st['correlation']:.2f}" if st.get("correlation") is not None else ""

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pair_")); frames = [0]

    def emit(fig):
        fig.savefig(tmp / f"f{frames[0]:05d}.png", facecolor=BG); plt.close(fig); frames[0] += 1

    # ---- hook card: the non-obvious relationship -------------------------
    def hook_card(p):
        e = _ease(p); fig = _fig()
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        ax.text(0.08, 0.9, "TICKER PAIRS · NIS RELATIONSHIP GRAPH", color=AMBER, fontsize=18, fontweight="bold", alpha=e)
        ax.text(0.08, 0.8, "NOBODY CONNECTS", color=MUT, fontsize=24, fontweight="bold", alpha=e)
        ax.text(0.08, 0.73, "THESE TWO.", color=INK, fontsize=58, fontweight="bold", alpha=e)
        # the two logos + tickers, side by side
        for i, (CO, arr) in enumerate([(A, img_a), (B, img_b)]):
            x = 0.26 + i * 0.42; y = 0.50
            oi = _oimg(arr, 0.42)
            if oi is not None:
                ax.add_artist(AnnotationBbox(oi, (x, y), frameon=False))
            ax.text(x, 0.36, CO["ticker"], color=INK, fontsize=40, fontweight="bold", ha="center", alpha=e)
        ax.text(0.5, 0.50, "↔", color=AMBER, fontsize=46, fontweight="bold", ha="center", va="center", alpha=e)
        ax.text(0.08, 0.25, f"On the tape, {rel['phrase']} — and the", color=MUT, fontsize=26, alpha=e)
        ax.text(0.08, 0.195, "spread between them snaps back.", color=INK, fontsize=26, fontweight="bold", alpha=e)
        ax.text(0.08, 0.07, "newsimpactscreener.com", color=MUT2, fontsize=18, alpha=e)
        return fig

    # ---- the evolving chart: prices on top, the SPREAD (σ) below ----------
    def chart_frame(frac):
        e = _ease(frac); k = max(2, int(round(e * n)))
        fig = _fig(); xs = list(range(n))

        # TOP — both prices indexed to 100 (identity + logos)
        axp = fig.add_axes([0.08, 0.44, 0.84, 0.38]); axp.set_facecolor(BG)
        for sp in axp.spines.values():
            sp.set_visible(False)
        axp.set_xlim(-1, n + 24); axp.set_ylim(ylo, yhi)
        axp.set_xticks([]); axp.tick_params(colors=MUT2, labelsize=12)
        axp.axhline(100, color=GRID, lw=1, ls=(0, (4, 5)))
        axp.plot(xs[:k], an[:k], color=CA, lw=3, solid_capstyle="round")
        axp.plot(xs[:k], bn[:k], color=CB, lw=3, solid_capstyle="round")
        for CO, arr, series, col in [(A, img_a, an, CA), (B, img_b, bn, CB)]:
            xe, ye = k - 1, series[k - 1]
            oi = _oimg(arr, 0.15)
            if oi is not None:
                axp.add_artist(AnnotationBbox(oi, (xe, ye), frameon=False, xybox=(28, 0),
                                              xycoords="data", boxcoords="offset points"))
            axp.annotate(CO["ticker"], xy=(xe, ye), xytext=(54, 0), textcoords="offset points",
                         color=col, fontsize=16, fontweight="bold", va="center")
        axp.text(-0.5, yhi, "PRICE · indexed to 100", color=MUT2, fontsize=13, fontweight="bold", va="bottom")

        # BOTTOM — the spread in sigma: the relationship made visible
        axz = fig.add_axes([0.08, 0.17, 0.84, 0.20]); axz.set_facecolor(BG)
        for sp in axz.spines.values():
            sp.set_visible(False)
        axz.set_xlim(-1, n + 24); axz.set_ylim(zlo, zhi)
        axz.tick_params(colors=MUT2, labelsize=12)
        axz.set_xticks(tick_idx); axz.set_xticklabels(tick_lbl)
        axz.set_yticks([-2, 0, 2]); axz.set_yticklabels(["−2σ", "0", "+2σ"])
        axz.axhspan(2, zhi, color=AMBER, alpha=0.10); axz.axhspan(zlo, -2, color=AMBER, alpha=0.10)
        for lv in (2, -2):
            axz.axhline(lv, color=AMBER, lw=1, ls=(0, (4, 4)), alpha=0.55)
        # the MEAN — what the spread always snaps back to (the target)
        axz.axhline(0, color=POS, lw=1.8)
        axz.annotate("MEAN", xy=(n - 1, 0), xytext=(40, 0), textcoords="offset points",
                     color=POS, fontsize=14, fontweight="bold", va="center")
        axz.plot(xs[:k], z[:k], color="#BFD4FF", lw=2.6, solid_capstyle="round")
        zc = z[k - 1]; mcol = NEG if abs(zc) >= 2 else (AMBER if abs(zc) >= 1.5 else POS)
        axz.plot([k - 1], [zc], marker="o", color=mcol, ms=11)
        axz.text(-0.5, zhi, "THE SPREAD · σ from the mean", color=MUT2, fontsize=13, fontweight="bold", va="bottom")
        if e > 0.6 and abs(zc) >= 1.4:
            axz.annotate("DIVERGENCE", xy=(k - 1, zc), xytext=(k - 6, zc - (1.0 if zc >= 0 else -1.0)),
                         color=AMBER, fontsize=18, fontweight="bold", ha="right", va="center")

        # header + stat strip
        fig.text(0.08, 0.93, f"{A['ticker']}  ↔  {B['ticker']}", color=INK, fontsize=40, fontweight="bold")
        fig.text(0.08, 0.89, f"{A['name']}  &  {B['name']}", color=MUT, fontsize=18)
        strip = []
        if e > 0.30 and coint:
            strip.append(coint)
        if e > 0.55 and hl:
            strip.append(hl)
        if e > 0.78 and rel.get("article_count"):
            strip.append(f"{rel['article_count']} news links")
        fig.text(0.08, 0.85, "   ·   ".join(strip), color=AMBER, fontsize=19, fontweight="bold")
        # trade banner once fully revealed
        if e > 0.9:
            txt = (f"SETUP {('— LIVE' if tr['actionable'] else 'FORMING')}:  Long {tr['long']}  ·  "
                   f"Short {tr['short']}   ·   {st['current_zscore']:.1f}σ apart")
            fig.text(0.5, 0.095, txt, color="#0A0E1A", fontsize=17, fontweight="bold", ha="center", va="center",
                     bbox=dict(boxstyle="round,pad=0.6", fc=AMBER, ec="none"))
        fig.text(0.08, 0.045, "newsimpactscreener.com", color=MUT2, fontsize=15)
        return fig

    def outro_card(p):
        e = _ease(p); fig = _fig()
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        ax.text(0.08, 0.88, "THE TRADE", color=AMBER, fontsize=20, fontweight="bold", alpha=e)
        ax.text(0.08, 0.76, "Bet on the snap-back.", color=INK, fontsize=52, fontweight="bold", alpha=e)
        rows = [("Long", tr["long"], POS), ("Short", tr["short"], NEG),
                ("Target", "back to the mean (0σ)", AMBER),
                ("Time", f"≈ {st['half_life_days']:.0f} days" if st.get("half_life_days") else "mean-reversion", INK)]
        y = 0.6
        for lab, val, col in rows:
            ax.text(0.08, y, lab, color=MUT, fontsize=26, alpha=e)
            ax.text(0.46, y, str(val), color=col, fontsize=30, fontweight="bold", alpha=e)
            y -= 0.1
        ax.add_patch(FancyBboxPatch((0.08, 0.12), 0.52, 0.06, boxstyle="round,pad=0.008",
                                    fc=AMBER, ec="none", mutation_aspect=0.5, alpha=e))
        ax.text(0.34, 0.15, "newsimpactscreener.com", color="#0A0E1A", fontsize=22, fontweight="bold",
                ha="center", va="center", alpha=e)
        ax.text(0.08, 0.05, "Not financial advice · education only", color=MUT2, fontsize=16, alpha=e)
        return fig

    def emit_card(secs, fn):
        total = int(secs * FPS); reveal = min(total, 14)
        for i in range(total):
            emit(fn(min(1.0, (i + 1) / reveal)))

    emit_card(4.5, hook_card)
    reveal_frames = 205
    for i in range(reveal_frames):
        emit(chart_frame((i + 1) / reveal_frames))
    for _ in range(70):  # hold on the full chart + divergence + setup
        emit(chart_frame(1.0))
    emit_card(3.6, outro_card)

    out_mp4 = d / "pair_story.mp4"
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"),
                    "-vf", "scale=1080:1350,format=yuv420p", "-c:v", "libx264", "-crf", "20", str(out_mp4)],
                   check=True, capture_output=True)
    palette = tmp / "pal.png"
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"),
                    "-vf", "scale=540:675:flags=lanczos,palettegen", str(palette)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"), "-i", str(palette),
                    "-lavfi", "scale=540:675:flags=lanczos[x];[x][1:v]paletteuse", str(d / 'pair_story.gif')],
                   check=True, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"frames: {frames[0]} @ {FPS}fps (~{frames[0]/FPS:.1f}s) → {out_mp4}")


if __name__ == "__main__":
    main()
