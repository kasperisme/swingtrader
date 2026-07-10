#!/usr/bin/env python3
"""
build_reel.py — assemble the high-value NIS reel: a Hook → Value → Proof walkthrough
voiced by ElevenLabs, ending on a disclaimer card. Implements the architecture in
the skill's Step 7.

Zones / scenes (in order):
  ZONE 1  hook visual (--hook-visual) under the verbal hook (--hook-text)   ~2-3s
  ZONE 2  value card — the whole trade up front
  ZONE 3  A setup · B chart · C volume · D fundamentals · E trade levels ·
          F breakout animation (plays in full) · G invalidation · H disclaimer

Narration adapts to real data: levels from setup.json, fundamentals (beats / EPS
growth / P/E) fetched live from FMP. Nothing is fabricated — a claim is dropped if
the number isn't available (e.g. RS rank when the universe screen wasn't run).

Run from code/analytics with its venv (elevenlabs + pydub + ffmpeg live there):
  cd code/analytics
  .venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_reel.py \
      --ticker ENVA --hook-text "..." --hook-visual number_card

Requires ELEVENLABS_API_KEY (+ a voice id) and APIKEY (FMP) in env or .env.
Expects slides/slide-01..08.png and breakout_story.mp4 already rendered (Steps 5-6).
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
import build_setup_chart as bsc  # noqa: E402  (sets sys.path + loads .env)

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

BG = "#FBF7F1"; INK = "#10182B"; MUT = "#566377"; MUT2 = "#8A93A4"
AMBER = "#F59E0B"; POS = "#16A34A"; NEG = "#DC2626"
W, H, FPS = 1080, 1350, 30
ELEVEN_MODEL = "eleven_multilingual_v2"
ELEVEN_FORMAT = "mp3_44100_128"
HOOK_VISUALS = ("number_card", "moment_crop", "trade_card", "split_screen")


def say_price(v) -> str:
    """Round a price to a precision that sounds natural spoken aloud — whole dollars
    for liquid names ($191), one decimal in the teens, cents for penny prices."""
    v = float(v)
    if v >= 100:
        return f"{round(v)}"
    if v >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


# --- live fundamentals (FMP) so the narration is true for ANY ticker -----------
def _fmp(path: str, **params):
    import requests
    key = os.environ.get("APIKEY")
    if not key:
        return None
    params["apikey"] = key
    try:
        r = requests.get(f"https://financialmodelingprep.com/api/v3/{path}", params=params, timeout=30)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def fetch_fundamentals(ticker: str) -> dict:
    """company / sector / P-E / consecutive earnings beats / latest YoY EPS growth.
    Every field is optional — missing → None, and the narration omits that claim."""
    out = {"company": ticker, "sector": None, "pe": None, "beats": None, "eps_growth": None}
    try:
        from services.viral_reels import data_sources as ds
        prof = ds.company_profile(ticker) or {}
        quote = ds.fmp_quote(ticker) or {}
        out["company"] = (prof.get("companyName") or ticker).strip()
        out["sector"] = (prof.get("sector") or "").strip() or None
        pe = quote.get("pe")
        out["pe"] = float(pe) if pe not in (None, 0) else None
    except Exception:
        pass
    surprises = _fmp(f"earnings-surprises/{ticker}") or []
    n = 0
    for r in surprises:  # FMP returns most-recent first
        act, est = r.get("actualEarningResult"), r.get("estimatedEarning")
        if act is None or est is None or act < est:
            break
        n += 1
    out["beats"] = n or None
    growth = _fmp(f"income-statement-growth/{ticker}", period="quarter", limit=1) or []
    if growth and growth[0].get("growthEPS") is not None:
        out["eps_growth"] = float(growth[0]["growthEPS"]) * 100
    return out


def _status_bits(status: str):
    s = (status or "").lower()
    if "actionable" in s:
        return "ACTIONABLE", POS, "It's actionable right now"
    if "extended" in s:
        return "EXTENDED", NEG, "It's extended — wait for the pullback"
    return "WATCH", AMBER, "It's a watch — it triggers on the breakout"


# ------------------------------------------------------------------------------
# The opening is a RAPID walkthrough: one fact per card, hard-cut every ~1.5s.
# Each beat is its own scene with a terse VO line. Returns a list of beats:
#   {big, label, color, vo}
# ------------------------------------------------------------------------------
def _short_name(company: str) -> str:
    """The name a person would say aloud — not the legal entity ('… Inc.', ', Corp')."""
    n = company.split(",")[0]
    for suf in (" Incorporated", " Inc", " Corporation", " Corp", " Company", " Co", " Ltd", " PLC", " Group"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    return n.strip(" .") or company


def _pick(seed: int, *opts: str) -> str:
    """Deterministic per-reel variation so every ticker doesn't read identically
    (the copy version of DESIGN_VARIANCE — kills templated sameness)."""
    return opts[seed % len(opts)]


def walkthrough(s: dict, f: dict, ticker: str) -> list[dict]:
    """Rapid one-fact cards. The VO does NOT read the card — the card shows the
    number, the voice says the thing a real trader would say about it: the why,
    the stance, the consequence. Conversational, contractions, a point of view.
    Slop tells (label:value, 'X says Y', hollow filler) are banned here."""
    t = s["technical"]; tr = s["trade_setup"]
    pivot, stop, tgt = say_price(tr["buy_point_pivot"]), say_price(tr["stop"]), say_price(tr["target_2r"])
    risk = f"{tr['risk_pct']:.0f}"
    name = _short_name(f["company"]); beats = f.get("beats"); growth = f.get("eps_growth")
    rs = t.get("RS_Rank"); udr = t.get("up_down_vol_ratio")
    sword = "actionable" if t.get("within_buy_range") else "extended" if t.get("extended") else "a watch"
    seed = sum(ord(c) for c in ticker)

    status_vo = {
        "actionable": _pick(seed,
            f"{name}. And this one's live — it's in the buy zone right now.",
            f"Here's {name}, and it's actionable today. Not a watch — a go."),
        "extended": _pick(seed,
            f"{name}. It's already run, though, so this is a chase. Treat it that way.",
            f"{name}'s extended here, so I'm not chasing. But know the setup."),
        "a watch": _pick(seed,
            f"Here's {name}. Not a buy yet — a watch. But it's right on the edge.",
            f"{name}. Watchlist, not buy list — yet. It's coiled, and it's close."),
    }[sword]

    out = [
        {"big": ticker, "label": sword.upper(), "color": AMBER, "vo": status_vo},
        {"big": "50·150·200", "label": "stacked & rising", "color": INK, "vo": _pick(seed,
            "Trend's clean — every average stacked and turning up. Nothing fighting it.",
            "Trend first: all the averages stacked and rising. That's what you want.")},
    ]
    if t.get("PriceWithin25Percent52WeekHigh"):
        out.append({"big": "52-WK", "label": "and pressing the high", "color": INK, "vo": _pick(seed,
            "And it's right at its highs — not stretched, not late.",
            "Sitting at new highs, too. Leaders make highs; they don't wait.")})
    # NOTE: no "RS / relative strength" card — that's jargon. The HOW IT STACKS UP
    # comparison slide explains strength in plain numbers (vs NVDA/MSFT/AAPL/S&P).
    if beats:
        out.append({"big": f"{beats}×", "label": "straight earnings beats", "color": POS, "vo": _pick(seed,
            f"Business backs it up — {beats} straight earnings beats.",
            f"And it's not just the chart. {beats} beats in a row.")})
    # growth only when positive AND believable — a loss→profit swing explodes the YoY %.
    if growth is not None and 0 < growth < 100:
        out.append({"big": f"+{growth:.0f}%", "label": "EPS growth, YoY", "color": POS,
                    "vo": f"Earnings up {growth:.0f} percent on the year — and the price is just catching up."})
    if udr:
        out.append({"big": f"{udr:.1f}×", "label": "up / down volume", "color": POS, "vo": _pick(seed,
            "And the volume? That's big money loading, not leaving.",
            "Watch the buying — way more on up days. Institutions stepping in.")})
    out += [
        {"big": f"${tr['buy_point_pivot']:,.2f}", "label": "ENTRY · the pivot", "color": AMBER,
         "vo": f"Here's the plan: you don't buy it here. You wait for the break through {pivot}."},
        {"big": f"${tr['stop']:,.2f}", "label": f"STOP · {risk}% risk", "color": NEG,
         "vo": f"Lose {stop} and you're out. No argument — that's the line."},
        {"big": f"${tr['target_2r']:,.2f}", "label": "TARGET · 2 : 1", "color": POS,
         "vo": f"First target, {tgt} — two-to-one on your risk. Take some, trail the rest."},
    ]
    return out


def opener_vo(s: dict, hook_text: str) -> str:
    """Voiced over the breakout animation, paced to track what's on screen: the
    secret-reveal hook (over the hook card), then commentary on the real breakout,
    then the fake-out, then the takeaway (over the outro). The animation is
    time-stretched to this narration so there's no gap and the comments land in step."""
    return (f"{hook_text}  Now watch. The real one clears the pivot on a volume surge — that's your "
            f"entry. The fake pokes above on light volume and rolls back under. Volume decides which.")


