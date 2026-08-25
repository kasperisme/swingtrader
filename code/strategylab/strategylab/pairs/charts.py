"""Charts for the FDP study. One figure per claim, no decoration."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_L = "#1f77b4"
_N = "#d62728"
_ALL = "#555555"


def _style(ax, title, xlabel, ylabel):
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(alpha=0.25, linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def survival(df: pd.DataFrame, out: Path, horizon: int = 60) -> Path:
    """Share of divergences still unconverged, by day since the divergence.

    This is the whole of H1 in one picture: if the taxonomy works, the two
    curves separate and stay separated.
    """
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=140)
    days = np.arange(0, horizon + 1)
    for label, color, sub in (("all divergences", _ALL, df),
                              ("L — no announcement", _L, df[df["regime"] == "L"]),
                              ("N — announcement on a leg", _N, df[df["regime"] == "N"])):
        if not len(sub):
            continue
        d = sub["days_to_converge"].to_numpy(dtype=float)
        surv = [float(np.mean(~(d <= k))) for k in days]
        ax.plot(days, surv, color=color, lw=1.8 if label != "all divergences" else 1.2,
                ls="--" if label == "all divergences" else "-",
                label=f"{label}  (n={len(sub)})")
    _style(ax, "Time to convergence after a |z| > 2 divergence",
           "trading days since divergence", "share still unconverged")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    p = out / "convergence_survival.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def per_window(df: pd.DataFrame, out: Path) -> Path:
    """Convergence rate by trading window and bucket — is the effect stable?"""
    g = df.groupby(["window", "regime"])["converged"].mean().unstack()
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=140)
    for col, color in (("L", _L), ("N", _N)):
        if col in g:
            ax.plot(g.index, g[col], marker="o", ms=3.5, lw=1.4, color=color, label=col)
    if {"L", "N"} <= set(g.columns):
        ax.fill_between(g.index, g["N"], g["L"], where=g["L"] >= g["N"],
                        color=_L, alpha=0.10, interpolate=True)
        ax.fill_between(g.index, g["N"], g["L"], where=g["L"] < g["N"],
                        color=_N, alpha=0.10, interpolate=True)
    _style(ax, "Convergence rate by trading window", "window (6 months each)",
           "share converged within 60 days")
    ax.axhline(0.5, color="#999", lw=0.8, ls=":")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    p = out / "convergence_by_window.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def bucket_pnl(df: pd.DataFrame, out: Path) -> Path:
    """Cumulative net return per event, in event order, by bucket.

    Equal-weight per event and NOT a portfolio curve: events overlap in time
    and a real book would have to size them jointly. It shows the sign and the
    consistency of the edge, not what it would have earned.
    """
    d = df.sort_values("day")
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=140)
    for label, color, sub in (("all", _ALL, d),
                              ("L — no announcement", _L, d[d["regime"] == "L"]),
                              ("N — announcement", _N, d[d["regime"] == "N"])):
        if not len(sub):
            continue
        ax.plot(np.arange(1, len(sub) + 1), sub["net_return"].cumsum().to_numpy(),
                color=color, lw=1.5, ls="--" if label == "all" else "-", label=label)
    _style(ax, "Cumulative net return per divergence traded (equal weight)",
           "events, in chronological order", "cumulative return of unit gross notional")
    ax.axhline(0, color="#999", lw=0.8)
    ax.legend(fontsize=8, frameon=False)

    # A cumulative sum pools every event, which quietly upweights the windows
    # that produced the most of them — and here those are also the better ones.
    # The reported statistic is the window-clustered mean, so both are printed
    # to stop the height of this curve from being read as the result.
    l = d[d["regime"] == "L"]
    if len(l):
        pooled = float(l["net_return"].mean())
        clustered = float(l.groupby("window")["net_return"].mean().mean())
        ax.text(0.01, -0.22,
                f"L bucket per event: pooled {pooled*100:+.3f}%  vs  window-clustered "
                f"{clustered*100:+.3f}%. Inference uses the clustered figure; this "
                f"curve is the pooled one.",
                transform=ax.transAxes, fontsize=7.5, color="#666")
    fig.tight_layout()
    p = out / "bucket_pnl.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


def null_and_selection(null: np.ndarray, adf: np.ndarray, crit: float, out: Path) -> Path:
    """The simulated Engle-Granger null against the pairs actually selected."""
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=140)
    ax.hist(null, bins=70, density=True, color="#bbbbbb",
            label=f"simulated null (independent random walks, n={len(null)})")
    if len(adf):
        ax.hist(adf, bins=50, density=True, color=_L, alpha=0.65,
                label=f"selected pairs (n={len(adf)})")
    ax.axvline(crit, color=_N, lw=1.4, ls="--", label=f"critical value {crit:.2f}")
    _style(ax, "Engle-Granger residual ADF statistic — null vs selected pairs",
           "ADF t-statistic", "density")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    p = out / "coint_null.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def write_all(df: pd.DataFrame, out_dir: Path, null=None, adf=None, crit=None) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [survival(df, out_dir), per_window(df, out_dir), bucket_pnl(df, out_dir)]
    if null is not None and adf is not None and crit is not None:
        paths.append(null_and_selection(null, adf, crit, out_dir))
    return [str(p) for p in paths]
