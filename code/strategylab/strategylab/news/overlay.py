"""News signals aligned onto the price panel, and an honest statement of power.

The pipeline starts 2025-04-10. That is the single most important fact about
this data and it constrains everything: sixteen months, entirely inside the
period the rest of the project reserved as its vault, with the NIS impact scores
covering only the last four and a half.

Sixteen months of daily cross-sections sounds like a lot and is not. A 21-day
forward return sampled daily gives roughly sixteen INDEPENDENT observations, so
the sample can only resolve a large effect. `minimum_detectable_ic` states how
large before any test is run, because a null on an underpowered sample means
"we could not see it", not "it is not there" — and those get confused precisely
when the answer is inconvenient.

Four signals are built, and they are deliberately different in kind:

    news_sentiment    article-weighted rolling mean score
    news_attention    article count — the Da/Engelberg/Gao attention channel,
                      which is a distinct claim from sentiment and not obviously
                      correlated with it
    news_surprise     attention against the name's OWN trailing normal, so a
                      permanently newsworthy mega-cap does not read as a
                      permanent signal
    news_sentiment_delta   change in sentiment, not its level
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..data.news import NewsStore

log = logging.getLogger(__name__)

NEWS_SIGNALS = ("news_sentiment", "news_attention", "news_surprise",
                "news_sentiment_delta")


def build_news_matrices(panel, lookback: int = 5, surprise_window: int = 63,
                        store: NewsStore | None = None) -> dict[str, np.ndarray]:
    """(n_days, n_symbols) matrices, NaN wherever there is no coverage.

    NaN means "no evidence" and must never be read as zero or as neutral: a name
    nobody wrote about is not a name with neutral news, and collapsing the two
    would hand the signal a spurious cross-section made of silence.
    """
    store = store or NewsStore()
    df = store.load()
    n, m = panel.close.shape
    out = {k: np.full((n, m), np.nan) for k in NEWS_SIGNALS}
    if df is None or df.empty:
        log.warning("no news cache — run the news sync first")
        return out

    grid = pd.DatetimeIndex(panel.dates)
    df = df[df["ticker"].isin(set(panel.symbols))]
    if df.empty:
        return out

    sent = df.pivot_table(index="trade_date", columns="ticker",
                          values="mean_sentiment", aggfunc="mean") \
             .reindex(index=grid, columns=panel.symbols)
    cnt = df.pivot_table(index="trade_date", columns="ticker",
                         values="n_articles", aggfunc="sum") \
            .reindex(index=grid, columns=panel.symbols)

    lo, hi = df["trade_date"].min(), df["trade_date"].max()
    covered = (grid >= lo) & (grid <= hi)

    # Inside the coverage window a day with no article is a real zero for
    # attention; outside it, nothing is known at all.
    cnt_z = cnt.copy()
    cnt_z.loc[covered] = cnt_z.loc[covered].fillna(0.0)

    num = (sent * cnt).rolling(lookback, min_periods=1).sum()
    den = cnt_z.rolling(lookback, min_periods=1).sum()
    roll_sent = num / den.replace(0.0, np.nan)
    roll_cnt = den

    normal = cnt_z.rolling(surprise_window, min_periods=20).mean().shift(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        surprise = roll_cnt / normal.replace(0.0, np.nan)

    prev_sent = roll_sent.shift(lookback)

    out["news_sentiment"] = np.array(roll_sent.to_numpy(dtype=np.float64), copy=True)
    out["news_attention"] = np.array(roll_cnt.to_numpy(dtype=np.float64), copy=True)
    out["news_surprise"] = np.array(surprise, dtype=np.float64, copy=True)
    out["news_sentiment_delta"] = np.array(
        (roll_sent - prev_sent).to_numpy(dtype=np.float64), copy=True)

    blind = ~covered
    for k in out:
        out[k][blind, :] = np.nan
    return out


def coverage_report(panel, mask: np.ndarray, mats: dict) -> dict:
    """How much of the tradeable universe the news pipeline actually sees.

    A signal present on a tenth of the cross-section cannot rank it, whatever
    its information content, so this decides whether the test is worth running
    before the test is run.

    "Seen" means the name actually had an article, not merely that the window
    was open. Inside the coverage window a name with no news gets attention 0
    rather than NaN — which is correct for the signal and wrong for a coverage
    statistic, and an earlier version of this function conflated the two and
    reported 100% coverage when the true figure was far lower.
    """
    att = mats["news_attention"]
    in_window = np.isfinite(att) & mask
    have = in_window & (att > 0)
    per_day = have.sum(axis=1)
    uni_per_day = mask.sum(axis=1)
    live = uni_per_day > 0
    with np.errstate(invalid="ignore", divide="ignore"):
        share = np.where(live, per_day / np.maximum(uni_per_day, 1), np.nan)
    covered_days = np.flatnonzero(np.isfinite(att).any(axis=1))
    win_per_day = in_window.sum(axis=1)
    return {
        "first_covered_session": str(panel.dates[covered_days[0]]) if covered_days.size else None,
        "last_covered_session": str(panel.dates[covered_days[-1]]) if covered_days.size else None,
        "covered_sessions": int(covered_days.size),
        "median_universe_names_with_news": float(np.nanmedian(per_day[covered_days]))
        if covered_days.size else 0.0,
        "median_share_of_universe_with_news": float(np.nanmedian(share[covered_days]))
        if covered_days.size else 0.0,
        "median_universe_names_in_window": float(np.nanmedian(win_per_day[covered_days]))
        if covered_days.size else 0.0,
    }


def minimum_detectable_ic(n_sessions: int, horizon: int, ic_sd: float = 0.12,
                          power_t: float = 2.0) -> dict:
    """The smallest IC this sample could resolve — computed BEFORE testing.

    Overlapping forward returns mean the effective sample is roughly
    `n_sessions / horizon` independent observations, not `n_sessions`. Stating
    the floor in advance is what stops an underpowered null being reported as
    evidence of absence.
    """
    eff = max(1.0, n_sessions / max(1, horizon))
    se = ic_sd / np.sqrt(eff)
    return {"sessions": int(n_sessions), "horizon": horizon,
            "effective_independent_obs": round(eff, 1),
            "ic_se": round(float(se), 4),
            "min_detectable_ic": round(float(power_t * se), 4),
            "note": ("An IC below this floor is invisible to this sample. A null "
                     "here means 'not resolvable', not 'not present'.")}