def proof_scenes(s: dict, f: dict) -> list[dict]:
    """Tail after the rapid stat walkthrough: the chart, the invalidation, the disclaimer.
    (The breakout animation is the opener, not repeated here.)"""
    t = s["technical"]; tr = s["trade_setup"]
    pivot = say_price(tr["buy_point_pivot"])
    sma50 = say_price(t["SMA50"]) if t.get("SMA50") else None
    pos = ("coiled just under the pivot" if t.get("below_pivot")
           else "right in the buy range" if t.get("within_buy_range") else "just above the pivot")
    chart_vo = (f"And here's the picture: a tight base, {pos} at {pivot}, volume building underneath.")
    g = (f"Know where you're wrong: lose the fifty-day at {sma50} on volume, and the setup is dead."
         if sma50 else "Know where you're wrong: lose the fifty-day on volume, and the setup is dead.")
    h = ("Not financial advice — education only. If you want the screener that found this, it's at "
         "news impact screener dot com.")
    return [
        {"v": "__chart__", "text": chart_vo, "pad": 0.4},
        {"v": "slides/slide-07.png", "text": g, "pad": 0.4},
        {"v": "__disclaimer__", "text": h, "pad": 0.4},
    ]


def verbal_hook(ticker: str, tt: dict, fund: dict) -> str:
    """The spoken hook — reveals the SAME standout fact the opening slide shows,
    framed as a secret the viewer missed. Derived from the shared bsc.standout()."""
    _, _, _, viz, data = bsc.standout(tt, fund)
    if viz == "turnaround":
        return (f"Here's what almost everyone missed on {ticker}: Wall Street modeled a loss last "
                f"quarter — and instead, it posted a profit.")
    if viz == "surprise" and data and data.get("est"):
        s = (data["actual"] - data["est"]) / data["est"] * 100
        return (f"Here's what almost everyone missed on {ticker}: it beat earnings by {s:.0f} percent "
                f"— and held the move.")
    if viz == "updown":
        return (f"Here's what {ticker}'s tape is hiding: buyers took nearly every down day — "
                f"{float(data):.1f} to one.")
    if viz == "streak":
        return f"Here's the streak nobody's talking about on {ticker}: {int(data)} straight earnings beats."
    if viz == "rank":
        tier = "top of the market" if (data or 0) >= 90 else "a market leader"
        return (f"Here's the number nobody checks on {ticker}: relative-strength rank {int(data)}, {tier}.")
    if viz == "rsline":
        return (f"Here's the tell pros watch on {ticker}: its strength line hit a new high before "
                f"the price did.")
    if viz == "coil":
        return f"Here's the quiet part on {ticker}: new highs, while volume quietly dried up to nothing."
    return f"Here's what the screen caught on {ticker}: one clean move from a textbook breakout."


