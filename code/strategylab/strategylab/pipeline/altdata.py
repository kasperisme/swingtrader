"""Information the price panel does not contain: analyst revisions and SUE.

The attainability test established that outperformance is unpredictable from
price, volume, size, sector and the three fundamentals already wired up — AUC
0.494 out of sample from a learner that can represent interactions. The
conclusion was that a middle layer needs *different information*, not a better
model. These are the two axes with enough history on this data plan to test:

  **Analyst grade changes** (2012 onward, ~100 a year per name). The revision
  anomaly is one of the better-documented in the literature, and a grade change
  is genuinely exogenous to the price series — an analyst's opinion is not a
  transformation of past returns.

  **Standardised unexpected earnings** (1995 onward, quarterly). The canonical
  PEAD measure, and the one the news-repricing study explicitly did NOT test:
  it used the announcement-window return as its surprise proxy instead, which
  is price-derived and therefore not new information at all.

Both are aligned point-in-time on their publication or announcement date and
made usable only from the FOLLOWING session, because a grade published during
the day is not tradeable at that morning's open.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import CACHE_ROOT

log = logging.getLogger(__name__)

# A grade change only means something on a scale. Anything unrecognised is
# dropped rather than guessed at — an unmapped grade silently scored as neutral
# would turn real revisions into non-events.
GRADE_SCALE = {
    "strong sell": 1, "sell": 1, "reduce": 1, "underperform": 2, "underweight": 2,
    "negative": 2, "sector underperform": 2, "market underperform": 2,
    "hold": 3, "neutral": 3, "market perform": 3, "sector perform": 3,
    "equal-weight": 3, "equal weight": 3, "in-line": 3, "peer perform": 3,
    "buy": 4, "outperform": 4, "overweight": 4, "accumulate": 4, "add": 4,
    "positive": 4, "sector outperform": 4, "market outperform": 4,
    "strong buy": 5, "conviction buy": 5, "top pick": 5,
}


def _grade(x) -> float:
    if not isinstance(x, str):
        return np.nan
    return GRADE_SCALE.get(x.strip().lower(), np.nan)


def load_grade_events(symbols: list[str], cache: Path | None = None) -> pd.DataFrame:
    """One row per grade change with a signed direction."""
    d = Path(cache or (CACHE_ROOT / "grades"))
    rows = []
    for s in symbols:
        p = d / f"{s.replace('.', '-')}.json"
        if not p.exists():
            continue
        try:
            recs = json.loads(p.read_text())
        except Exception:
            continue
        for r in recs or []:
            new, old = _grade(r.get("newGrade")), _grade(r.get("previousGrade"))
            if not np.isfinite(new):
                continue
            rows.append({"symbol": s, "date": r.get("date"), "new": new, "old": old,
                         "delta": (new - old) if np.isfinite(old) else 0.0})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_localize(None)
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def load_surprises(symbols: list[str], cache: Path | None = None) -> pd.DataFrame:
    """Announcement-date earnings surprises."""
    d = Path(cache or (CACHE_ROOT / "surprises"))
    rows = []
    for s in symbols:
        p = d / f"{s.replace('.', '-')}.json"
        if not p.exists():
            continue
        try:
            recs = json.loads(p.read_text())
        except Exception:
            continue
        for r in recs or []:
            a, e = r.get("actualEarningResult"), r.get("estimatedEarning")
            if a is None or e is None:
                continue
            rows.append({"symbol": s, "date": r.get("date"),
                         "actual": float(a), "estimate": float(e)})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values(["symbol", "date"]).reset_index(drop=True)


def grade_matrices(panel, events: pd.DataFrame, windows=(21, 63)) -> dict:
    """Net and gross revision activity over trailing windows.

    Shifted by one session: a grade published on day t is actionable at the open
    of t+1, not at the open of t.
    """
    n, m = panel.close.shape
    out = {}
    if events.empty:
        for w in windows:
            out[f"grade_net_{w}d"] = np.full((n, m), np.nan)
            out[f"grade_count_{w}d"] = np.full((n, m), np.nan)
        out["grade_level"] = np.full((n, m), np.nan)
        return out

    grid = pd.DatetimeIndex(panel.dates)
    col = {s: j for j, s in enumerate(panel.symbols)}
    net = np.zeros((n, m))
    cnt = np.zeros((n, m))
    lvl = np.full((n, m), np.nan)
    pos = np.searchsorted(grid.values, events["date"].values, side="left")
    for p, j, dl, nw in zip(pos, events["symbol"].map(col), events["delta"], events["new"]):
        if not np.isfinite(j) or p >= n:
            continue
        j = int(j)
        net[p, j] += dl
        cnt[p, j] += 1.0
        lvl[p, j] = nw

    for w in windows:
        out[f"grade_net_{w}d"] = pd.DataFrame(net).rolling(w, min_periods=1).sum().shift(1).to_numpy()
        out[f"grade_count_{w}d"] = pd.DataFrame(cnt).rolling(w, min_periods=1).sum().shift(1).to_numpy()
    out["grade_level"] = pd.DataFrame(lvl).ffill(limit=252).shift(1).to_numpy()
    # Names never covered stay NaN rather than zero: no coverage is not "no
    # revisions", and the difference decides whether the feature can rank them.
    seen = cnt.cumsum(axis=0) > 0
    for k in out:
        out[k] = np.where(seen, out[k], np.nan)
    return out


def sue_matrix(panel, surprises: pd.DataFrame, lookback: int = 8) -> dict:
    """Standardised unexpected earnings, forward-filled from the announcement.

    Standardised by the dispersion of the name's OWN past surprises, which is
    what makes a 2c beat on a stable earner different from a 2c beat on a
    volatile one. Uses only prior surprises, so it is point-in-time.
    """
    n, m = panel.close.shape
    out = {"sue": np.full((n, m), np.nan), "surprise_pct": np.full((n, m), np.nan)}
    if surprises.empty:
        return out
    grid = pd.DatetimeIndex(panel.dates)
    col = {s: j for j, s in enumerate(panel.symbols)}

    for sym, g in surprises.groupby("symbol"):
        j = col.get(sym)
        if j is None or len(g) < 3:
            continue
        g = g.sort_values("date")
        diff = (g["actual"] - g["estimate"]).to_numpy(dtype=float)
        sd = pd.Series(diff).rolling(lookback, min_periods=3).std().shift(1).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            sue = np.where(np.isfinite(sd) & (sd > 0), diff / sd, np.nan)
            pct = np.where(np.abs(g["estimate"].to_numpy()) > 1e-9,
                           diff / np.abs(g["estimate"].to_numpy()), np.nan)
        pos = np.searchsorted(grid.values, g["date"].values, side="left")
        for p, s_, pc in zip(pos, sue, pct):
            if p + 1 >= n:
                continue
            out["sue"][p + 1:, j] = s_        # usable from the next session
            out["surprise_pct"][p + 1:, j] = pc
    return out


# ----------------------------------------------------------------------
# SEC insider transactions (Form 4), free from EDGAR back to 2006.
# ----------------------------------------------------------------------
INSIDER_ABSURD_VALUE = 1e11
"""A single reported leg above $100bn is a filing error, not a trade.

