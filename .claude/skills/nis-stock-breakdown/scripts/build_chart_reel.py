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

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

# brand midnight theme (matches build_setup_chart.py output)
BG = "#0B1020"; INK = "#F5F7FF"; MUT = "#9AA3BC"; MUT2 = "#6B7488"; GRID = "#1C2740"
AMBER = "#F5A623"; POS = "#3DD68C"; NEG = "#FF6B6B"; PANEL = "#0E1426"; FUTURE = "#5B8FF9"
SMA_COL = {"SMA50": "#F5A623", "SMA150": "#5B8FF9", "SMA200": "#9D7BFF"}
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
    _panel(ax, 0.05, 0.755, 0.90, 0.19, ec="#27324A", lw=1.6)
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
    ax.text(0.40, 0.735, "newsimpactscreener.com", color="#0A0E1A", fontsize=22,
            fontweight="bold", ha="center", va="center", zorder=3)
    _save(fig, path)


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


def encode_segment(frame_dir, audio, out, dur, tempo):
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frame_dir / "f%05d.png"),
                    "-i", str(audio), "-filter_complex", f"[1:a]atempo={tempo:.3f},apad[a]",
                    "-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}", *ENC, str(out)],
                   check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Scenes + reveal schedule
# ---------------------------------------------------------------------------
def build_scenes(setup, fund, ticker, tmp, hook_text):
    t = setup["technical"]; tr = setup["trade_setup"]
    scenes = []
    lead, l1, l2, _viz, _data = bsc.standout(t, fund)
    hc = tmp / "card_hook.png"; hook_card(hc, ticker, lead, l1, l2)
    scenes.append({"vo": hook_text, "card": hc, "group": "real", "pad": 0.35, "tempo": 1.0})

    kicker = f"{ticker} · NIS MOMENTUM"
    for i, b in enumerate(br.walkthrough(setup, fund, ticker)):
        card = tmp / f"card_stat_{i:02d}.png"
        stat_card(card, b["big"], b["label"], kicker, b["color"])
        scenes.append({"vo": b["vo"], "card": card, "group": "real", "pad": 0.12})

    bc = tmp / "card_breakout.png"; breakout_card(bc, 1.9)
    pivot = br.say_price(tr["buy_point_pivot"]); tgt = br.say_price(tr["target_2r"])
    scenes.append({
        "vo": (f"Now watch the breakout. Price clears {pivot} on a volume surge, and runs "
               f"to {tgt} — two to one on your risk. That's the move."),
        "card": bc, "group": "proj", "pad": 0.4, "tempo": 1.0})

    sma50 = br.say_price(t["SMA50"]) if t.get("SMA50") else None
    inv = tmp / "card_inval.png"
    text_card(inv, "KNOW WHERE YOU'RE WRONG", "One rule.",
              (f"Loses the 50-day at {sma50} on volume — the setup is dead."
               if sma50 else "Loses the 50-day on volume — the setup is dead."), accent=NEG)
    scenes.append({
        "vo": (f"Know where you're wrong: lose the fifty-day at {sma50} on volume, and the setup is dead."
               if sma50 else "Know where you're wrong: lose the fifty-day on volume, and the setup is dead."),
        "card": inv, "group": "hold", "pad": 0.4})

    cta = tmp / "card_cta.png"; cta_card(cta)
    scenes.append({
        "vo": ("Not financial advice — education only. If you want the screener that found this, "
               "it's at news impact screener dot com."),
        "card": cta, "group": "hold", "pad": 0.4})
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
    ap = argparse.ArgumentParser(description="Full-frame expanding-chart NIS reel with floating cards.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--voice-id", default=None)
    ap.add_argument("--hook-text", default=None, help="Zone-1 verbal hook (else auto from data).")
    ap.add_argument("--display-days", type=int, default=126,
                    help="Real trading days the chart grows through (126 ≈ half a year).")
    ap.add_argument("--tempo", type=float, default=1.08)
    args = ap.parse_args()

    ticker = args.ticker.upper().strip()
    d = pathlib.Path(args.dir) if args.dir else bsc.ANALYTICS_DIR / "output" / "setups" / ticker
    setup_json = json.loads((d / "setup.json").read_text())
    voice = (args.voice_id or os.environ.get("ELEVENLABS_PRIMARY_VOICE_ID")
             or os.environ.get("ELEVENLABS_VOICE_ID") or "")
    voice = voice.split("#")[0].split()[0] if voice.strip() else ""
    if not voice:
        sys.exit("no voice id — set ELEVENLABS_PRIMARY_VOICE_ID or pass --voice-id")
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("ELEVENLABS_API_KEY not set (in env or code/analytics/.env)")

    fund = dict(setup_json.get("fundamentals") or {}) or br.fetch_fundamentals(ticker)
    fund.setdefault("company", setup_json.get("company") or ticker)

    # ONE live snapshot drives the chart, the projection, AND the narrated levels, so
    # the on-chart Entry/Stop/Target can't drift from what Hans speaks. Preserve a real
    # RS rank if setup.json carried one (ab.load can't compute a universe rank solo).
    full, tt, setup_live = ab.load(ticker)
    tech = dict(tt)
    # Carry the universe-relative fields from setup.json (build_setup_chart fetched them
    # from the latest NIS Momentum screening); ab.load can't compute them standalone, so
    # the live tt has them as None. Without this the hook misses the RS-rank number-drop.
    sj_tech = setup_json.get("technical") or {}
    for k in ("RS_Rank", "RSOver70", "rs_line_new_high"):
        if tech.get(k) is None and sj_tech.get(k) is not None:
            tech[k] = sj_tech[k]
    setup = {"technical": tech, "trade_setup": setup_live}

    series = prepare_series(full, tt, setup_live, args.display_days)
    renderer = ChartRenderer(series)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"chartreel_{ticker}_"))
    hook_text = args.hook_text or br.verbal_hook(ticker, setup["technical"], fund)
    scenes = build_scenes(setup, fund, ticker, tmp, hook_text)

    effs = []
    for i, s in enumerate(scenes):
        audio = tmp / f"vo_{i:02d}.mp3"
        print(f"[{i+1}/{len(scenes)}] voicing ({len(s['vo'])} chars)…", flush=True)
        br.tts(s["vo"], audio, voice)
        s["audio"] = audio
        effs.append(br.probe_dur(audio) / s.get("tempo", args.tempo) + s.get("pad", 0.25))

    spans = assign_reveal(scenes, series["n_real"], series["N"], effs)

    seg_paths = []
    for i, s in enumerate(scenes):
        dur = effs[i]; n_frames = max(1, round(dur * FPS))
        fdir = tmp / f"frames_{i:02d}"; fdir.mkdir()
        card = Image.open(s["card"]).convert("RGBA") if s.get("card") else None
        f0, f1 = spans[i]
        zoom_mode = {"real": "none", "proj": "ramp", "hold": "full"}[s["group"]]
        render_scene_frames(renderer, card, fdir, n_frames, f0, f1, zoom_mode)
        seg = tmp / f"seg_{i:02d}.mp4"
        encode_segment(fdir, s["audio"], seg, dur, s.get("tempo", args.tempo))
        seg_paths.append(seg)
        print(f"     → {br.probe_dur(seg):.1f}s  expand {f0:.2f}→{f1:.2f}", flush=True)

    listf = tmp / "list.txt"
    listf.write_text("".join(f"file '{p}'\n" for p in seg_paths))
    out_mp4 = d / "reel_chart.mp4"
    # +faststart moves the moov atom to the front so platforms that fetch the
    # MP4 by URL (Instagram/Meta especially) can build their container reliably.
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-c", "copy", "-movflags", "+faststart", str(out_mp4)],
                   check=True, capture_output=True)
    print(f"\nreel: {out_mp4}  ({br.probe_dur(out_mp4):.1f}s, {len(scenes)} scenes, "
          f"{series['n_real']} real + {series['N'] - series['n_real']} projected bars, voice {voice[:8]})")
    print(f"hook: \"{hook_text}\"")


if __name__ == "__main__":
    main()