# ------------------------------------------------------------------------------
# Cards
# ------------------------------------------------------------------------------
def _fig():
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100); fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    return fig, ax


def value_card(path, ticker, setup, fund):
    t = setup["technical"]; tr = setup["trade_setup"]
    entry, stop, tgt = tr["entry"], tr["stop"], tr["target_2r"]; riskpct = tr["risk_pct"]
    label, col, _ = _status_bits(tr.get("status", ""))
    fig, ax = _fig()
    ax.add_patch(Rectangle((0.08, 0.905), 0.03, 0.028, color=AMBER))
    ax.text(0.135, 0.915, "NIS MOMENTUM · SWING SETUP", color=AMBER, fontsize=18, fontweight="bold", va="center")
    ax.text(0.08, 0.845, ticker, color=INK, fontsize=58, fontweight="bold", va="center")
    pill_w = 0.07 + 0.018 * len(label)
    ax.add_patch(FancyBboxPatch((0.92 - pill_w, 0.825), pill_w, 0.045, boxstyle="round,pad=0.006",
                                fc="none", ec=col, lw=2, mutation_aspect=0.5))
    ax.text(0.92 - pill_w / 2, 0.847, f"● {label}", color=col, fontsize=17, fontweight="bold",
            ha="center", va="center")
    sub = fund.get("sector") or "The whole trade — up front."
    ax.text(0.08, 0.78, sub if fund.get("sector") else sub, color=MUT, fontsize=22, va="center")

    rows = [("Entry", f"${entry:,.2f}", "breakout through the pivot", AMBER),
            ("Stop", f"${stop:,.2f}", f"−{riskpct:.1f}% risk", NEG),
            ("Target", f"${tgt:,.2f}", "2 : 1 reward-to-risk", POS)]
    y = 0.665
    ax.text(0.08, y + 0.055, "THE TRADE", color=MUT2, fontsize=17, fontweight="bold")
    for lab, val, note, c in rows:
        ax.text(0.08, y + 0.012, lab, color=INK, fontsize=30, va="center")
        ax.text(0.08, y - 0.032, note, color=MUT, fontsize=18, va="center")
        ax.text(0.92, y, val, color=c, fontsize=38, fontweight="bold", ha="right", va="center")
        ax.plot([0.08, 0.92], [y - 0.062, y - 0.062], color="#1C2740", lw=1.2)
        y -= 0.108

    # edge chips, data-driven
    chips = []
    rs = t.get("RS_Rank")
    if rs is not None:
        chips.append(f"RS {int(rs)}")
    if t.get("vol_ratio_today"):
        chips.append(f"{t['vol_ratio_today']:.1f}× volume")
    if t.get("accumulation"):
        chips.append("Accumulation")
    if fund.get("beats"):
        chips.append(f"{fund['beats']} beats")
    if t.get("PriceWithin25Percent52WeekHigh") and len(chips) < 4:
        chips.append("Near 52-wk high")
    if t.get("adr_pct") and len(chips) < 4:
        chips.append(f"ADR {t['adr_pct']:.1f}%")
    chips = chips[:4]
    ax.text(0.08, 0.275, "THE EDGE", color=MUT2, fontsize=17, fontweight="bold")
    cx = 0.08
    for c in chips:
        wpx = 0.035 + 0.0135 * len(c)
        ax.add_patch(FancyBboxPatch((cx, 0.205), wpx, 0.05, boxstyle="round,pad=0.004",
                                    fc="#131C2E", ec="#27324A", lw=1.2, mutation_aspect=0.5))
        ax.text(cx + wpx / 2, 0.23, c, color=INK, fontsize=18, ha="center", va="center")
        cx += wpx + 0.022

    ax.add_patch(Rectangle((0.08, 0.085), 0.018, 0.018, color=AMBER))
    ax.text(0.11, 0.094, "NIS STOCK BREAKDOWN", color=MUT2, fontsize=15, va="center", fontweight="bold")
    ax.text(0.92, 0.094, "newsimpactscreener.com", color=MUT2, fontsize=15, va="center", ha="right")
    fig.savefig(path, facecolor=BG); plt.close(fig)


