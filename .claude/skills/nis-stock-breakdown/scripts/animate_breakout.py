#!/usr/bin/env python3
"""
animate_breakout.py — animate how the NIS-momentum breakout *should* form to be
validated, for one ticker.

It takes the real recent candles + the derived setup levels (pivot / stop /
target), then projects the **ideal validated breakout**: a tight coil under the
pivot, a breakout bar that closes above the pivot on a volume surge, and
follow-through toward the 2R target. Each projected candle is animated forming
bar-by-bar, with a live validation badge that flips to CONFIRMED the moment the
validation rule is met:

    VALIDATION = a daily close ABOVE the pivot with volume >= 1.5x the 50-day avg

(the same close-above-pivot + volume-surge rule the agent's breakout band uses).

Outputs under <out-dir> (default code/analytics/output/setups/<TICKER>/):
  • breakout.mp4   — 1080x1350, ~6s
  • breakout.gif   — looping, for chat/preview

Run from code/analytics with its venv:
  cd code/analytics
  .venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/animate_breakout.py \
      --ticker ENVA
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

# Reuse the chart script's data path + setup derivation (its import sets up
# sys.path to code/analytics and loads APIKEY from .env).
_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import build_setup_chart as bsc  # noqa: E402

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle, FancyBboxPatch  # noqa: E402

# brand midnight theme
BG = "#0A0E1A"; PANEL = "#0F1626"; INK = "#F5F7FF"; MUT = "#9AA3BC"; MUT2 = "#6B7488"
AMBER = "#F5A623"; POS = "#3DD68C"; NEG = "#FF6B6B"; GRID = "#1C2740"
W, H, FPS = 1080, 1350, 30
VOL_MULT = 1.5  # validation: breakout volume must be >= 1.5x the 50d average


def draw_hook_viz(ax, viz, data, b, pivot):
    """The visual hook, built on the SAME standout fact. Draws in the band
    y∈[~0.25, 0.41] (axes coords). `b` is reveal progress 0→1."""
    b = max(0.0, min(1.0, b))
    y0, BH = 0.255, 0.15

    def bar(x, w, h, color):
        ax.add_patch(Rectangle((x - w / 2, y0), w, max(h, 0.001), facecolor=color, edgecolor="none"))

    if viz == "surprise" and data:
        act = float(data.get("actual") or 0); est = float(data.get("est") or 0)
        m = max(act, est, 1e-6)
        bar(0.60, 0.12, (est / m) * BH * b, MUT2)
        bar(0.80, 0.12, (act / m) * BH * b, AMBER)
        ax.text(0.60, y0 - 0.03, "estimate", color=MUT, fontsize=16, ha="center", va="top")
        ax.text(0.80, y0 - 0.03, "actual", color=AMBER, fontsize=16, ha="center", va="top", fontweight="bold")
        if b > 0.55:  # arrow showing the beat gap
            ax.annotate("", xy=(0.80, y0 + (act / m) * BH), xytext=(0.80, y0 + (est / m) * BH),
                        arrowprops=dict(arrowstyle="-|>", color=POS, lw=2.5))
    elif viz == "turnaround" and data:
        est = float(data.get("est") or 0); act = float(data.get("actual") or 0)
        zero = y0 + 0.05; m = max(abs(est), abs(act), 1e-6)
        eh = (abs(est) / m) * 0.045 * b; ah = (abs(act) / m) * 0.095 * b
        ax.add_patch(Rectangle((0.60 - 0.06, zero - eh), 0.12, eh, facecolor=NEG, edgecolor="none"))
        ax.add_patch(Rectangle((0.80 - 0.06, zero), 0.12, ah, facecolor=POS, edgecolor="none"))
        ax.plot([0.50, 0.92], [zero, zero], color=MUT2, lw=1.5)
        ax.text(0.60, zero - eh - 0.015, "expected", color=NEG, fontsize=15, ha="center", va="top")
        ax.text(0.80, zero + ah + 0.012, "actual", color=POS, fontsize=15, ha="center", va="bottom", fontweight="bold")
    elif viz == "updown":
        udr = float(data or 1.0)
        bar(0.60, 0.12, BH * b, POS)
        bar(0.80, 0.12, (1.0 / max(udr, 1.0)) * BH * b, NEG)
        ax.text(0.60, y0 - 0.03, "up-day vol", color=POS, fontsize=16, ha="center", va="top", fontweight="bold")
        ax.text(0.80, y0 - 0.03, "down-day vol", color=NEG, fontsize=16, ha="center", va="top")
    elif viz == "streak":
        n_total = int(data or 0); n = min(n_total, 9); gap, start = 0.05, 0.52
        for i in range(n):
            bb = max(0.0, min(1.0, b * n - i))
            bar(start + i * gap, 0.03, 0.10 * bb, POS)
        if n_total > n and b > 0.8:
            ax.text(start + n * gap + 0.005, y0 + 0.05, f"+{n_total - n}", color=MUT, fontsize=16, va="center")
    elif viz == "rank":
        rsv = float(data or 50); tx0, tx1, ty = 0.52, 0.90, y0 + 0.06
        ax.plot([tx0, tx1], [ty, ty], color="#27324A", lw=3, solid_capstyle="round")
        ax.plot([tx0 + (1 - rsv / 99.0) * (tx1 - tx0)], [ty], marker="o", color=AMBER, ms=max(2, 16 * b))
        ax.text(tx0, ty - 0.04, "99", color=MUT2, fontsize=14, ha="left", va="top")
        ax.text(tx1, ty - 0.04, "1", color=MUT2, fontsize=14, ha="right", va="top")
    elif viz == "rsline":
        xs = [0.52, 0.60, 0.68, 0.76, 0.84, 0.90]
        ys = [y0 + 0.02, y0 + 0.05, y0 + 0.035, y0 + 0.085, y0 + 0.07, y0 + 0.13]
        ax.plot([0.50, 0.92], [y0 + 0.10, y0 + 0.10], color="#27324A", lw=1.5, ls=(0, (5, 4)))
        k = max(2, int(round(len(xs) * b)))
        ax.plot(xs[:k], ys[:k], color=POS, lw=3, solid_capstyle="round")
        if b > 0.9:
            ax.plot([xs[-1]], [ys[-1]], marker="*", color=AMBER, ms=22)
    elif viz == "coil":
        xs = [0.52, 0.62, 0.72, 0.82, 0.90]; ys = [y0 + 0.03, y0 + 0.05, y0 + 0.07, y0 + 0.09, y0 + 0.115]
        k = max(2, int(round(len(xs) * b)))
        ax.plot(xs[:k], ys[:k], color=POS, lw=3, solid_capstyle="round")
        for i, xx in enumerate([0.55, 0.66, 0.77, 0.88]):
            bar(xx, 0.045, (0.06 - 0.012 * i) * b, "#27324A")
    else:  # breakout — the original pivot + real/fake candle tease
        x1 = 0.08 + b * 0.84
        ax.plot([0.08, x1], [y0 + 0.07, y0 + 0.07], color=AMBER, lw=2.4, ls=(0, (6, 5)))
        ax.text(0.08, y0 + 0.085, f"PIVOT  ${pivot:,.2f}", color=AMBER, fontsize=17, fontweight="bold")
        mini_candle(ax, 0.66, y0 + 0.07 + 0.06 * b, 0.05, 0.13 * b, up=True)
        mini_candle(ax, 0.86, y0 + 0.07 - 0.06 * b, 0.05, 0.13 * b, up=False)


standout = bsc.standout  # shared picker (lives in build_setup_chart) — keeps the
# animation's visual hook and the reel's verbal hook revealing the SAME fact.


def load(ticker: str, lookback_days: int = 420):
    """Real OHLCV tail + trade setup for a ticker (mirrors build_setup_chart)."""
    enddate = date.today()
    startdate = enddate - timedelta(days=lookback_days)
    t = bsc.technical()
    # RS is universe-relative; standalone we can't compute it, so we stub df_rs only
    # to let the trend template run. The animation never has a real universe rank.
    t.df_rs = pd.DataFrame([{"symbol": ticker, "RS": 0.0, "RS_Rank": 0}])
    data, tt, error = t.get_screening(ticker, startdate.isoformat(), enddate.isoformat())
    if error or tt is None or data is None:
        sys.exit(f"screening failed for {ticker} (check APIKEY / ticker)")
    # Null the stubbed rank (mirror build_setup_chart) so standout() never reads the
    # meaningless 0 as a real "rank 0 — top of the market" hook.
    tt["RS_Rank"] = None
    tt["RSOver70"] = None
    full = data if "date" in data.columns else data.reset_index()
    close = float(full["close"].iloc[-1])
    sma50 = float(full["SMA50"].iloc[-1])
    setup = bsc.derive_trade_setup(tt, close, sma50)
    return full, tt, setup


def project(setup: dict, avg_vol: float, adr_pct: float, mode: str = "validated"):
    """Projected path relative to the pivot so it works for any ticker.

    Returns ``(bars, info)``. ``info`` carries the event index and the mode so the
    renderer can colour the action and drive the validation badge.

    - ``validated``: coil under the pivot → breakout bar closing above it on a
      ~1.9x volume surge → follow-through to the 2R target.
    - ``fake`` (anti-pattern): coil → a bar that POKES above the pivot intraday but
      closes back UNDER it on light (<avg) volume → reversal that loses the pivot
      and breaks the stop. The bull trap.
    """
    p = setup["buy_point_pivot"]; tgt = setup["target_2r"]; stop = setup["stop"]
    rng = max(adr_pct, 2.5) / 100.0  # typical bar half-range as a fraction
    def bar(o, c, vmult, hi_extra=0.6, lo_extra=0.6, hi=None, lo=None):
        hh = hi if hi is not None else max(o, c) * (1 + rng * hi_extra)
        ll = lo if lo is not None else min(o, c) * (1 - rng * lo_extra)
        return {"open": o, "close": c, "high": hh, "low": ll, "vol": avg_vol * vmult}
    if mode == "fake":
        bars = [
            bar(p * 0.985, p * 0.990, 0.7),                              # coil 1
            bar(p * 0.990, p * 0.994, 0.6),                              # coil 2
            bar(p * 0.996, p * 0.997, 0.7, hi=p * 1.022),                # TRAP: pokes >pivot, closes back under, light vol
            bar(p * 0.997, p * 0.972, 1.3),                              # reversal (distribution)
            bar(p * 0.972, p * 0.945, 1.4),                              # back below the buy range
            bar(p * 0.945, stop * 0.992, 1.5, lo_extra=0.9),             # stop blown — invalidated
        ]
        return bars, {"mode": "fake", "event_idx": 2}
    bars = [
        bar(p * 0.985, p * 0.990, 0.7),                 # coil 1 (drying volume)
        bar(p * 0.990, p * 0.994, 0.6),                 # coil 2 (tightening)
        bar(p * 0.996, p * 1.018, 1.9, hi_extra=0.4),   # BREAKOUT — close > pivot, surge
        bar(p * 1.018, p * 1.040, 1.4),                 # follow-through
        bar(p * 1.040, p * 1.062, 1.2),                 # follow-through
        bar(p * 1.062, tgt * 0.999, 1.3, hi_extra=0.3), # tag the 2R target
    ]
    return bars, {"mode": "validated", "event_idx": 2}


def draw_candle(ax, x, o, c, h, l, color, width=0.62, alpha=1.0):
    ax.plot([x, x], [l, h], color=color, lw=1.6, alpha=alpha, solid_capstyle="round")
    lo, ht = min(o, c), abs(c - o) or 1e-6
    ax.add_patch(Rectangle((x - width / 2, lo), width, ht, facecolor=color,
                           edgecolor=color, lw=0.5, alpha=alpha))


def _ease(p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3  # ease-out cubic


def mini_candle(ax, cx, cy, w, h, up):
    col = POS if up else NEG
    ax.plot([cx, cx], [cy - h * 0.85, cy + h * 0.85], color=col, lw=3, solid_capstyle="round")
    ax.add_patch(Rectangle((cx - w / 2, cy - h * 0.45), w, h * 0.9, facecolor=col, edgecolor=col))


def card_axes(fig):
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.set_facecolor(BG)
    return ax


def main() -> None:
    ap = argparse.ArgumentParser(description="Animate the NIS breakout — validated vs. the fake-out trap.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--tail", type=int, default=22, help="Real bars of context shown.")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--mode", choices=["combo", "validated", "fake"], default="combo",
                    help="combo = hook + real breakout + fake breakout in one MP4 (default).")
    ap.add_argument("--gif", action="store_true", default=True)
    args = ap.parse_args()

    ticker = args.ticker.upper().strip()
    full, tt, setup = load(ticker)
    avg_vol = float(full["volume"].tail(50).mean())
    adr = float(tt.get("adr_pct") or 5.0)

    tail = full.tail(args.tail).reset_index(drop=True)
    real = [
        {"open": float(r.open), "close": float(r.close), "high": float(r.high),
         "low": float(r.low), "vol": float(r.volume)}
        for r in tail.itertuples()
    ]
    n_real = len(real)
    pivot = setup["buy_point_pivot"]; stop = setup["stop"]; target = setup["target_2r"]
    price = float(full["close"].iloc[-1])
    ext = tt.get("extension_pct")          # % from pivot (negative = below)
    hook_volx = tt.get("vol_ratio_today")  # today's volume vs 50d avg
    hook_udr = tt.get("up_down_vol_ratio")  # up/down volume = the accumulation tell

    # The weirdly-specific hook fact — prefer fundamentals already in setup.json.
    fund = {}
    out_dir_guess = pathlib.Path(args.out_dir) if args.out_dir else bsc.ANALYTICS_DIR / "output" / "setups" / ticker
    sjp = out_dir_guess / "setup.json"
    if sjp.exists():
        try:
            fund = json.loads(sjp.read_text()).get("fundamentals") or {}
        except Exception:
            fund = {}
    if not fund:
        fund = bsc.fetch_fundamentals(ticker)
    hook_lead, hook_l1, hook_l2, hook_viz, hook_data = standout(tt, fund)

    proj_v, info_v = project(setup, avg_vol, adr, "validated")
    proj_f, info_f = project(setup, avg_vol, adr, "fake")
    br_close = proj_v[info_v["event_idx"]]["close"]
    br_volx = proj_v[info_v["event_idx"]]["vol"] / avg_vol
    trap_volx = proj_f[info_f["event_idx"]]["vol"] / avg_vol

    dpi = 100
    figsize = (W / dpi, H / dpi)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"breakout_{ticker}_"))
    n = [0]

    def emit(fig):
        fig.savefig(tmp / f"f{n[0]:05d}.png", facecolor=BG)
        plt.close(fig)
        n[0] += 1

    # ---- the chart segment (validated or fake) ----------------------------
    def chart_fig(proj, info, formed, g):
        mode = info["mode"]; ev = info["event_idx"]; n_proj = len(proj)
        lows = [b["low"] for b in real + proj] + [stop]
        highs = [b["high"] for b in real + proj] + [target]
        ylo, yhi = min(lows), max(highs); pad = (yhi - ylo) * 0.06
        ylo, yhi = ylo - pad, yhi + pad
        vmax = max(b["vol"] for b in real + proj) * 1.15

        fig, (axp, axv) = plt.subplots(
            2, 1, figsize=figsize, dpi=dpi, gridspec_kw={"height_ratios": [3.1, 1]})
        fig.patch.set_facecolor(BG)
        for ax in (axp, axv):
            ax.set_facecolor(BG)
            for sp in ax.spines.values():
                sp.set_visible(False)
            ax.tick_params(colors=MUT2, labelsize=11); ax.margins(x=0.01)
        fig.subplots_adjust(left=0.07, right=0.95, top=0.84, bottom=0.07, hspace=0.12)

        for i, b in enumerate(real):
            col = POS if b["close"] >= b["open"] else NEG
            draw_candle(axp, i, b["open"], b["close"], b["high"], b["low"], col, alpha=0.45)
            axv.bar(i, b["vol"], width=0.62, color=col, alpha=0.35)

        cur_close = cur_high = cur_vol = None
        for j in range(formed):
            b = proj[j]; x = n_real + j
            surge = b["vol"] >= VOL_MULT * avg_vol
            col = AMBER if (mode == "validated" and j == ev and surge) else (POS if b["close"] >= b["open"] else NEG)
            draw_candle(axp, x, b["open"], b["close"], b["high"], b["low"], col)
            axv.bar(x, b["vol"], width=0.62, color=col)
        if g > 0 and formed < n_proj:
            b = proj[formed]; x = n_real + formed; o = b["open"]
            cur_close = o + (b["close"] - o) * g
            cur_high = o + (b["high"] - o) * g
            cur_low = o + (b["low"] - o) * g
            cur_vol = b["vol"] * g
            surge_now = cur_vol >= VOL_MULT * avg_vol
            col = AMBER if (mode == "validated" and formed == ev and surge_now) else (POS if cur_close >= o else NEG)
            draw_candle(axp, x, o, cur_close, cur_high, cur_low, col)
            axv.bar(x, cur_vol, width=0.62, color=col)

        xspan = (-0.6, n_real + n_proj - 0.4)
        axp.set_xlim(*xspan); axp.set_ylim(ylo, yhi)
        axv.set_xlim(*xspan); axv.set_ylim(0, vmax)
        axv.axhline(VOL_MULT * avg_vol, color=AMBER, lw=1.2, ls=(0, (2, 4)), alpha=0.7)
        axv.text(xspan[0] + 0.2, VOL_MULT * avg_vol, f"  {VOL_MULT:g}× avg vol",
                 color=AMBER, fontsize=11, va="bottom", alpha=0.9)
        for y, col, lab in [(target, POS, f"TARGET  ${target:,.2f}"),
                            (pivot, AMBER, f"PIVOT  ${pivot:,.2f}"),
                            (stop, NEG, f"STOP  ${stop:,.2f}")]:
            axp.axhline(y, color=col, lw=1.4, ls="-" if col == AMBER else "--", alpha=0.85)
            axp.text(xspan[0] + 0.2, y, f"{lab}", color=col, fontsize=13, fontweight="bold",
                     va="bottom", ha="left")
        axp.axhspan(pivot, pivot * 1.05, color=AMBER, alpha=0.06)
        axp.set_xticks([]); axv.set_xticks([])
        axp.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
        axv.set_yticks([])

        sub = ("Validation = a daily close above the pivot, on volume ≥ 1.5× the 50-day average."
               if mode == "validated" else
               "No volume = no validation. It pokes above the pivot, closes back under, and fails.")
        title2 = "·  How the breakout validates" if mode == "validated" else "·  Anti-pattern: the fake-out"
        fig.text(0.07, 0.945, f"{ticker}", color=INK, fontsize=34, fontweight="bold")
        fig.text(0.205, 0.945, title2, color=MUT, fontsize=20, fontweight="bold", va="baseline")
        fig.text(0.07, 0.905, sub, color=MUT, fontsize=13.5)

        # badge state machine
        if mode == "validated":
            confirmed = (formed > ev) or (formed == ev and cur_close is not None
                                          and cur_close > pivot and (cur_vol or 0) >= VOL_MULT * avg_vol)
            if confirmed:
                txt, bc, filled = (f"BREAKOUT CONFIRMED   ·   close ${br_close:,.2f} > pivot on {br_volx:.1f}× volume", POS, True)
            else:
                txt, bc, filled = (f"WAITING   ·   needs close > ${pivot:,.2f}  +  ≥{VOL_MULT:g}× volume", AMBER, False)
        else:
            failed = any(j > ev and proj[j]["close"] < stop for j in range(formed))
            if cur_close is not None and formed > ev and cur_close < stop:
                failed = True
            trap_done = formed > ev
            poking = (formed == ev and cur_high is not None and cur_high > pivot)
            if failed:
                txt, bc, filled = (f"FAILED   ·   stop ${stop:,.2f} hit — setup invalidated", NEG, True)
            elif trap_done or poking:
                txt, bc, filled = (f"FAKE BREAKOUT   ·   poked above ${pivot:,.2f} on {trap_volx:.1f}× volume, closed back under", NEG, False)
            else:
                txt, bc, filled = (f"WAITING   ·   needs close > ${pivot:,.2f}  +  ≥{VOL_MULT:g}× volume", AMBER, False)
        fig.text(0.5, 0.025, txt, color="#0A0E1A" if filled else bc, fontsize=14.5,
                 fontweight="bold", ha="center", va="center",
                 bbox=dict(boxstyle="round,pad=0.6", fc=bc if filled else "none", ec=bc, lw=2))
        return fig

    def emit_sequence(proj, info):
        ev = info["event_idx"]; n_proj = len(proj)
        sched: list[tuple[int, float]] = [(0, 0.0)] * 8
        for j in range(n_proj):
            steps = 12 if j == ev else 8
            for s in range(steps):
                sched.append((j, (s + 1) / steps))
            sched.extend([(j + 1, 0.0)] * (20 if j == ev else 5))
        sched += [(n_proj, 0.0)] * 20
        for formed, g in sched:
            emit(chart_fig(proj, info, formed, g))

    # ---- title / section / outro cards ------------------------------------
    def hook_fig(p):
        """Opening hook — the SPECIFIC ticker case: ticker, where it sits vs the
        pivot, and the real-or-fake question, teased with two candles."""
        e = _ease(p); a = e; dy = (1 - e) * 0.03
        fig = plt.figure(figsize=figsize, dpi=dpi); fig.patch.set_facecolor(BG)
        ax = card_axes(fig)
        ax.text(0.08, 0.905, "NIS MOMENTUM · SWING SETUP", color=AMBER, fontsize=19,
                fontweight="bold", alpha=a)
        # the specific ticker + its situation
        ax.text(0.08, 0.81, ticker, color=INK, fontsize=92, fontweight="bold", va="center", alpha=a)
        where = f"${price:,.2f}"
        if ext is not None:
            loc = ("at the pivot" if abs(ext) < 1
                   else f"{abs(ext):.0f}% under the pivot" if ext < 0
                   else f"{abs(ext):.0f}% over the pivot")
            where += f"  ·  {loc}"
        # volume tell: today's surge if there is one, else the up/down accumulation ratio
        if hook_volx and hook_volx >= 1.2:
            where += f"  ·  {hook_volx:.1f}× vol"
        elif hook_udr and hook_udr >= 1.25:
            where += f"  ·  {hook_udr:.1f}× up/down vol"
        ax.text(0.085, 0.745, where, color=MUT, fontsize=24, va="center", alpha=a)
        # curiosity lead-in — frames the fact as something they missed
        ax.text(0.08, 0.66, hook_lead, color=AMBER, fontsize=20, fontweight="bold", alpha=a)
        # the weirdly-specific fact (line2 carries the number, in amber); auto-size to fit
        hfs = max(34, min(56, int(1080 / max(len(hook_l1), len(hook_l2), 1))))
        ax.text(0.08, 0.59 - dy, hook_l1, color=INK, fontsize=hfs, fontweight="bold", alpha=a)
        ax.text(0.08, 0.505 - dy, hook_l2, color=AMBER, fontsize=hfs, fontweight="bold", alpha=a)
        # the visual hook, built on the SAME fact
        draw_hook_viz(ax, hook_viz, hook_data, _ease((p - 0.45) / 0.55) if p > 0.45 else 0.0, pivot)
        ax.text(0.08, 0.15, "Breakout, or fake-out? Volume decides.", color=INK,
                fontsize=23, fontweight="bold", alpha=a)
        ax.text(0.08, 0.06, "newsimpactscreener.com", color=MUT2, fontsize=18, alpha=a)
        return fig

    def section_fig(p, num, title, sub, accent):
        e = _ease(p); a = e
        fig = plt.figure(figsize=figsize, dpi=dpi); fig.patch.set_facecolor(BG)
        ax = card_axes(fig)
        ax.text(0.08, 0.52, num, color=accent, fontsize=200, fontweight="bold", alpha=0.16 * a, va="center")
        ax.plot([0.08, 0.08 + e * 0.16], [0.62, 0.62], color=accent, lw=5)
        ax.text(0.08, 0.55, title, color=accent, fontsize=58, fontweight="bold", alpha=a)
        ax.text(0.08, 0.47, sub, color=MUT, fontsize=27, alpha=a)
        return fig

    def outro_fig(p):
        e = _ease(p); a = e
        fig = plt.figure(figsize=figsize, dpi=dpi); fig.patch.set_facecolor(BG)
        ax = card_axes(fig)
        ax.text(0.08, 0.62, "Volume confirms.", color=POS, fontsize=62, fontweight="bold", alpha=a)
        ax.text(0.08, 0.53, "Or it doesn't.", color=NEG, fontsize=62, fontweight="bold", alpha=a)
        ax.text(0.08, 0.40, "The NIS Momentum board scans the market", color=MUT, fontsize=26, alpha=a)
        ax.text(0.08, 0.355, "for the real ones — every day.", color=MUT, fontsize=26, alpha=a)
        ax.add_patch(FancyBboxPatch((0.08, 0.21), 0.52, 0.07, boxstyle="round,pad=0.01",
                                    fc=AMBER, ec="none", alpha=a, mutation_aspect=0.4))
        ax.text(0.34, 0.245, "newsimpactscreener.com", color="#0A0E1A", fontsize=24,
                fontweight="bold", ha="center", va="center", alpha=a)
        ax.text(0.08, 0.12, "@newsimpactscreener · not financial advice", color=MUT2, fontsize=17, alpha=a)
        return fig

    def emit_card(secs, fn, **kw):
        total = int(secs * FPS); reveal = min(total, 14)
        for i in range(total):
            emit(fn(min(1.0, (i + 1) / reveal), **kw))

    # ---- assemble ---------------------------------------------------------
    if args.mode == "combo":
        emit_card(4.0, hook_fig)  # longer so the spoken hook has room to land
        emit_card(1.2, lambda p: section_fig(p, "1", "The real breakout", "Close above the pivot, on a volume surge.", POS))
        emit_sequence(proj_v, info_v)
        emit_card(1.4, lambda p: section_fig(p, "2", "The fake-out", "Pokes above. No volume. Fails.", NEG))
        emit_sequence(proj_f, info_f)
        emit_card(2.2, outro_fig)
        stem = "breakout_story"
    elif args.mode == "validated":
        emit_sequence(proj_v, info_v); stem = "breakout"
    else:
        emit_sequence(proj_f, info_f); stem = "fake_breakout"

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else bsc.ANALYTICS_DIR / "output" / "setups" / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / f"{stem}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"),
         "-vf", "scale=1080:1350,format=yuv420p", "-c:v", "libx264", "-crf", "20",
         str(mp4)], check=True, capture_output=True)
    outputs = [mp4]
    if args.gif:
        gif = out_dir / f"{stem}.gif"; palette = tmp / "pal.png"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"),
                        "-vf", "scale=540:675:flags=lanczos,palettegen", str(palette)],
                       check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp / "f%05d.png"),
                        "-i", str(palette), "-lavfi",
                        "scale=540:675:flags=lanczos[x];[x][1:v]paletteuse", str(gif)],
                       check=True, capture_output=True)
        outputs.append(gif)
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"frames: {n[0]} @ {FPS}fps  (~{n[0]/FPS:.1f}s)  mode={args.mode}")
    for o in outputs:
        print("wrote", o)


if __name__ == "__main__":
    main()
