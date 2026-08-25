"""The event-study core: abnormal returns, announcement windows, and drift.

Three design choices carry the honesty of the whole thing.

**The announcement window straddles the date.** FMP gives a calendar date but
not reliably whether the release was before the open or after the close, and
that one bit moves the reaction by a full session. Rather than guess, the
surprise is measured as the cumulative abnormal return over [D-1, D+1], which
contains the reaction either way, and the outcome starts at D+2. Nothing has to
be inferred about timing.

**The surprise is a return, the outcome is a later return.** The two share no
day. This is the same forward-control structure the pairs study used and the
thing the flow Stage-1 lacked, and it is what makes the test non-circular.

**Ranking is against a trailing distribution.** Deciles are cut from the
previous 12 months of announcements, recomputed monthly, so an event is never
sorted against events that had not happened yet. Sorting within a calendar
quarter — the convenient thing — is look-ahead, and on a drift study it is
worth roughly the size of the effect.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class EventSpec:
    """The event protocol. Frozen for a study."""

    ear_lead: int = 1                    # announcement window is [D-lead, D+lag]
    ear_lag: int = 1
    entry_lag: int = 2                   # fill at the OPEN of D+entry_lag
    drift_horizons: tuple = (5, 21, 63)
    primary_horizon: int = 21
    beta_window: int = 250
    beta_gap: int = 11                   # beta estimated up to D-gap
    min_beta_obs: int = 120
    min_price: float = 1.0               # $1, not $5 — the edge may live small
    min_adv_usd: float = 0.0             # tiers are reported, not filtered
    rank_lookback_days: int = 365        # trailing calendar days for the deciles
    min_rank_events: int = 500
    n_buckets: int = 10
    cost_bps_per_side: float = 13.0      # one leg, so a round trip is 2x this
    # Pseudo-events must sit clear of any real announcement or they measure the
    # very thing they are the control for.
    pseudo_min_gap: int = 20
    pseudo_seed: int = 41
    # Outlier treatment. NOT optional and NOT a tuning knob: the raw panel
    # contains unadjusted corporate actions (a +39,900% 21-day "return" on QUBT,
    # five separate 100x moves on WSE) that are data errors rather than prices.
    # One of them shifts a decile mean of ~6,000 events by 6.6 percentage
    # points, which is larger than any effect being measured. Thresholds are cut
    # on the COMBINED real+pseudo sample so both get identical treatment.
    winsorize_pct: float = 0.01
    absurd_return: float = 2.0           # |21d return| beyond this is reported


# ----------------------------------------------------------------------
def _rolling_sums(X: np.ndarray, w: int):
    """Trailing sums and valid-observation counts, NaN-safe, via cumsum.

    pandas' rolling is expressive but this runs over ~17M cells and gets called
    on four matrices; the cumsum form is the difference between seconds and
    minutes.
    """
    V = np.isfinite(X)
    Z = np.where(V, X, 0.0)
    cs = np.cumsum(Z, axis=0)
    cn = np.cumsum(V.astype(np.float64), axis=0)
    pad = np.zeros((1, X.shape[1]))
    cs = np.vstack([pad, cs])
    cn = np.vstack([pad, cn])
    lo = np.maximum(0, np.arange(X.shape[0] + 1) - w)
    s = cs - cs[lo]
    n = cn - cn[lo]
    return s[1:], n[1:]


def market_model(panel, market: str = "SPY", spec: EventSpec | None = None):
    """Rolling-beta abnormal returns.

    Returns (abnormal, beta, sigma_ab, market_returns). Beta on day t is
    estimated from the `beta_window` sessions ENDING AT t-1, so it never uses
    the day it adjusts.
    """
    spec = spec or EventSpec()
    close = panel.close
    prev = np.vstack([np.full((1, close.shape[1]), np.nan), close[:-1]])
    R = close / prev - 1.0

    if market in panel.symbols:
        m = R[:, panel.symbols.index(market)]
    else:
        log.warning("%s not in the panel — falling back to the equal-weight "
                    "cross-section as the market proxy", market)
        m = np.nanmean(R, axis=1)
    M = np.repeat(m[:, None], R.shape[1], axis=1)
    M = np.where(np.isfinite(R), M, np.nan)

    w = spec.beta_window
    sx, n = _rolling_sums(M, w)
    sy, _ = _rolling_sums(R, w)
    sxy, _ = _rolling_sums(M * R, w)
    sxx, _ = _rolling_sums(M * M, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - (sx / n) * (sy / n)
        var = sxx / n - (sx / n) ** 2
        beta = np.where((n >= spec.min_beta_obs) & (var > 0), cov / var, np.nan)
    # Shift so day t uses estimates through t-1.
    beta = np.vstack([np.full((1, beta.shape[1]), np.nan), beta[:-1]])
    beta = np.clip(beta, -3.0, 4.0)

    AB = R - beta * M
    sab, nab = _rolling_sums(AB, w)
    sab2, _ = _rolling_sums(AB * AB, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        var_ab = sab2 / nab - (sab / nab) ** 2
        sigma = np.where((nab >= spec.min_beta_obs) & (var_ab > 0), np.sqrt(var_ab), np.nan)
    sigma = np.vstack([np.full((1, sigma.shape[1]), np.nan), sigma[:-1]])
    return AB, beta, sigma, m


def _event_rows(panel, day_idx: np.ndarray, col_idx: np.ndarray, AB, beta, sigma,
                m: np.ndarray, adv: np.ndarray, spec: EventSpec) -> pd.DataFrame:
    """Vectorised extraction of surprise, drift and tradeable return."""
    T, N = AB.shape
    open_, close = panel.open, panel.close
    d, j = day_idx, col_idx

    def win_sum(mat, lo, hi):
        """Sum of mat[d+lo : d+hi+1, j] for every event, NaN-safe."""
        out = np.zeros(len(d))
        cnt = np.zeros(len(d))
        for k in range(lo, hi + 1):
            t = d + k
            ok = (t >= 0) & (t < T)
            v = np.full(len(d), np.nan)
            v[ok] = mat[t[ok], j[ok]]
            good = np.isfinite(v)
            out[good] += v[good]
            cnt += good
        return out, cnt

    ear_raw, ear_n = win_sum(AB, -spec.ear_lead, spec.ear_lag)
    width = spec.ear_lead + spec.ear_lag + 1
    sig = np.full(len(d), np.nan)
    ok = (d - spec.ear_lead - 1 >= 0)
    sig[ok] = sigma[d[ok] - spec.ear_lead - 1, j[ok]]
    with np.errstate(invalid="ignore", divide="ignore"):
        ear = np.where((ear_n == width) & np.isfinite(sig) & (sig > 0),
                       ear_raw / (sig * np.sqrt(width)), np.nan)

    out = {"day": d, "col": j, "ear": ear, "ear_raw": ear_raw}
    for H in spec.drift_horizons:
        car, car_n = win_sum(AB, spec.entry_lag, spec.entry_lag + H - 1)
        out[f"car_{H}"] = np.where(car_n >= max(2, int(0.6 * H)), car, np.nan)

    # Tradeable: open of D+entry_lag to open of D+entry_lag+H, market-hedged
    # with the same beta the abnormal return used.
    b = np.full(len(d), np.nan)
    ok = (d >= 0) & (d < T)
    b[ok] = beta[d[ok], j[ok]]
    mkt_level = np.nancumprod(np.where(np.isfinite(m), 1.0 + m, 1.0))

    def price_at(offset, mat):
        t = d + offset
        ok = (t >= 0) & (t < T)
        v = np.full(len(d), np.nan)
        v[ok] = mat[t[ok], j[ok]]
        return v, t, ok

    p0, t0, ok0 = price_at(spec.entry_lag, open_)
    for H in spec.drift_horizons:
        p1, t1, ok1 = price_at(spec.entry_lag + H, open_)
        with np.errstate(invalid="ignore", divide="ignore"):
            raw = p1 / p0 - 1.0
        mk = np.full(len(d), np.nan)
        both = ok0 & ok1
        mk[both] = mkt_level[t1[both]] / mkt_level[t0[both]] - 1.0
        out[f"ret_{H}"] = raw - b * mk
        out[f"raw_{H}"] = raw

    out["beta"] = b
    px = np.full(len(d), np.nan)
    px[ok] = close[d[ok], j[ok]]
    out["price"] = px
    av = np.full(len(d), np.nan)
    av[ok] = adv[d[ok], j[ok]]
    out["adv"] = av
    out["date"] = panel.dates[np.clip(d, 0, T - 1)]
    out["symbol"] = np.array(panel.symbols, dtype=object)[j]
    return pd.DataFrame(out)


def _map_dates(panel, dates: list, symbol_col: int) -> np.ndarray:
    grid = np.asarray(panel.dates, dtype="datetime64[D]")
    arr = np.array([np.datetime64(pd.Timestamp(x).date()) for x in dates],
                   dtype="datetime64[D]")
    return np.searchsorted(grid, arr, side="left")


def build_events(panel, earnings: dict, spec: EventSpec, AB=None, beta=None,
                 sigma=None, m=None, adv=None) -> pd.DataFrame:
    """One row per earnings announcement with a usable measurement window."""
    if AB is None:
        AB, beta, sigma, m = market_model(panel, spec=spec)
    if adv is None:
        adv = pd.DataFrame(panel.close * panel.volume).rolling(
            20, min_periods=10).mean().to_numpy()

    T = AB.shape[0]
    days, cols = [], []
    col_of = {s: k for k, s in enumerate(panel.symbols)}
    grid = np.asarray(panel.dates, dtype="datetime64[D]")
    lo_bound = spec.beta_window + spec.beta_gap
    hi_bound = T - (spec.entry_lag + max(spec.drift_horizons) + 1)
    for sym, dts in earnings.items():
        j = col_of.get(sym)
        if j is None or not dts:
            continue
        arr = np.array([np.datetime64(pd.Timestamp(x).date()) for x in dts],
                       dtype="datetime64[D]")
        pos = np.searchsorted(grid, arr, side="left")
        keep = (pos >= lo_bound) & (pos < hi_bound)
        days.append(pos[keep])
        cols.append(np.full(keep.sum(), j))
    if not days:
        return pd.DataFrame()

    d = np.concatenate(days)
    j = np.concatenate(cols)
    df = _event_rows(panel, d, j, AB, beta, sigma, m, adv, spec)
    df = df[np.isfinite(df["ear"]) & np.isfinite(df["price"])
            & (df["price"] >= spec.min_price)]
    return df.sort_values("date").reset_index(drop=True)


def pseudo_events(panel, earnings: dict, spec: EventSpec, AB, beta, sigma, m,
                  adv, tiers: np.ndarray | None = None) -> pd.DataFrame:
    """THE control: identical measurement, same day, no announcement.

    For every real announcement (symbol S, day D) a substitute is drawn from
    the names that (a) traded on D, (b) had no announcement within
    `pseudo_min_gap` sessions of D, and (c) sit in the same liquidity tier as S
    on that day. Every quantity is then computed by the same code.

    Matching on the DAY is what makes this a control rather than a curiosity.
    An earlier version drew random days from each symbol's own history, which
    scattered the controls across the calendar while real announcements cluster
    into four seasons a year — the two samples then barely shared any months and
    the comparison lost most of its power. Same day, same tier, different name
    holds the market environment fixed and leaves exactly one thing varying:
    whether anything was announced.

    Whatever drift-after-a-large-abnormal-move survives here is momentum,
    volatility clustering and the CAR construction. It is the number the real
    effect has to beat.
    """
    rng = np.random.default_rng(spec.pseudo_seed)
    T, N = AB.shape
    col_of = {s: k for k, s in enumerate(panel.symbols)}
    grid = np.asarray(panel.dates, dtype="datetime64[D]")
    lo_bound = spec.beta_window + spec.beta_gap
    hi_bound = T - (spec.entry_lag + max(spec.drift_horizons) + 1)

    blocked = np.zeros((T, N), dtype=bool)
    real_days, real_cols = [], []
    for sym, dts in earnings.items():
        j = col_of.get(sym)
        if j is None or not dts:
            continue
        arr = np.array([np.datetime64(pd.Timestamp(x).date()) for x in dts],
                       dtype="datetime64[D]")
        pos = np.searchsorted(grid, arr, side="left")
        for p in pos[(pos >= 0) & (pos < T)]:
            blocked[max(0, p - spec.pseudo_min_gap):
                    min(T, p + spec.pseudo_min_gap + 1), j] = True
        keep = (pos >= lo_bound) & (pos < hi_bound)
        real_days.append(pos[keep])
        real_cols.append(np.full(int(keep.sum()), j))
    if not real_days:
        return pd.DataFrame()

    rd = np.concatenate(real_days)
    rc = np.concatenate(real_cols)
    if tiers is None:
        tiers = liquidity_tier(adv)
    avail = np.isfinite(panel.close) & ~blocked

    order = np.lexsort((rc, rd))
    rd, rc = rd[order], rc[order]
    days, cols = [], []
    i = 0
    while i < len(rd):
        d = rd[i]
        k = i
        while k < len(rd) and rd[k] == d:
            k += 1
        want_tiers = tiers[d, rc[i:k]]
        pool = np.flatnonzero(avail[d])
        if pool.size:
            pool_tiers = tiers[d, pool]
            for tier in np.unique(want_tiers):
                need = int((want_tiers == tier).sum())
                cand = pool[pool_tiers == tier]
                if cand.size == 0:
                    continue
                pick = rng.choice(cand, size=min(need, cand.size), replace=False)
                days.append(np.full(pick.size, d))
                cols.append(pick)
        i = k
    if not days:
        return pd.DataFrame()

    d = np.concatenate(days)
    j = np.concatenate(cols)
    df = _event_rows(panel, d, j, AB, beta, sigma, m, adv, spec)
    df = df[np.isfinite(df["ear"]) & np.isfinite(df["price"])
            & (df["price"] >= spec.min_price)]
    return df.sort_values("date").reset_index(drop=True)


# ----------------------------------------------------------------------
def assign_buckets(df: pd.DataFrame, spec: EventSpec, col: str = "ear") -> pd.DataFrame:
    """Decile the surprise against a TRAILING distribution, recut monthly.

    Cutting deciles inside a calendar quarter — the convenient thing — sorts an
    event against announcements that had not happened yet. On a drift study that
    look-ahead is worth roughly the size of the effect being measured.
    """
    d = df.dropna(subset=[col]).copy()
    if d.empty:
        return d.assign(bucket=np.nan)
    d["_month"] = pd.PeriodIndex(pd.to_datetime(d["date"]), freq="M")
    months = np.sort(d["_month"].unique())
    dates = pd.to_datetime(d["date"])
    vals = d[col].to_numpy()
    bucket = np.full(len(d), np.nan)

    for mth in months:
        end = mth.to_timestamp()
        start = end - pd.Timedelta(days=spec.rank_lookback_days)
        hist = vals[(dates < end) & (dates >= start)]
        if hist.size < spec.min_rank_events:
            continue
        edges = np.quantile(hist, np.linspace(0, 1, spec.n_buckets + 1)[1:-1])
        sel = (d["_month"] == mth).to_numpy()
        bucket[sel] = np.searchsorted(edges, vals[sel], side="right")

    d["bucket"] = bucket
    return d.drop(columns=["_month"])


def winsorize(real: pd.DataFrame, fake: pd.DataFrame, spec: EventSpec) -> dict:
    """Clip return columns at symmetric percentiles of the pooled sample.

    Applied in place to both frames, with one set of thresholds, so the control
    can never be trimmed differently from the thing it controls for. Returns the
    thresholds and the contamination counts, which belong in the report — a
    result that depends on the winsorisation level is not a result.
    """
    info: dict = {"pct": spec.winsorize_pct, "thresholds": {}, "absurd": {}}
    for h in spec.drift_horizons:
        for col in (f"ret_{h}", f"car_{h}", f"raw_{h}"):
            if col not in real.columns:
                continue
            pooled = pd.concat([real[col], fake[col]]).dropna()
            if pooled.empty:
                continue
            lo = float(pooled.quantile(spec.winsorize_pct))
            hi = float(pooled.quantile(1 - spec.winsorize_pct))
            n_ab = int((pooled.abs() > spec.absurd_return).sum())
            real[col] = real[col].clip(lo, hi)
            fake[col] = fake[col].clip(lo, hi)
            info["thresholds"][col] = [lo, hi]
            if n_ab:
                info["absurd"][col] = n_ab
    return info


def liquidity_tier(adv: np.ndarray) -> np.ndarray:
    """The tiers the whole question turns on: does the edge live where the
    friction does not?"""
    return np.select(
        [adv < 1e6, adv < 1e7, adv < 1e8],
        ["T1_micro_<$1M", "T2_small_$1-10M", "T3_mid_$10-100M"],
        default="T4_large_>$100M")