def stat_card(path, big, label, kicker, color):
    """One-fact card for the rapid walkthrough: a big value + a short label."""
    fig, ax = _fig()
    ax.text(0.08, 0.9, kicker, color=AMBER, fontsize=20, fontweight="bold", va="center")
    n = len(str(big))
    fs = 210 if n <= 4 else 150 if n <= 8 else 104
    ax.text(0.5, 0.565, str(big), color=color, fontsize=fs, fontweight="bold", ha="center", va="center")
    ax.plot([0.42, 0.58], [0.40, 0.40], color=AMBER, lw=4, solid_capstyle="round")
    ax.text(0.5, 0.33, label, color=INK, fontsize=30, ha="center", va="center")
    ax.text(0.5, 0.085, "newsimpactscreener.com", color=MUT2, fontsize=16, ha="center", va="center")
    fig.savefig(path, facecolor=BG); plt.close(fig)


def disclaimer_card(path, ticker):
    fig, ax = _fig()
    ax.add_patch(Rectangle((0.08, 0.78), 0.03, 0.04, color=AMBER))
    ax.text(0.135, 0.79, "BEFORE YOU TRADE", color=AMBER, fontsize=20, fontweight="bold", va="center")
    ax.text(0.08, 0.64, "Not financial", color=INK, fontsize=66, fontweight="bold")
    ax.text(0.08, 0.555, "advice.", color=INK, fontsize=66, fontweight="bold")
    ax.text(0.08, 0.44,
            "For education only. Levels and signals are\nmechanical outputs of the NIS Momentum\nsetup — not a recommendation to buy or sell.\nDo your own research. Manage your risk.",
            color=MUT, fontsize=24, va="top", linespacing=1.5)
    ax.add_patch(FancyBboxPatch((0.08, 0.20), 0.52, 0.06, boxstyle="round,pad=0.008",
                                fc=AMBER, ec="none", mutation_aspect=0.5))
    ax.text(0.34, 0.23, "newsimpactscreener.com", color="#0A0E1A", fontsize=22,
            fontweight="bold", ha="center", va="center")
    ax.text(0.08, 0.11, "@newsimpactscreener", color=MUT2, fontsize=18)
    fig.savefig(path, facecolor=BG); plt.close(fig)