400 of 867,270 legs (0.046%) come back between $1tn and $21 QUADRILLION —
mis-keyed share counts and malformed price fields, which SEC publishes as
filed. Left in, they dominate every aggregate: the raw total insider purchase
value across twenty years computes to $58 quadrillion against a true figure
near $6.5tn.
"""


def load_insider(cache: Path | None = None) -> pd.DataFrame:
    """Per-ticker, per-filing-date open-market purchases and sales.

    Keyed on FILING DATE rather than transaction date: a Form 4 becomes public
    when it is filed, and that is the first moment the information could have
    been acted on. Only transaction codes P and S are kept — grants, option
    exercises and gifts dominate the raw file and are compensation mechanics
    rather than opinions about value.
    """
    d = Path(cache or (CACHE_ROOT / "insider"))
    files = sorted(d.glob("*.csv.gz"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    if df.empty:
        return df
    df["filing_date"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df = df.dropna(subset=["filing_date", "ticker"])
    for c in ("buy_value", "sell_value", "officer_buy", "director_buy"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        df.loc[df[c] > INSIDER_ABSURD_VALUE, c] = np.nan
    return df


def insider_matrices(panel, ins: pd.DataFrame, adv: np.ndarray,
                     windows=(63, 126)) -> dict:
    """Insider activity scaled by the name's own turnover.

    Raw dollars cannot be compared across a $2bn company and a $2tn one, so
    every measure is divided by trailing dollar volume: "how many days of this
    stock's own turnover did insiders buy". Purchases are kept SEPARATE from
    the net, because the literature is consistent that purchases carry
    information and sales are dominated by diversification and liquidity — a
    net figure blends a signal with noise and reports the average.
    """
    n, m = panel.close.shape
    out: dict[str, np.ndarray] = {}
    keys = []
    for w in windows:
        keys += [f"insider_buy_{w}d", f"insider_net_{w}d", f"insider_buyers_{w}d"]
    keys += ["insider_officer_buy_63d", "insider_buy_share_126d"]
    for k in keys:
        out[k] = np.full((n, m), np.nan)
    if ins.empty:
        return out

    grid = pd.DatetimeIndex(panel.dates)
    col = {s: j for j, s in enumerate(panel.symbols)}
    ins = ins[ins["ticker"].isin(col)]
    if ins.empty:
        return out

    buy = np.zeros((n, m)); sell = np.zeros((n, m))
    nbuy = np.zeros((n, m)); off = np.zeros((n, m))
    pos = np.searchsorted(grid.values, ins["filing_date"].values, side="left")
    js = ins["ticker"].map(col).to_numpy()
    for p, j, b, s_, nb, o in zip(pos, js, ins["buy_value"], ins["sell_value"],
                                  ins["n_buys"], ins["officer_buy"]):
        if p >= n:
            continue
        j = int(j)
        if np.isfinite(b):
            buy[p, j] += b
        if np.isfinite(s_):
            sell[p, j] += s_
        if np.isfinite(nb):
            nbuy[p, j] += nb
        if np.isfinite(o):
            off[p, j] += o

    advz = np.where(np.isfinite(adv) & (adv > 0), adv, np.nan)
    for w in windows:
        rb = pd.DataFrame(buy).rolling(w, min_periods=1).sum().shift(1).to_numpy()
        rs = pd.DataFrame(sell).rolling(w, min_periods=1).sum().shift(1).to_numpy()
        rn = pd.DataFrame(nbuy).rolling(w, min_periods=1).sum().shift(1).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            out[f"insider_buy_{w}d"] = rb / (advz * w)
            out[f"insider_net_{w}d"] = (rb - rs) / (advz * w)
        out[f"insider_buyers_{w}d"] = rn
        if w == 126:
            with np.errstate(invalid="ignore", divide="ignore"):
                tot = rb + rs
                out["insider_buy_share_126d"] = np.where(tot > 0, rb / tot, np.nan)
    ro = pd.DataFrame(off).rolling(63, min_periods=1).sum().shift(1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        out["insider_officer_buy_63d"] = ro / (advz * 63)

    # A name EDGAR has never carried a Form 4 for is unknown, not inactive.
    seen = (buy + sell).cumsum(axis=0) > 0
    for k in out:
        out[k] = np.where(seen, out[k], np.nan)
    return out
