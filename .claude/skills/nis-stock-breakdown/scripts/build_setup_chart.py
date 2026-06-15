#!/usr/bin/env python3
"""
build_setup_chart.py — render the annotated NIS-momentum technical chart for one
ticker, and dump the data the director needs to write the carousel.

This is the missing renderer: nothing else in the repo draws a price chart with
volume *and* the swing-trade levels (pivot / buy range / entry / stop / target)
overlaid. It reuses the production screener (`services.screener.technical`) so
the SMAs, volume metrics and buy-point are computed exactly as they are in the
NIS Momentum screening, then adds the trade-setup math and the brand styling.

Outputs (under --out-dir, default ./output/setups/<TICKER>/):
  • chart.png   — 1080x1350 annotated candlestick + volume chart
  • setup.json  — every technical / fundamental / trade-setup number, so the
                  director writes slides from real values, never guesses.

Run from code/analytics with its venv (plotly + kaleido + the screener live there):
  cd code/analytics
  .venv/bin/python ../../.claude/skills/nis-stock-breakdown/scripts/build_setup_chart.py \
      --ticker NVDA --display-days 180

Requires APIKEY (FMP) in the environment or code/analytics/.env.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import date, timedelta

# --- make the analytics package importable + load APIKEY -------------------
def _find_analytics() -> pathlib.Path:
    """code/analytics holds the screener. Search CWD upward, then the repo tree
    relative to this script — so the script runs from anywhere."""
    marker = pathlib.Path("services") / "screener" / "technical.py"
    candidates = [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]
    # repo root is .../swingtrader; this file is .../swingtrader/.claude/skills/...
    for p in pathlib.Path(__file__).resolve().parents:
        candidates.append(p / "code" / "analytics")
    for c in candidates:
        if (c / marker).exists():
            return c
    sys.exit("could not locate code/analytics (services/screener/technical.py)")


ANALYTICS_DIR = _find_analytics()
sys.path.insert(0, str(ANALYTICS_DIR))

# Load APIKEY from .env if not already set (the screener reads os.environ["APIKEY"]).
if not os.environ.get("APIKEY"):
    env_file = ANALYTICS_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from services.screener.technical import technical  # noqa: E402

# --- brand theme (midnight, matches viral_reels reel/src/theme.ts) ----------
BG = "#0B1020"
GRID = "#1C2740"
TEXT = "#F5F7FF"
MUTED = "#8A93AD"
ACCENT = "#F5A623"   # amber — entry / pivot
POS = "#3DD68C"      # green — up candles / target
NEG = "#FF6B6B"      # red — down candles / stop
SMA = {"SMA50": "#F5A623", "SMA150": "#5B8FF9", "SMA200": "#9D7BFF"}

W, H = 1080, 1350


# ---------------------------------------------------------------------------
# Trade-setup derivation — the "proposed trade generated from the NIS momentum
# setup". Deterministic; see references/nis-momentum-framework.md for the rules.
# ---------------------------------------------------------------------------
def derive_trade_setup(tt: dict, close: float, sma50: float) -> dict:
    """Turn the screener's trend_template_dict (+ current close / SMA50 from the
    OHLCV frame) into entry / stop / target / R:R.

    NIS Momentum is a long trend-continuation setup, so this is long-only.
    """
    pivot = float(tt.get("pivot") or close)          # base high = O'Neil buy point
    adr = float(tt.get("adr_pct") or 5.0)            # avg daily range %, already a %
    within = bool(tt.get("within_buy_range"))
    extended = bool(tt.get("extended"))

    # Entry: in the buy range -> act at current price; below pivot -> breakout
    # entry at the pivot; extended -> wait for a pullback toward the pivot.
    if within:
        entry, status = close, "actionable — inside the buy range"
    elif extended:
        entry, status = pivot, "extended — wait for a pullback to the pivot"
    else:  # below pivot
        entry, status = pivot, "watch — triggers on a breakout through the pivot"

    # Stop: 1.5x ADR below entry, clamped to O'Neil's 4-8% max-loss band; tighten
    # to just under SMA50 when that sits inside the band (cleaner structural stop).
    risk_pct = min(max(1.5 * adr, 4.0), 8.0)
    stop = entry * (1 - risk_pct / 100.0)
    sma50_stop = sma50 * 0.99
    if entry > sma50_stop > stop:
        stop = sma50_stop
        risk_pct = (entry - stop) / entry * 100.0

    risk = entry - stop
    target_2r = entry + 2 * risk
    target_3r = entry + 3 * risk
    oneil_target = entry * 1.22  # 20-25% profit-taking zone

    return {
        "direction": "long",
        "status": status,
        "buy_point_pivot": round(pivot, 2),
        "buy_range_low": round(pivot, 2),
        "buy_range_high": round(pivot * 1.05, 2),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "risk_pct": round(risk_pct, 2),
        "risk_per_share": round(risk, 2),
        "target_2r": round(target_2r, 2),
        "target_3r": round(target_3r, 2),
        "oneil_25pct_target": round(oneil_target, 2),
        "reward_risk_to_2r": 2.0,
        "rule": "risk = 1.5x ADR, capped 4-8%; targets at 2R / 3R; trim into +20-25%.",
    }


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def build_chart(df: pd.DataFrame, tt: dict, setup: dict, ticker: str,
                *, height: int = H, bare: bool = False) -> go.Figure:
    if "date" not in df.columns:
        df = df.reset_index()
    df = df.copy()

    # Volume highlight: bars where today's volume >= 1.4x its 50d average pop in
    # amber; up days green, down days red otherwise.
    avg_vol = df["volume"].rolling(50, min_periods=10).mean()
    surge = df["volume"] >= 1.4 * avg_vol
    up = df["close"] >= df["open"]
    vol_colors = [
        ACCENT if s else (POS if u else NEG)
        for s, u in zip(surge.fillna(False), up)
    ]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.74, 0.26],
    )

    fig.add_trace(
        go.Candlestick(
            x=df["date"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=ticker,
            increasing_line_color=POS, decreasing_line_color=NEG,
            increasing_fillcolor=POS, decreasing_fillcolor=NEG,
            line=dict(width=1),
        ),
        row=1, col=1,
    )
    for key, color in SMA.items():
        if key in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df["date"], y=df[key], mode="lines", name=key,
                    line=dict(color=color, width=1.4),
                ),
                row=1, col=1,
            )

    fig.add_trace(
        go.Bar(x=df["date"], y=df["volume"], marker_color=vol_colors,
               showlegend=False, name="Volume"),
        row=2, col=1,
    )

    # --- trade-setup overlays on the price pane ---------------------------
    x0, x1 = df["date"].iloc[0], df["date"].iloc[-1]

    def hline(y, color, label, dash="solid"):
        fig.add_shape(type="line", x0=x0, x1=x1, y0=y, y1=y, xref="x", yref="y",
                      line=dict(color=color, width=1.6, dash=dash), row=1, col=1)
        fig.add_annotation(x=x1, y=y, xref="x", yref="y", text=label,
                           showarrow=False, xanchor="right", yanchor="bottom",
                           font=dict(color=color, size=22, family="Arial"),
                           bgcolor="rgba(11,16,32,0.7)", row=1, col=1)

    # buy range band
    fig.add_shape(type="rect", x0=x0, x1=x1, y0=setup["buy_range_low"],
                  y1=setup["buy_range_high"], xref="x", yref="y",
                  fillcolor="rgba(245,166,35,0.12)", line=dict(width=0), row=1, col=1)
    hline(setup["entry"], ACCENT, f"  Entry {setup['entry']}")
    hline(setup["stop"], NEG, f"  Stop {setup['stop']} ({setup['risk_pct']}%)", dash="dot")
    hline(setup["target_2r"], POS, f"  Target 2R {setup['target_2r']}", dash="dash")

    # In bare mode the slide owns the header/footer, so drop the title and tuck
    # the legend inside the plot — leaving clean top/bottom margins.
    title = None if bare else dict(
        text=(f"<b>{ticker}</b>  ·  NIS Momentum setup<br>"
              f"<span style='font-size:22px;color:{MUTED}'>"
              f"RS rank {_fmt(tt.get('RS_Rank'))} · ADR {_fmt(tt.get('adr_pct'))}% · "
              f"vol {_fmt(tt.get('vol_ratio_today'))}x avg</span>"),
        x=0.02, xanchor="left", y=0.97, font=dict(size=40),
    )
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=BG, plot_bgcolor=BG,
        width=W, height=height,
        margin=dict(l=40, r=70, t=(48 if bare else 120), b=40),
        font=dict(color=TEXT, family="Arial", size=22),
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", y=0.995, x=0.01, font=dict(size=20),
                    bgcolor="rgba(11,16,32,0.55)"),
        title=title,
        bargap=0.15,
    )
    fig.update_xaxes(gridcolor=GRID, showgrid=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    # hide weekend/holiday gaps so candles stay tight
    dt_all = pd.date_range(start=df["date"].iloc[0], end=df["date"].iloc[-1], freq="1D")
    obs = set(pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"))
    breaks = [d for d in dt_all.strftime("%Y-%m-%d") if d not in obs]
    fig.update_xaxes(rangebreaks=[dict(dvalue=86400000, values=breaks)])
    return fig


def _fmt(v):
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return str(v)


def fetch_fundamentals(ticker: str) -> dict:
    """Company / sector / P-E / consecutive earnings beats / latest YoY EPS growth /
    recent quarterly actual-vs-estimate (for the slide-5 bars), from FMP. Every field
    is optional — missing → None, so downstream copy omits the claim (no fabrication)."""
    out = {"company": ticker, "sector": None, "pe": None, "beats": None,
           "eps_growth": None, "recent": []}
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

    import requests
    key = os.environ.get("APIKEY")

    def g(path, **p):
        if not key:
            return None
        p["apikey"] = key
        try:
            r = requests.get(f"https://financialmodelingprep.com/api/v3/{path}", params=p, timeout=30)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    sur = g(f"earnings-surprises/{ticker}") or []   # most-recent first
    n = 0
    for r in sur:
        a, e = r.get("actualEarningResult"), r.get("estimatedEarning")
        if a is None or e is None or a < e:
            break
        n += 1
    out["beats"] = n or None
    recent = [{"date": r.get("date"), "actual": r.get("actualEarningResult"),
               "est": r.get("estimatedEarning")}
              for r in sur[:4] if r.get("actualEarningResult") is not None and r.get("estimatedEarning") is not None]
    out["recent"] = list(reversed(recent))  # chronological for the bar chart
    gr = g(f"income-statement-growth/{ticker}", period="quarter", limit=1) or []
    if gr and gr[0].get("growthEPS") is not None:
        out["eps_growth"] = float(gr[0]["growthEPS"]) * 100
    return out


def standout(tt: dict, fund: dict):
    """The one weird, probably-overlooked tell for THIS ticker — framed as something
    the viewer most likely missed. Leans toward signals retail doesn't track over
    obvious ones. Shared by the animation hook AND the reel voiceover so the verbal
    and visual hooks always reveal the SAME secret. Returns
    (lead, line1, line2, viz, data); line2 carries the number, viz drives the visual."""
    fund = fund or {}
    beats = fund.get("beats")
    recent = fund.get("recent") or []
    udr = tt.get("up_down_vol_ratio")
    rs = tt.get("RS_Rank")

    def surprise(rec):  # % beat, only when the estimate is a sane positive number
        a, e = rec.get("actual"), rec.get("est")
        return (a - e) / e * 100 if (a is not None and e and e > 0.05) else None

    last_s = surprise(recent[-1]) if recent else None
    max_s = max([s for s in (surprise(r) for r in recent) if s is not None], default=None)

    def best_surprise_rec():
        cand = [(surprise(r), r) for r in recent if surprise(r) is not None]
        return max(cand, key=lambda x: x[0])[1] if cand else None

    if tt.get("rs_line_new_high"):
        return ("THE TELL PROS WATCH", "Its strength line hit a", "new high before price.", "rsline", None)
    # turnaround: the Street modeled a loss and it printed a profit — overlooked & valuable
    if recent and (recent[-1].get("est") or 0) < 0 and (recent[-1].get("actual") or 0) > 0:
        return ("WHAT EVERYONE MISSED", "Wall Street modeled a loss.", "It posted a profit.", "turnaround", recent[-1])
    if last_s is not None and last_s >= 30:
        return ("WHAT EVERYONE MISSED", "It beat earnings by", f"{last_s:.0f}% — and held it.", "surprise", recent[-1])
    if udr and udr >= 2.2:
        return ("HIDING IN THE TAPE", "Buyers took every down", f"day — {udr:.1f} to 1.", "updown", udr)
    if (tt.get("vol_contracting_in_base") and tt.get("PriceWithin25Percent52WeekHigh")
            and not tt.get("below_pivot")):  # only when it's actually pressing the highs
        return ("THE QUIET PART", "New highs — while volume", "quietly dried up.", "coil", None)
    if last_s is not None and last_s >= 18:
        return ("THE BEAT NOBODY CLOCKED", "It beat estimates by", f"{last_s:.0f}% last quarter.", "surprise", recent[-1])
    if beats and beats >= 12:
        return ("NOBODY'S TALKING ABOUT IT", "It's beaten estimates", f"{beats} quarters running.", "streak", beats)
    if rs is not None and rs <= 8:
        return ("THE RANK NOBODY CHECKS", "Relative-strength rank", f"{int(rs)} — top of the market.", "rank", rs)
    if udr and udr >= 1.5:
        return ("HIDING IN THE TAPE", "Buyers are taking the", f"dips — {udr:.1f} to 1.", "updown", udr)
    if beats and beats >= 6:
        return ("THE STREAK YOU MISSED", "It's beaten estimates", f"{beats} quarters running.", "streak", beats)
    if max_s is not None and max_s >= 15:
        return ("THE BEAT NOBODY CLOCKED", "It beat estimates by", f"{max_s:.0f}% recently.", "surprise", best_surprise_rec())
    if tt.get("accumulation"):
        return ("HIDING IN THE TAPE", "It's been quietly", "accumulated for weeks.", "updown", udr or 1.5)
    return ("WHAT THE SCREEN CAUGHT", "One clean move from", "a textbook breakout.", "breakout", None)


def main() -> None:
    ap = argparse.ArgumentParser(description="Annotated NIS-momentum setup chart for one ticker.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--display-days", type=int, default=180,
                    help="Trading window shown on the chart (SMAs still use full history).")
    ap.add_argument("--lookback-days", type=int, default=420,
                    help="Calendar days of history fetched (needs >200 trading days for SMA200).")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--rs-rank", type=int, default=None,
                    help="IBD RS rank (1-99) from the NIS Momentum run. RS is "
                         "universe-relative and can't be computed for one ticker, "
                         "so pass it from the screening; omitted -> shown as unknown.")
    ap.add_argument("--bare", action="store_true",
                    help="Drop the built-in title (the carousel slide owns the header). "
                         "Pair with --height/--chart-name to fit a slide region.")
    ap.add_argument("--height", type=int, default=H, help="Output PNG height (px).")
    ap.add_argument("--chart-name", default="chart.png",
                    help="Output PNG filename inside the ticker's output dir.")
    args = ap.parse_args()

    ticker = args.ticker.upper().strip()
    enddate = date.today()
    startdate = enddate - timedelta(days=args.lookback_days)

    t = technical()
    # RS_Rank/RS are percentile ranks across the whole screened universe — the
    # NIS Momentum pipeline computes them via get_change_prices(). Standalone we
    # can't, so stub a one-row df_rs (with the rank passed in, if any) just so
    # minervini_trend_template runs; we treat the stubbed RS as unknown below.
    rs_known = args.rs_rank is not None
    t.df_rs = pd.DataFrame([{
        "symbol": ticker,
        "RS": 0.0,
        "RS_Rank": int(args.rs_rank) if rs_known else 0,
    }])
    data, tt, error = t.get_screening(ticker, startdate.isoformat(), enddate.isoformat())
    if error or tt is None or data is None:
        sys.exit(f"screening failed for {ticker} (check APIKEY / ticker)")
    if not rs_known:
        tt["RS_Rank"] = None  # stub value is meaningless solo
        tt["RSOver70"] = None

    full = data if "date" in data.columns else data.reset_index()
    close = float(full["close"].iloc[-1])
    sma50 = float(full["SMA50"].iloc[-1])
    setup = derive_trade_setup(tt, close, sma50)

    df = full.tail(args.display_days).reset_index(drop=True)

    out_dir = pathlib.Path(args.out_dir) if args.out_dir else ANALYTICS_DIR / "output" / "setups" / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    fig = build_chart(df, tt, setup, ticker, height=args.height, bare=args.bare)
    chart_path = out_dir / args.chart_name
    fig.write_image(str(chart_path), width=W, height=args.height, scale=2)

    # JSON-safe technical/fundamental snapshot for the director.
    def jn(v):
        try:
            f = float(v)
            return f if f == f else None
        except (TypeError, ValueError):
            return v

    last = full.iloc[-1]
    tech_fields = {k: tt.get(k) for k in (
        "RS_Rank", "Passed", "PriceOverSMA50", "PriceOverSMA150And200",
        "SMA50AboveSMA150And200", "SMA200Slope", "PriceWithin25Percent52WeekHigh",
        "RSOver70", "adr_pct", "vol_ratio_today", "up_down_vol_ratio",
        "accumulation", "vol_contracting_in_base", "rs_line_new_high",
        "within_buy_range", "extended", "below_pivot", "pivot", "extension_pct",
    ) if k in tt}
    tech_fields.update({
        "SMA50": jn(last.get("SMA50")),
        "SMA150": jn(last.get("SMA150")),
        "SMA200": jn(last.get("SMA200")),
    })
    fundamentals = fetch_fundamentals(ticker)
    snapshot = {
        "ticker": ticker,
        "company": fundamentals.get("company"),
        "sector": fundamentals.get("sector"),
        "as_of": str(tt.get("date")),
        "price": jn(close),
        "rs_rank_source": "screening" if rs_known else "unknown — pass --rs-rank from the NIS Momentum run",
        "technical": tech_fields,
        "screen_flags": {k: tt.get(k) for k in (
            "increasing_eps", "beat_estimate", "PASSED_FUNDAMENTALS",
        ) if k in tt},
        "fundamentals": fundamentals,
        "trade_setup": setup,
        "chart_png": str(chart_path),
    }
    (out_dir / "setup.json").write_text(json.dumps(snapshot, indent=2, default=jn))

    print(json.dumps({"chart_png": str(chart_path),
                      "setup_json": str(out_dir / "setup.json"),
                      "trade_setup": setup}, indent=2, default=jn))


if __name__ == "__main__":
    main()