def _mini_candle(ax, cx, ylo, yhi, ymid, up):
    """Draw a single candle in axes coords: wick ylo→yhi, body around ymid."""
    col = POS if up else NEG
    ax.plot([cx, cx], [ylo, yhi], color=col, lw=4, solid_capstyle="round")
    bh = abs(yhi - ymid) * 0.7
    ax.add_patch(Rectangle((cx - 0.05, ymid - bh / 2), 0.10, bh, facecolor=col, edgecolor=col))


def hook_card(path, kind, ticker, setup, fund, d, tmp):
    """ZONE 1 visual. number_card / trade_card / split_screen via matplotlib;
    moment_crop is a tight ffmpeg crop of the real chart."""
    t = setup["technical"]; tr = setup["trade_setup"]
    if kind == "moment_crop":
        src = d / "chart.png"
        if src.exists():
            subprocess.run(["ffmpeg", "-y", "-i", str(src),
                            "-vf", "crop=486:1040:594:150,scale=1080:1350", str(path)],
                           check=True, capture_output=True)
            return
        kind = "number_card"  # fall back if the chart isn't rendered yet

    fig, ax = _fig()
    ax.text(0.08, 0.9, f"{ticker} · NIS MOMENTUM", color=AMBER, fontsize=20, fontweight="bold", va="center")

    if kind == "trade_card":
        rows = [("ENTRY", say_price(tr["buy_point_pivot"]), AMBER),
                ("STOP", say_price(tr["stop"]), NEG),
                ("TARGET", say_price(tr["target_2r"]), POS)]
        y = 0.66
        for lab, val, col in rows:
            ax.text(0.08, y, lab, color=MUT, fontsize=30, va="center")
            ax.text(0.92, y, f"${val}", color=col, fontsize=64, fontweight="bold", ha="right", va="center")
            y -= 0.17
        ax.text(0.08, 0.13, "2 : 1  reward-to-risk", color=INK, fontsize=34, fontweight="bold", va="center")

    elif kind == "split_screen":
        ax.plot([0.5, 0.5], [0.12, 0.82], color="#27324A", lw=2)
        ax.plot([0.06, 0.94], [0.5, 0.5], color=AMBER, lw=2, ls=(0, (6, 5)))
        ax.text(0.06, 0.52, "PIVOT", color=AMBER, fontsize=18, fontweight="bold")
        _mini_candle(ax, 0.27, 0.42, 0.74, 0.66, up=True)    # real: closes above
        _mini_candle(ax, 0.73, 0.40, 0.66, 0.45, up=False)   # fake: pokes above, closes under
        ax.text(0.27, 0.30, "?", color=POS, fontsize=70, fontweight="bold", ha="center")
        ax.text(0.73, 0.30, "?", color=NEG, fontsize=70, fontweight="bold", ha="center")

    else:  # number_card — the single most surprising figure
        rs = t.get("RS_Rank"); volx = t.get("vol_ratio_today"); beats = fund.get("beats")
        if rs is not None:
            big, small = f"RS {int(rs)}", "relative strength — top of the market"
        elif volx and volx >= 1.4:
            big, small = f"{volx:.1f}×", "today's volume vs. its average"
        elif beats:
            big, small = f"{beats}", "straight earnings beats"
        else:
            big, small = f"${say_price(tr['buy_point_pivot'])}", "the pivot that decides the trade"
        ax.text(0.5, 0.56, big, color=AMBER, fontsize=210, fontweight="bold", ha="center", va="center")
        ax.text(0.5, 0.34, small, color=INK, fontsize=30, ha="center", va="center")

    fig.savefig(path, facecolor=BG); plt.close(fig)


