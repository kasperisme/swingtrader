"""Charts — the search and the strategies it produces, made legible.

Two audiences, one file:

* **Search charts** answer "is the loop learning?" — reward over iterations,
  where the good proposals came from, which operators paid off. A search that
  plateaus, or one where every improvement comes from random restarts, is
  telling you something you cannot see in a leaderboard.
* **Performance charts** answer "would I have held this?" — equity against the
  benchmark, the drawdown you would have sat through, the shape of the trade
  distribution, and where the P&L actually leaked out.

All plots are theme-neutral (dark text on light ground, colour-blind-safe
palette) and every axis is labelled in the units a reader thinks in.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

# Okabe-Ito: distinguishable under the common colour-vision deficiencies.
INK = "#1a1a1a"
MUTED = "#6b6b6b"
GRID = "#e2e2e2"
ACCENT = "#0072B2"
POS = "#009E73"
NEG = "#D55E00"
ALT = "#CC79A7"
WARN = "#E69F00"
SERIES = [ACCENT, POS, WARN, ALT, "#56B4E9", NEG]

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titlesize": 12.5, "axes.titleweight": "bold",
    "figure.dpi": 130, "savefig.bbox": "tight", "savefig.facecolor": "white",
})


def _pct(ax, axis: str = "y") -> None:
    fmt = PercentFormatter(xmax=1.0)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def _money(ax) -> None:
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"${v/1e6:.1f}M" if abs(v) >= 1e6 else f"${v/1e3:.0f}k"))


def _note(ax, text: str, wrap: int = 108) -> None:
    """One line under the title saying what the reader should take away.

    Matplotlib keeps separate left/center/right title slots, so re-setting the
    title with loc="left" without clearing the centre one draws both on top of
    each other. Clear first.
    """
    import textwrap
    title = ax.get_title()
    ax.set_title("")
    lines = textwrap.wrap(text, wrap) or [""]
    ax.set_title(title, loc="left", pad=10 + 11 * len(lines))
    ax.text(0.0, 1.015, "\n".join(lines), transform=ax.transAxes, fontsize=8.5,
            color=MUTED, va="bottom", ha="left", linespacing=1.35)


def _save(fig, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    fig.savefig(path)
    plt.close(fig)
    return path


# ======================================================================
# Search progress
# ======================================================================
def search_charts(ledger_path: Path, out_dir: Path) -> list[Path]:
    """Reward trajectory, proposal provenance, operator payoff."""
    conn = sqlite3.connect(str(ledger_path))
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT iteration, genome_hash, rung, valid, reward, sharpe, source, operator "
        "FROM trials ORDER BY id ASC")]
    conn.close()
    if not rows:
        return []
    df = pd.DataFrame(rows)
    r1 = df[(df["rung"] == 1)].copy()
    out: list[Path] = []

    # ---- 1. reward trajectory ------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 4.6))
    valid = r1[r1["valid"] == 1]
    if len(valid):
        ax.scatter(valid["iteration"], valid["reward"], s=26, alpha=0.55,
                   color=ACCENT, edgecolor="none", label="evaluated (full walk-forward)")
        best = valid.sort_values("iteration").groupby("iteration")["reward"].max().cummax()
        ax.plot(best.index, best.values, color=POS, lw=2.2, label="best so far")
        base = valid[valid["source"] == "seed"]["reward"]
        if len(base):
            ax.axhline(float(base.iloc[0]), color=NEG, ls="--", lw=1.4,
                       label=f"incumbent baseline ({float(base.iloc[0]):+.3f})")
    invalid = r1[r1["valid"] == 0]
    if len(invalid):
        ax.scatter(invalid["iteration"], np.full(len(invalid), valid["reward"].min() if len(valid) else -1),
                   s=18, marker="x", color=MUTED, alpha=0.5, label="rejected (not a strategy)")
    ax.set_xlabel("iteration")
    ax.set_ylabel("reward  (median fold Sharpe − penalties)")
    ax.set_title("Does the search learn?")
    _note(ax, "A rising green line means the loop is finding real improvements; a flat one means it has plateaued.")
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    out.append(_save(fig, out_dir, "search_reward.png"))

    # ---- 2. where the good ideas came from ------------------------------
    if len(valid) > 3:
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
        counts = df[df["rung"] == 0]["source"].value_counts()
        a1.bar(counts.index, counts.values, color=SERIES[:len(counts)])
        a1.set_title("Proposals by origin")
        a1.set_ylabel("candidates screened")
        _note(a1, "The budget split across LLM hypotheses, surrogate, mutation and restarts.")

        by_src = valid.groupby("source")["reward"].agg(["max", "mean", "size"])
        by_src = by_src.sort_values("max", ascending=True)
        y = np.arange(len(by_src))
        a2.barh(y - 0.19, by_src["max"], height=0.36, color=POS, label="best")
        a2.barh(y + 0.19, by_src["mean"], height=0.36, color=ACCENT, alpha=0.75, label="mean")
        a2.set_yticks(y, [f"{i}  (n={int(n)})" for i, n in zip(by_src.index, by_src["size"])])
        a2.set_xlabel("reward")
        a2.set_title("Which origin produced the winners?")
        _note(a2, "Best vs average reward per source — a high mean matters more than one lucky draw.")
        a2.legend(frameon=False, fontsize=8.5)
        out.append(_save(fig, out_dir, "search_sources.png"))

    # ---- 3. operator payoff ---------------------------------------------
    ops = valid[valid["operator"].notna() & (valid["operator"] != "")]
    if len(ops) > 5:
        agg = (ops.groupby("operator")["reward"]
                  .agg(["mean", "size"]).sort_values("mean"))
        agg = agg[agg["size"] >= 1]
        fig, ax = plt.subplots(figsize=(8.5, max(3.2, 0.32 * len(agg) + 1.4)))
        colors = [POS if v >= 0 else NEG for v in agg["mean"]]
        ax.barh(np.arange(len(agg)), agg["mean"], color=colors, alpha=0.85)
        ax.set_yticks(np.arange(len(agg)),
                      [f"{i}  (n={int(n)})" for i, n in zip(agg.index, agg["size"])])
        ax.axvline(0, color=INK, lw=1)
        ax.set_xlabel("mean reward of resulting genomes")
        ax.set_title("Which kinds of change paid off?")
        _note(ax, "The bandit spends its budget on the operators toward the top of this chart.")
        out.append(_save(fig, out_dir, "search_operators.png"))

    return out


# ======================================================================
# Strategy performance
# ======================================================================
def performance_charts(result, metrics: dict, out_dir: Path,
                       bench_returns: np.ndarray | None = None,
                       fold_metrics: list[dict] | None = None,
                       label: str = "strategy") -> list[Path]:
    """Equity, drawdown, fold stability, trade shape, P&L attribution."""
    out: list[Path] = []
    dates = pd.to_datetime(result.dates)
    eq = result.equity
    tf = result.trades_frame()

    # ---- 1. equity + drawdown -------------------------------------------
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True,
                                 gridspec_kw={"height_ratios": [2.6, 1]})
    a1.plot(dates, eq / eq[0], color=ACCENT, lw=1.9, label=label)
    if bench_returns is not None and len(bench_returns) == len(eq):
        bench_eq = np.cumprod(1.0 + np.nan_to_num(bench_returns))
        a1.plot(dates, bench_eq / bench_eq[0], color=MUTED, lw=1.4, ls="--",
                label="benchmark (buy & hold)")
    a1.set_ylabel("growth of $1")
    a1.set_yscale("log")
    a1.set_title(f"{label} — equity curve")
    _note(a1, "Log scale: equal vertical distances are equal percentage moves.")
    a1.legend(frameon=False, fontsize=9)

    peak = np.maximum.accumulate(eq)
    dd = eq / np.where(peak > 0, peak, np.nan) - 1.0
    a2.fill_between(dates, dd, 0, color=NEG, alpha=0.35, linewidth=0)
    a2.plot(dates, dd, color=NEG, lw=1.0)
    a2.set_ylabel("drawdown")
    _pct(a2)
    worst = float(np.nanmin(dd))
    a2.annotate(f"worst {worst:.1%}", xy=(dates[int(np.nanargmin(dd))], worst),
                xytext=(6, 8), textcoords="offset points", fontsize=8.5, color=NEG)
    _note(a2, "This is the pain you would have had to sit through to collect the return above.")
    out.append(_save(fig, out_dir, "perf_equity.png"))

    # ---- 2. fold stability ----------------------------------------------
    if fold_metrics:
        fig, ax = plt.subplots(figsize=(8.5, 4))
        names = [f["fold"] for f in fold_metrics]
        sr = [f["sharpe"] for f in fold_metrics]
        ax.bar(names, sr, color=[POS if s > 0 else NEG for s in sr], alpha=0.9)
        ax.axhline(0, color=INK, lw=1)
        med = float(np.median(sr))
        ax.axhline(med, color=ACCENT, ls="--", lw=1.4, label=f"median {med:+.2f}")
        for i, f in enumerate(fold_metrics):
            ax.annotate(f"{f['start'][:4]}–{f['end'][:4]}\n{f['n_trades']} trades",
                        (i, sr[i]), ha="center",
                        va="bottom" if sr[i] >= 0 else "top",
                        xytext=(0, 6 if sr[i] >= 0 else -6),
                        textcoords="offset points", fontsize=8, color=MUTED)
        ax.set_ylabel("Sharpe")
        ax.set_title("Does it work in more than one regime?")
        _note(ax, "The reward optimises the MEDIAN of these bars and penalises their spread.")
        ax.legend(frameon=False, fontsize=8.5)
        out.append(_save(fig, out_dir, "perf_folds.png"))

    if tf.empty:
        return out

    # ---- 3. trade distribution ------------------------------------------
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    r = tf["r_multiple"].clip(-3, 6)
    a1.hist(r, bins=48, color=ACCENT, alpha=0.85, edgecolor="white", linewidth=0.4)
    a1.axvline(0, color=INK, lw=1)
    a1.axvline(float(tf["r_multiple"].mean()), color=POS, lw=1.8,
               label=f"expectancy {tf['r_multiple'].mean():+.2f}R")
    a1.set_xlabel("outcome, in R (multiples of risk)")
    a1.set_ylabel("trades")
    a1.set_title("Trade outcome distribution")
    _note(a1, "A long right tail with a wall at −1R is the shape a stop-loss strategy should have.")
    a1.legend(frameon=False, fontsize=8.5)

    by_reason = tf.groupby("exit_reason")["pnl"].sum().sort_values()
    a2.barh(by_reason.index, by_reason.values,
            color=[POS if v >= 0 else NEG for v in by_reason.values], alpha=0.9)
    a2.axvline(0, color=INK, lw=1)
    _money(a2)
    a2.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"${v/1e3:.0f}k" if abs(v) >= 1e3 else f"${v:.0f}"))
    a2.set_xlabel("total P&L")
    a2.set_title("Where the money was made and lost")
    _note(a2, "A large negative bar is an exit rule that is costing more than it protects.")
    out.append(_save(fig, out_dir, "perf_trades.png"))

    # ---- 3b. long vs short attribution ----------------------------------
    if "side" in tf.columns and (tf["side"] == -1).any():
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
        agg = tf.groupby("side").agg(pnl=("pnl", "sum"), n=("pnl", "size"),
                                     exp_r=("r_multiple", "mean"))
        labels = {1: "long", -1: "short"}
        names = [f"{labels[i]}  (n={int(agg.loc[i, 'n'])})" for i in agg.index]
        vals = agg["pnl"].to_numpy()
        a1.bar(names, vals, color=[POS if v >= 0 else NEG for v in vals], alpha=0.9)
        a1.axhline(0, color=INK, lw=1)
        a1.yaxis.set_major_formatter(FuncFormatter(
            lambda v, _: f"${v/1e3:.0f}k" if abs(v) >= 1e3 else f"${v:.0f}"))
        a1.set_ylabel("total P&L")
        a1.set_title("Did each sleeve pay for itself?")
        borrow = float(tf["borrow_cost"].sum()) if "borrow_cost" in tf.columns else 0.0
        _note(a1, f"Borrow paid on the short book: ${borrow:,.0f}. A short sleeve that "
                  "loses money is invisible in a portfolio-level Sharpe.")

        for i, side in enumerate(agg.index):
            sub = tf[tf["side"] == side]
            a2.hist(sub["r_multiple"].clip(-3, 6), bins=36, alpha=0.6,
                    color=(ACCENT if side == 1 else ALT), edgecolor="white",
                    linewidth=0.3, label=f"{labels[side]}  E={sub['r_multiple'].mean():+.2f}R")
        a2.axvline(0, color=INK, lw=1)
        a2.set_xlabel("outcome, in R")
        a2.set_ylabel("trades")
        a2.set_title("Outcome distribution by side")
        _note(a2, "A short book should have a tighter right tail than the long book — "
                  "profits are bounded below by zero, losses are not.")
        a2.legend(frameon=False, fontsize=8.5)
        out.append(_save(fig, out_dir, "perf_sides.png"))

    # ---- 4. exposure + position count -----------------------------------
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.fill_between(dates, result.exposure, 0, color=ACCENT, alpha=0.28, linewidth=0)
    ax.plot(dates, result.exposure, color=ACCENT, lw=1.1, label="gross exposure")
    _pct(ax)
    ax.set_ylabel("invested share of equity")
    ax2 = ax.twinx()
    if getattr(result, "net_exposure", None) is not None:
        ax.plot(dates, result.net_exposure, color=ALT, lw=1.2, ls="--",
                label="net (long − short)")
        ax.axhline(0, color=INK, lw=0.8)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax2.plot(dates, result.n_positions, color=WARN, lw=1.0, alpha=0.75,
             label="open positions")
    ax2.set_ylabel("positions", color=WARN)
    ax2.grid(False)
    ax.set_title("Capital deployment over time")
    _note(ax, f"Average exposure {np.nanmean(result.exposure):.0%} — idle capital caps the return regardless of signal quality.")
    out.append(_save(fig, out_dir, "perf_exposure.png"))

    return out


# ======================================================================
def contact_sheet(images: list[Path], out_path: Path, title: str,
                  subtitle: str = "") -> Path:
    """One scrollable HTML page holding every chart, for quick review."""
    cards = "\n".join(
        f'<figure><img src="{p.name}" alt="{p.stem}"><figcaption>{p.stem.replace("_", " ")}</figcaption></figure>'
        for p in images)
    html = f"""<!doctype html><meta charset="utf-8">
<title>{title}</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font: 15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
        margin: 0; padding: 2.5rem clamp(1rem,4vw,3rem); background:#fafafa; color:#1a1a1a; }}
 h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
 p.sub {{ color:#6b6b6b; margin: 0 0 2rem; }}
 figure {{ margin: 0 0 2.5rem; background:#fff; border:1px solid #e6e6e6;
           border-radius:10px; padding:1rem; }}
 img {{ width:100%; height:auto; display:block; }}
 figcaption {{ color:#6b6b6b; font-size:.85rem; margin-top:.6rem; text-transform:capitalize; }}
 @media (prefers-color-scheme: dark) {{
   body {{ background:#141414; color:#ededed; }}
   figure {{ background:#1d1d1d; border-color:#2e2e2e; }}
   p.sub, figcaption {{ color:#9a9a9a; }}
 }}
</style>
<h1>{title}</h1><p class="sub">{subtitle}</p>
{cards}
"""
    out_path.write_text(html)
    return out_path
