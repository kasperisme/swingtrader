"""Charts for the flow-inertia investigation.

The brief names one chart as the decisive one — average return in event time
after F crosses 1, split by rho tercile — because a *shape* is much harder to
overfit than a Sharpe ratio. That one is `event_time_chart`. The rest exist to
make the precondition failure visible rather than merely asserted: if rho is
noise, you should be able to see that it is noise.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from ..charts import ACCENT, ALT, GRID, INK, MUTED, NEG, POS, SERIES, WARN, _note, _save


def rho_distribution_chart(sig, out_dir: Path, unsigned_ar1: float | None = None) -> Path:
    """The artefact, shown side by side with the honest estimator."""
    rho = sig.rho[np.isfinite(sig.rho)]
    rho_ema = sig.rho_ema[np.isfinite(sig.rho_ema)]

    fig, ax = plt.subplots(figsize=(9, 4.8))
    bins = np.linspace(-1.2, 1.6, 90)
    ax.hist(rho, bins=bins, color=ACCENT, alpha=0.75, edgecolor="white",
            linewidth=0.3, label=f"ρ — AR(1) of weekly summed flow  (mean {rho.mean():+.3f})")
    ax.hist(rho_ema, bins=bins, color=NEG, alpha=0.5, edgecolor="white",
            linewidth=0.3, label=f"ρ_ema — the spec's smoothed variant  (mean {rho_ema.mean():+.3f})")
    ax.axvline(0, color=INK, lw=1.2)

    top = ax.get_ylim()[1]
    ax.set_ylim(0, top * 1.24)          # headroom so callouts never sit on bars

    detect = 2.0 / np.sqrt(26)
    ax.axvline(detect, color=WARN, ls="--", lw=1.5)
    ax.annotate(f"detectable at |ρ| > {detect:.2f}", xy=(detect, top * 1.16),
                xytext=(6, 0), textcoords="offset points", fontsize=8.5,
                color=WARN, va="center", ha="left")
    if unsigned_ar1 is not None:
        ax.axvline(unsigned_ar1, color=POS, ls=":", lw=1.8)
        ax.annotate(f"unsigned $ volume AR(1) = {unsigned_ar1:+.2f}",
                    xy=(unsigned_ar1, top * 1.04), xytext=(6, 0),
                    textcoords="offset points", fontsize=8.5, color=POS,
                    va="center", ha="left")

    ax.set_xlim(-1.15, 1.55)
    ax.set_xlabel("AR(1) persistence coefficient")
    ax.set_ylabel("stock-days")
    ax.set_title("Is there any inertia in the forcing function?")
    _note(ax, "The blue mass sits on zero: no persistence. The red mass is the EMA's own "
              "memory — an AR(1) coefficient above 1.0 is not even a valid persistence value.")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left",
              bbox_to_anchor=(0.0, 0.86))
    return _save(fig, out_dir, "flow_rho_distribution.png")


def proxy_comparison_chart(results: dict[str, dict], out_dir: Path) -> Path:
    """Every flow proxy tested, against the persistence of raw volume."""
    names = list(results)
    weekly = [results[n]["weekly"] for n in names]
    monthly = [results[n].get("monthly", np.nan) for n in names]
    y = np.arange(len(names))

    fig, ax = plt.subplots(figsize=(9, max(3.4, 0.46 * len(names) + 1.6)))
    ax.barh(y - 0.19, weekly, height=0.36, color=ACCENT, label="weekly AR(1)")
    ax.barh(y + 0.19, monthly, height=0.36, color=ALT, alpha=0.85, label="monthly AR(1)")
    ax.axvline(0, color=INK, lw=1)
    detect = 2.0 / np.sqrt(26)
    ax.axvspan(-detect, detect, color=GRID, alpha=0.6, zorder=0)
    ax.annotate("indistinguishable from zero", xy=(0, len(names) - 0.4),
                ha="center", fontsize=8.5, color=MUTED)
    ax.set_yticks(y, names)
    ax.set_xlabel("AR(1) persistence")
    ax.set_title("No price-derived flow proxy carries persistence")
    _note(ax, "Direction is what the theory needs, and direction is exactly what none of these retain.")
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    return _save(fig, out_dir, "flow_proxy_comparison.png")


def impact_law_chart(df: pd.DataFrame, out_dir: Path, y_prior: tuple = (0.5, 1.0),
                     knee: dict | None = None) -> Path:
    """Contemporaneous fit vs the forward control.

    The contemporaneous curve looks like a textbook impact law. The forward
    curve — same F, next window's move, no shared return signs — is flat. The
    gap between the two lines IS the circularity, and showing them together is
    the only honest way to present either.
    """
    col = "realised_20d" if "realised_20d" in df.columns else "fwd_ret"
    g = df[["F", col, "sigma"]].dropna()
    g = g[(g["sigma"] > 0) & (g["F"].abs() > 1e-9)]
    x = np.sqrt(g["F"].abs().to_numpy())
    yv = np.abs(g[col].to_numpy()) / (g["sigma"].to_numpy() * np.sqrt(21))
    ok = np.isfinite(x) & np.isfinite(yv)
    x, yv = x[ok], yv[ok]
    keep = x <= np.quantile(x, 0.99)
    x, yv = x[keep], yv[keep]
    slope, intercept, r, p, _se = stats.linregress(x, yv)

    # Binned means: 100k scattered points hide the relationship they contain,
    # and |move| is right-skewed enough that raw OLS does not track E[y|x].
    q = pd.qcut(pd.Series(x), 40, labels=False, duplicates="drop")
    b = pd.DataFrame({"x": x, "y": yv, "q": q}).groupby("q").agg(
        x=("x", "mean"), y=("y", "mean"), n=("y", "size"), sd=("y", "std"))
    bslope, bintercept, br, _bp, _bse = stats.linregress(b["x"], b["y"])

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(x[::37], yv[::37], s=4, alpha=0.06, color=MUTED, edgecolor="none",
               zorder=1, label="stock-months (1-in-37 sample)")
    ax.errorbar(b["x"], b["y"], yerr=b["sd"] / np.sqrt(b["n"]), fmt="o",
                ms=5, color=ACCENT, ecolor=ACCENT, elinewidth=1.2, capsize=2,
                zorder=3, label="binned mean ± s.e.")
    xs = np.linspace(0, x.max(), 100)
    ax.plot(xs, bintercept + bslope * xs, color=NEG, lw=2.4, zorder=5,
            label=f"binned fit:  {bintercept:.2f} + {bslope:.3f}·√|F|   (R²={br**2:.2f})")
    ax.plot(xs, intercept + slope * xs, color=MUTED, lw=1.3, ls="--", zorder=4,
            label=f"raw OLS on all points:  {intercept:.2f} + {slope:.3f}·√|F|")
    ax.fill_between(xs, bintercept + y_prior[0] * xs, bintercept + y_prior[1] * xs,
                    color=POS, alpha=0.12, zorder=2,
                    label=f"literature prior Y ∈ [{y_prior[0]}, {y_prior[1]}]")
    ax.axhline(float(b["y"].iloc[0]), color=WARN, ls=":", lw=1.3, zorder=3)
    ax.annotate(f"inert floor: {b['y'].iloc[0]:.2f}σ", xy=(0.06, float(b["y"].iloc[0])),
                xytext=(0, -14), textcoords="offset points", fontsize=8.5, color=WARN)
    if knee:
        bp = knee["breakpoint_sqrtF"]
        ax.axvline(bp, color=ALT, lw=2.0, zorder=3)
        ax.annotate(f"inertia knee\nF = {knee['breakpoint_F']:.2f}\n"
                    f"({knee['breakpoint_F']*100:.0f}% of Q_break)",
                    xy=(bp, ax.get_ylim()[1] * 0.72), xytext=(9, 0),
                    textcoords="offset points", fontsize=9, color=ALT, weight="bold",
                    va="center")
    # --- the control: same F, but the NEXT window's move -----------------
    if "fwd_ret" in df.columns:
        gf = df[["F", "fwd_ret", "sigma"]].dropna()
        gf = gf[(gf["sigma"] > 0) & (gf["F"].abs() > 1e-9)]
        xf = np.sqrt(gf["F"].abs().to_numpy())
        yf = np.abs(gf["fwd_ret"].to_numpy()) / (gf["sigma"].to_numpy() * np.sqrt(21))
        okf = np.isfinite(xf) & np.isfinite(yf)
        xf, yf = xf[okf], yf[okf]
        kf = xf <= np.quantile(xf, 0.99)
        xf, yf = xf[kf], yf[kf]
        qf = pd.qcut(pd.Series(xf), 40, labels=False, duplicates="drop")
        bf = pd.DataFrame({"x": xf, "y": yf, "q": qf}).groupby("q").agg(
            x=("x", "mean"), y=("y", "mean"), n=("y", "size"), sd=("y", "std"))
        fs, fi, fr, _fp, _fse = stats.linregress(bf["x"], bf["y"])
        ax.errorbar(bf["x"], bf["y"], yerr=bf["sd"] / np.sqrt(bf["n"]), fmt="s",
                    ms=4.5, color=WARN, ecolor=WARN, elinewidth=1.0, capsize=2,
                    zorder=6, alpha=0.9,
                    label=f"CONTROL — next window's move  (Y = {fs:+.3f}, R²={fr**2:.3f})")
        ax.plot(xs, fi + fs * xs, color=WARN, lw=2.0, zorder=6)

    ax.set_xlabel("√|F|   (√ of flow ÷ breakout threshold)")
    ax.set_ylabel("|move| ÷ σ")
    ax.set_title("The impact 'law' here is an accounting identity")
    _note(ax, f"n = {x.size:,} stock-months. BLUE: the same window's move — F is built "
              "from the signs of those very returns, so this slope is largely mechanical. "
              "ORANGE: the identical fit on the NEXT window's move, sharing no signs with "
              "its target. It is flat. Nothing about real price impact is established here.")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    return _save(fig, out_dir, "flow_impact_law.png")


def event_time_chart(test_t2: dict, out_dir: Path) -> Path | None:
    """The brief's decisive chart: drift after F crosses 1, by rho tercile.

    Theory predicts drift for ~T_half then flattening in the high-rho group, and
    immediate reversal in the low-rho group. Three curves lying on top of each
    other means rho is not separating anything.
    """
    curves = (test_t2 or {}).get("curves") or {}
    if not curves:
        return None
    order = ["low_rho", "mid_rho", "high_rho"]
    colors = {"low_rho": NEG, "mid_rho": MUTED, "high_rho": POS}

    fig, ax = plt.subplots(figsize=(9, 5))
    for name in order:
        c = curves.get(name)
        if not c:
            continue
        y = np.array(c["cum_return_by_day"], dtype=float)
        ax.plot(np.arange(1, len(y) + 1), y, lw=2.1, color=colors[name],
                label=f"{name.replace('_', ' ')}  (n={c['n']:,})")
    ax.axhline(0, color=INK, lw=1)
    ax.set_xlabel("trading days after F crosses 1")
    ax.set_ylabel("cumulative average return")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=1.0))
    ax.set_title("Event-time drift after the forcing threshold is crossed")

    hi = curves.get("high_rho", {}).get("cum_20d")
    lo = curves.get("low_rho", {}).get("cum_20d")
    if hi is not None and lo is not None:
        _note(ax, f"Theory predicts high-ρ drifts and low-ρ reverses. Measured at 20 days: "
                  f"high-ρ {hi:+.2%} vs low-ρ {lo:+.2%} — a {abs(hi-lo):.2%} gap, with all "
                  "three groups simply drifting with the market.")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    return _save(fig, out_dir, "flow_event_time.png")


def coefficient_chart(models: dict, out_dir: Path, key_term: str = "rho_x_F_z") -> Path | None:
    """Fama-MacBeth coefficients with Newey-West confidence intervals."""
    m = models.get("M5_add_interaction")
    if not m:
        return None
    coefs = m["coefficients"] if isinstance(m, dict) else m.coefficients
    names = [k for k in coefs if k != "const"]
    if not names:
        return None
    vals = np.array([coefs[k]["coef"] for k in names])
    ses = np.array([coefs[k]["se"] for k in names])
    ts = np.array([coefs[k]["t"] for k in names])

    order = np.argsort(vals)
    names = [names[i] for i in order]
    vals, ses, ts = vals[order], ses[order], ts[order]
    colors = [NEG if n == key_term else (ACCENT if abs(t) >= 1.96 else MUTED)
              for n, t in zip(names, ts)]

    fig, ax = plt.subplots(figsize=(8.6, max(3.4, 0.42 * len(names) + 1.6)))
    y = np.arange(len(names))
    ax.errorbar(vals, y, xerr=1.96 * ses, fmt="o", ms=6, elinewidth=1.6,
                capsize=3, ecolor=MUTED, mfc="none", mec="none")
    ax.scatter(vals, y, s=52, color=colors, zorder=3)
    ax.axvline(0, color=INK, lw=1.2)
    ax.set_yticks(y, [f"{n}   t={t:+.2f}" for n, t in zip(names, ts)])
    ax.set_xlabel("coefficient on next-month return  (per cross-sectional SD)")
    ax.set_title("Fama-MacBeth: which predictors survive the controls?")
    _note(ax, "Bars are 95% Newey-West intervals. Any interval crossing the vertical line "
              "is indistinguishable from no effect. The interaction term is highlighted.")
    return _save(fig, out_dir, "flow_coefficients.png")


def momentum_by_rho_chart(test_t1: dict, out_dir: Path) -> Path | None:
    """12-1 momentum spread within each rho quintile."""
    if not (test_t1 or {}).get("available"):
        return None
    b = test_t1["buckets"]
    x = [f"Q{r['rho_bucket']+1}" for r in b]
    v = [r["annualised"] for r in b]
    t = [r["t"] for r in b]

    fig, ax = plt.subplots(figsize=(8, 4.3))
    bars = ax.bar(x, v, color=[POS if abs(tt) >= 1.96 else MUTED for tt in t], alpha=0.9)
    ax.axhline(0, color=INK, lw=1)
    for rect, tt in zip(bars, t):
        ax.annotate(f"t={tt:+.2f}", (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                    ha="center", va="bottom", xytext=(0, 4), textcoords="offset points",
                    fontsize=8.5, color=MUTED)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=1.0))
    ax.set_ylabel("12-1 momentum spread, annualised")
    ax.set_xlabel("flow-persistence quintile (ρ)")
    ax.set_title("Is momentum stronger where flow persists?")
    sp = test_t1.get("spearman_rho_vs_momentum", 0.0)
    _note(ax, f"Spearman(ρ bucket, momentum) = {sp:+.2f}. With five buckets that carries "
              "almost no information — grey bars are not significant individually.")
    return _save(fig, out_dir, "flow_momentum_by_rho.png")