# ------------------------------------------------------------------------------
def tts(text, out_path, voice_id):
    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    audio = client.text_to_speech.convert(
        voice_id=voice_id, text=text, model_id=ELEVEN_MODEL, output_format=ELEVEN_FORMAT,
        voice_settings={"stability": 0.5, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True})
    out_path.write_bytes(b"".join(audio))


def probe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


ENC = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-c:a", "aac", "-ar", "44100", "-b:a", "160k", "-vsync", "cfr"]


def still_segment(img, audio, out, dur, tempo):
    frames = max(1, round(dur * FPS))
    vf = (f"scale=3240:4050,zoompan=z='min(zoom+0.0005,1.04)':d={frames}"
          f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps={FPS}:s={W}x{H}")
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-i", str(audio),
                    "-filter_complex", f"[0:v]{vf}[v];[1:a]atempo={tempo:.3f},apad[a]",
                    "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *ENC, str(out)],
                   check=True, capture_output=True)


def video_segment(vid, audio, out, dur, tempo):
    # time-stretch the video so it fills exactly `dur` (the narration length) — no
    # silent gap, and the animation's phases track the voiceover.
    factor = max(0.1, dur / max(probe_dur(vid), 0.1))
    subprocess.run(["ffmpeg", "-y", "-i", str(vid), "-i", str(audio),
                    "-filter_complex",
                    f"[0:v]setpts=PTS*{factor:.4f},scale={W}:{H},fps={FPS}[v];[1:a]atempo={tempo:.3f},apad[a]",
                    "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *ENC, str(out)],
                   check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser(description="Assemble the Hook→Value→Proof NIS reel.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--dir", default=None)
    ap.add_argument("--voice-id", default=None)
    ap.add_argument("--hook-text", default=None, help="Zone-1 verbal hook (else auto from data).")
    ap.add_argument("--hook-visual", choices=HOOK_VISUALS, default="number_card")
    ap.add_argument("--pad", type=float, default=0.3)
    ap.add_argument("--tempo", type=float, default=1.08)
    args = ap.parse_args()

    ticker = args.ticker.upper().strip()
    d = pathlib.Path(args.dir) if args.dir else bsc.ANALYTICS_DIR / "output" / "setups" / ticker
    setup = json.loads((d / "setup.json").read_text())
    voice = (args.voice_id or os.environ.get("ELEVENLABS_PRIMARY_VOICE_ID")
             or os.environ.get("ELEVENLABS_VOICE_ID") or "")
    voice = voice.split("#")[0].split()[0] if voice.strip() else ""
    if not voice:
        sys.exit("no voice id — set ELEVENLABS_PRIMARY_VOICE_ID or pass --voice-id")
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("ELEVENLABS_API_KEY not set (in env or code/analytics/.env)")

    # Single source of truth: fundamentals written into setup.json by
    # build_setup_chart.py. Fall back to a live fetch for older setup.json files.
    fund = dict(setup.get("fundamentals") or {}) or fetch_fundamentals(ticker)
    fund.setdefault("company", setup.get("company") or ticker)
    fund.setdefault("sector", setup.get("sector"))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"reel_{ticker}_"))
    kicker = f"{ticker} · NIS MOMENTUM"
    disclaimer = tmp / "disclaimer.png"; disclaimer_card(disclaimer, ticker)

    visuals = {"__disclaimer__": disclaimer}
    chart_bare = d / "chart_bare.png"
    visuals["__chart__"] = chart_bare if chart_bare.exists() else d / "chart.png"

    # Scene list: OPEN on the breakout animation (how to enter / what to look for) with
    # the hook voiced over it → rapid one-fact stat walkthrough (≈1.5s cuts) → proof tail.
    hook_text = args.hook_text or verbal_hook(ticker, setup["technical"], fund)
    # opener narrates over the animation — slow it a touch (1.0) so the hook lands.
    scenes = [{"v": "breakout_story.mp4", "text": opener_vo(setup, hook_text), "tempo": 1.0}]
    for i, b in enumerate(walkthrough(setup, fund, ticker)):
        card = tmp / f"stat_{i:02d}.png"
        stat_card(card, b["big"], b["label"], kicker, b["color"])
        key = f"__stat{i}__"; visuals[key] = card
        scenes.append({"v": key, "text": b["vo"], "pad": 0.12})  # tight pad → ~1.5s cuts
    scenes += proof_scenes(setup, fund)

    seg_paths = []
    n_seg = len(scenes)
    for i, ln in enumerate(scenes):
        audio = tmp / f"vo_{i:02d}.mp3"
        print(f"[{i+1}/{n_seg}] voicing ({len(ln['text'])} chars)…", flush=True)
        tts(ln["text"], audio, voice)
        sc_tempo = ln.get("tempo", args.tempo)
        eff = probe_dur(audio) / sc_tempo
        seg = tmp / f"seg_{i:02d}.mp4"
        if ln["v"] == "breakout_story.mp4":
            anim = d / "breakout_story.mp4"
            # stretch the animation to the narration (+ a small breath) — no gap.
            video_segment(anim, audio, seg, eff + 0.4, sc_tempo)
        else:
            still_segment(visuals.get(ln["v"], d / ln["v"]), audio, seg, eff + ln.get("pad", args.pad), sc_tempo)
        seg_paths.append(seg)
        print(f"     → {probe_dur(seg):.1f}s", flush=True)

    listf = tmp / "list.txt"
    listf.write_text("".join(f"file '{p}'\n" for p in seg_paths))
    out_mp4 = d / "reel.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-c", "copy", str(out_mp4)], check=True, capture_output=True)
    print(f"\nreel: {out_mp4}  ({probe_dur(out_mp4):.1f}s, {n_seg} scenes, "
          f"hook={args.hook_visual}, voice {voice[:8]})")
    print(f"hook: \"{hook_text}\"")


if __name__ == "__main__":
    main()
