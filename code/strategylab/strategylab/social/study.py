"""SOCIAL-ARB-1 link tests.

Each function here runs one link of the thesis and returns a `LinkResult` with a
verdict, so the chain semantics live in the thesis and the statistics live here.

The pivotal test is `l2_attention_predicts_surprise`. Its whole job is to be
*able to come back negative*, which means the controls matter more than the
headline number:

* **The company-page placebo.** Pageviews for `Apple_Inc.` measure investors and
  journalists — the crowd whose views are already in the price. Pageviews for a
  product measure consumers. If the company page predicts the surprise as well
  as the product page, the mechanism is not "consumer demand shows up early", it
  is "attention correlates with returns", which is Cookson et al.'s one-day
  effect and does not support the thesis. This placebo is the single most
  important number the function produces.

* **Clustering by announcement date.** Earnings cluster into four weeks a
  quarter, and a shock common to those weeks (a sector move, a macro print) hits
  every name at once. Treating each announcement as independent would overstate
  |t| by roughly the square root of the average cluster size. Inference is
  therefore clustered on the announcement month.

* **Standardising the surprise by the firm's OWN history.** A raw EPS beat of
  two cents means something different for a firm that always beats by two cents
  than for one that never does. SUE is scaled by the trailing standard deviation
  of that firm's past surprises, computed point-in-time from announcements
  strictly before the one being scored.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import CACHE_ROOT
from ..thesis.thesis import (BLOCKED, FAILS, HOLDS, INCONCLUSIVE, Link,
                             LinkResult, link_bar)
from .pageviews import PageviewStore, attention_growth

log = logging.getLogger(__name__)

MIN_EVENTS = 200        # below this the test cannot decide anything
MIN_SURPRISE_HISTORY = 6


@dataclass
class L2Spec:
    """Every knob, in one place, so an arm can be described in the registry."""
    signal_lag: int = 5           # sessions BEFORE the announcement the signal is read
    growth_window: int = 90       # recent-attention window
    growth_baseline: int = 365    # its own trailing baseline
    car_days: int = 3             # announcement-window return, [d, d+car_days)
    min_base_views: float = 20.0
    dev_end: str = "2023-12-31"
    vault_start: str = "2024-01-01"


# ----------------------------------------------------------------------
def load_surprises(tickers: list[str], cache_dir: Path | None = None) -> pd.DataFrame:
    """Announcement dates with a point-in-time standardised surprise.

    `sue` at announcement i uses only announcements < i to set the scale, so a
    firm's whole surprise history is never used to standardise its own early
    prints. Announcements without `MIN_SURPRISE_HISTORY` priors are dropped
    rather than scaled by a noisy denominator.
    """
    d = Path(cache_dir or (CACHE_ROOT / "surprises"))
    rows = []
    for t in tickers:
        p = d / f"{t.replace('/', '_').replace('.', '-')}.json"
        if not p.exists():
            continue
        try:
            recs = json.loads(p.read_text())
        except Exception:                                  # noqa: BLE001
            continue
        df = pd.DataFrame(recs)
        if df.empty or not {"date", "actualEarningResult", "estimatedEarning"} <= set(df):
            continue
        df = df.dropna(subset=["date", "actualEarningResult", "estimatedEarning"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        df["surprise"] = df["actualEarningResult"].astype(float) - \
            df["estimatedEarning"].astype(float)
        # Expanding, SHIFTED: the scale at row i is built from rows < i only.
        scale = df["surprise"].expanding().std().shift(1)
        n_prior = df["surprise"].expanding().count().shift(1)
        df["sue"] = df["surprise"] / scale.where(scale > 1e-9)
        df["ticker"] = t
        df = df[n_prior >= MIN_SURPRISE_HISTORY]
        rows.append(df[["ticker", "date", "surprise", "sue"]])
    return (pd.concat(rows, ignore_index=True) if rows
            else pd.DataFrame(columns=["ticker", "date", "surprise", "sue"]))


def _cluster_t(y: np.ndarray, x: np.ndarray, groups: np.ndarray) -> tuple[float, float, int]:
    """Slope of y on x with standard errors clustered on `groups`.

    Announcements cluster into a handful of weeks each quarter; the naive OLS
    standard error assumes they do not, and is wrong by roughly sqrt(cluster
    size). Returns (slope, t, n_clusters).
    """
    ok = np.isfinite(y) & np.isfinite(x)
    y, x, g = y[ok], x[ok], groups[ok]
    n = y.size
    if n < 30 or np.nanstd(x) < 1e-12:
        return float("nan"), float("nan"), 0
    X = np.column_stack([np.ones(n), x])
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ (X.T @ y)
    resid = y - X @ beta
    meat = np.zeros((2, 2))
    for gg in np.unique(g):
        m = g == gg
        Xg, ug = X[m], resid[m]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    ncl = int(np.unique(g).size)
    if ncl < 8:
        return float(beta[1]), float("nan"), ncl
    # Small-cluster correction, as in Cameron-Gelbach-Miller.
    corr = ncl / max(1, ncl - 1)
    cov = xtx_inv @ meat @ xtx_inv * corr
    se = float(np.sqrt(max(cov[1, 1], 0.0)))
    return float(beta[1]), (float(beta[1]) / se if se > 0 else float("nan")), ncl


def _rank(v: pd.Series) -> pd.Series:
    """Cross-sectional rank within a period, mapped to [-0.5, +0.5].

    Ranking rather than using raw growth because attention growth has fat tails
    — a single page that went viral would otherwise set the slope on its own.
    """
    r = v.rank(pct=True)
    return r - 0.5


# ----------------------------------------------------------------------
def build_events(entities: dict[str, list], surprises: pd.DataFrame,
                 pv: PageviewStore, spec: L2Spec,
                 panel=None) -> pd.DataFrame:
    """One row per (ticker, announcement) with the pre-announcement signal.

    The signal is read `spec.signal_lag` CALENDAR days before the announcement
    from a series that is itself trailing, so nothing on the right-hand side is
    observable after the left-hand side. That is the same forward-control
    structure the pairs study uses and the flow study lacked.
    """
    out = []
    for t, ents in entities.items():
        prods = [e for e in ents if e.kind == "product"]
        comps = [e for e in ents if e.kind == "company"]
        if not prods:
            continue
        ev = surprises[surprises.ticker == t]
        if ev.empty:
            continue

        def series(ents_in: list) -> pd.Series | None:
            """Total daily views across a ticker's entities, then its growth.

            Summed before the growth is taken, not averaged after: a firm's
            consumer attention is the total across its brands, and averaging
            growth rates would let a tiny page swing a large one.

            Ownership is applied point-in-time. A brand acquired in 2025 has
            pageviews going back years, and attributing those to the acquirer
            would hand the model a demand history the firm never had — the
            attention "growth" at the acquisition date would be pure corporate
            action. Views before `valid_from` are therefore masked out. Where
            Wikidata records no acquisition date the article is treated as
            always-owned, which is the assumption that can be wrong; it is
            counted and reported rather than hidden.
            """
            cols, unknown = [], 0
            for e in ents_in:
                f = pv.load(e.article)
                if f is None or f.empty:
                    continue
                ser = f.set_index("date")["views"].rename(e.article).astype(float)
                if e.valid_from:
                    ser = ser.where(ser.index >= pd.Timestamp(e.valid_from))
                else:
                    unknown += 1
                cols.append(ser)
            if not cols:
                return None
            wide = pd.concat(cols, axis=1)
            tot = wide.sum(axis=1, min_count=1).to_frame("v")
            g = attention_growth(tot, spec.growth_window, spec.growth_baseline,
                                 spec.min_base_views)["v"]
            return g

        g_prod = series(prods)
        g_comp = series(comps)
        if g_prod is None:
            continue

        for _, r in ev.iterrows():
            asof = r["date"] - pd.Timedelta(days=spec.signal_lag)
            sp = g_prod.reindex(g_prod.index.union([asof])).sort_index().ffill().get(asof)
            sc = (g_comp.reindex(g_comp.index.union([asof])).sort_index().ffill().get(asof)
                  if g_comp is not None else np.nan)
            out.append({"ticker": t, "date": r["date"], "sue": r["sue"],
                        "surprise": r["surprise"],
                        "g_product": float(sp) if sp is not None and np.isfinite(sp) else np.nan,
                        "g_company": float(sc) if sc is not None and np.isfinite(sc) else np.nan})
    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["period"] = df["date"].dt.to_period("M").astype(str)
    return df.dropna(subset=["g_product", "sue"])


def add_announcement_return(df: pd.DataFrame, panel, spec: L2Spec) -> pd.DataFrame:
    """[d, d+car_days) return, filled at the open after the announcement.

    Same execution convention as the rest of the lab: a signal known at the
    close of d-1 is filled at the open of d. Missing legs are dropped rather
    than forward-filled.
    """
    if df.empty or panel is None:
        df["car"] = np.nan
        return df
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    sym = {s: i for i, s in enumerate(panel.symbols)}
    car = []
    for _, r in df.iterrows():
        j = sym.get(r["ticker"])
        if j is None:
            car.append(np.nan); continue
        i0 = int(np.searchsorted(dates, np.datetime64(r["date"].date())))
        i1 = i0 + spec.car_days
        if i0 <= 0 or i1 >= len(dates):
            car.append(np.nan); continue
        p0, p1 = panel.open[i0, j], panel.open[i1, j]
        car.append(float(p1 / p0 - 1.0) if np.isfinite(p0) and np.isfinite(p1)
                   and p0 > 0 else np.nan)
    df = df.copy()
    df["car"] = car
    return df


# ----------------------------------------------------------------------
def l2_attention_predicts_surprise(link: Link, events: pd.DataFrame,
                                   spec: L2Spec, arms_run: int) -> LinkResult:
    """The gate. Product attention growth -> SUE, against its placebo."""
    res = LinkResult(link_id=link.id)
    if events.empty:
        res.verdict = BLOCKED
        res.note = "no (ticker, announcement) rows — entity map or pageviews missing"
        return res

    dev = events[events["date"] <= spec.dev_end]
    vault = events[events["date"] >= spec.vault_start]
    res.n_obs = int(len(dev))
    res.bar = link_bar(link, arms_run)

    if len(dev) < MIN_EVENTS:
        res.verdict = INCONCLUSIVE
        res.note = (f"only {len(dev)} dev announcements with a usable signal "
                    f"(need {MIN_EVENTS}) — underpowered, not refuted")
        return res

    def fit(d: pd.DataFrame, col: str) -> tuple[float, float, int]:
        """Clustered rank IC.

        BOTH sides are ranked within the announcement month, not just the
        signal. Raw SUE is unusable as a regression outcome: on the first real
        sample its 1-99% range was [-5.1, +7.6] and its minimum was -107.9, a
        single Booking Holdings announcement thirty standard deviations out that
        on its own sets the slope of an OLS fit. Ranking the outcome is inside
        L2's pre-registration — the link names "rank IC" as its outcome — so this
        is the specified estimator rather than a repair made after seeing a
        number.
        """
        g = d.groupby("period")
        x = g[col].transform(_rank).to_numpy()
        y = g["sue"].transform(_rank).to_numpy()
        return _cluster_t(y, x, d["period"].to_numpy())

    eff, t, ncl = fit(dev, "g_product")
    res.effect, res.t_stat = eff, t
    peff, pt, _ = fit(dev.dropna(subset=["g_company"]), "g_company")
    res.placebo_t, res.control_effect = pt, peff

    # Permutation control: shuffle the signal within each announcement month,
    # many times. A single draw was the first design and it is too weak — one
    # permutation of a noisy panel returned |t| = 1.57 on the smoke sample, which
    # tells you nothing about whether 1.57 is a normal draw or an alarming one.
    # The distribution answers that directly, and using its 95th percentile as
    # the threshold is strictly HARDER to pass than the single-draw version, so
    # adding it after the smoke run cannot flatter the result.
    rng = np.random.default_rng(23)
    perm_t = []
    for _ in range(200):
        sh = dev.copy()
        sh["g_product"] = sh.groupby("period")["g_product"].transform(
            lambda s: rng.permutation(s.to_numpy()))
        _, pt_i, _ = fit(sh, "g_product")
        if np.isfinite(pt_i):
            perm_t.append(abs(pt_i))
    perm_t = np.array(perm_t) if perm_t else np.array([np.nan])
    sht = float(np.nanpercentile(perm_t, 95)) if perm_t.size else float("nan")
    perm_p = (float(np.mean(perm_t >= abs(t))) if perm_t.size and np.isfinite(t)
              else float("nan"))

    veff, vt, _ = fit(vault, "g_product") if len(vault) >= 60 else (np.nan, np.nan, 0)
    res.vault_effect, res.vault_t = veff, vt

    # The announcement return, reported but NOT a second kill criterion. L2's
    # outcome names both SUE and the 3-day return, and letting either one
    # trigger a pass would be two bites at the apple dressed as one test. SUE is
    # primary because it is the mechanism the thesis actually asserts —
    # attention leads FUNDAMENTALS. The return is corroboration: if attention
    # predicts the surprise but not the reaction to it, the market already knew.
    car_t = float("nan")
    if "car" in dev and dev["car"].notna().sum() >= 200:
        d = dev.dropna(subset=["car"])
        g = d.groupby("period")
        _, car_t, _ = _cluster_t(g["car"].transform(_rank).to_numpy(),
                                 g["g_product"].transform(_rank).to_numpy(),
                                 d["period"].to_numpy())

    res.detail = {"clusters": ncl, "n_dev": int(len(dev)), "n_vault": int(len(vault)),
                  "shuffle_t": sht, "placebo_effect": peff,
                  "perm_p_value": perm_p, "perm_median_abs_t": float(np.nanmedian(perm_t)),
                  "perm_draws": int(perm_t.size), "announcement_return_t": car_t,
                  "dev_span": [str(dev["date"].min().date()), str(dev["date"].max().date())],
                  "tickers": int(dev["ticker"].nunique()), "spec": spec.__dict__}

    reasons = []
    if not np.isfinite(t) or abs(t) < res.bar:
        reasons.append(f"|t| {abs(t):.2f} < bar {res.bar:.2f}")
    if link.direction and np.isfinite(t) and np.sign(t) != link.direction:
        reasons.append(f"sign {np.sign(t):+.0f} against pre-registered {link.direction:+d}")
    if np.isfinite(pt) and abs(pt) >= abs(t):
        reasons.append(f"company-page placebo fires as hard (|t| {abs(pt):.2f} >= {abs(t):.2f})")
    if np.isfinite(perm_p) and perm_p > 0.05:
        reasons.append(f"permutation p {perm_p:.3f} > 0.05 "
                       f"(|t| {abs(t):.2f} vs shuffled 95th pct {sht:.2f})")
    if np.isfinite(vt) and np.isfinite(t) and np.sign(vt) != np.sign(t):
        reasons.append("sign flips on the vault")

    if reasons:
        res.verdict = FAILS
        res.note = "; ".join(reasons)
    else:
        res.verdict = HOLDS
        res.note = (f"t {t:+.2f} > bar {res.bar:.2f}, placebo {pt:+.2f}, "
                    f"permutation p {perm_p:.3f}, vault t {vt:+.2f}")
    return res
