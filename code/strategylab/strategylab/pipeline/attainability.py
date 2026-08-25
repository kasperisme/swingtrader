"""Is outperformance learnable from what we can observe at the time?

Two bounds, in order.

**The oracle.** Label every eligible name-day by whether it beat the benchmark
over the swing horizon, then ask what perfect selection would have earned. This
is the ceiling on any middle layer — no selection rule can do better than
picking the winners with hindsight. If the ceiling is low the layer is not worth
building however good the model; if it is high, the question becomes how much is
reachable.

**The model.** Fit a gradient-boosted classifier on every feature at once and
score it on data separated from training by time and an embargo. This is the
first test in the project that can see interactions, and it is the right way to
ask "is there anything here" rather than "does this one thing work".

The embargo is not decoration. Labels are forward returns over H days, so a
training row from day t and a test row from day t+1 share H-1 days of outcome.
Without a gap the model is scored partly on what it memorised, and a
look-ahead-free AUC becomes an inflated one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class LabelSpec:
    horizon: int = 10                 # swing-trading holding period, sessions
    benchmark: str = "SPY"
    embargo_days: int = 21            # gap between train and test
    min_names_per_day: int = 30
    sample_every: int = 3             # thin the panel; adjacent days are near-duplicates


def build_dataset(panel, bank, mask: np.ndarray, features: dict,
                  spec: LabelSpec) -> pd.DataFrame:
    """One row per (eligible name, sampled day) with features as-of t and the
    forward label from t+1.

    Fills at the open of t+1 and exits at the open of t+1+H, matching every
    other study here, so a positive result would be tradeable rather than
    merely true.
    """
    open_ = panel.open
    n, m = open_.shape
    j_b = panel.symbols.index(spec.benchmark)
    H = spec.horizon

    with np.errstate(invalid="ignore", divide="ignore"):
        fwd = np.full((n, m), np.nan)
        fwd[:n - H - 1] = open_[H + 1:n, :] / open_[1:n - H, :] - 1.0
        b = np.full(n, np.nan)
        b[:n - H - 1] = open_[H + 1:n, j_b] / open_[1:n - H, j_b] - 1.0

    excess = fwd - b[:, None]
    rows, cols = np.where(mask & np.isfinite(excess))
    keep = (rows % spec.sample_every) == 0
    rows, cols = rows[keep], cols[keep]
    if rows.size == 0:
        return pd.DataFrame()

    data = {"day": rows, "col": cols, "excess": excess[rows, cols],
            "beat": (excess[rows, cols] > 0).astype(int)}
    for name, mat in features.items():
        data[name] = mat[rows, cols]
    df = pd.DataFrame(data)
    counts = df.groupby("day")["col"].transform("size")
    return df[counts >= spec.min_names_per_day].reset_index(drop=True)


def oracle_bound(df: pd.DataFrame, top_frac: float = 0.1) -> dict:
    """What perfect selection would earn — the ceiling on any middle layer.

    Also reports the *random* baseline, because the gap between them is the
    entire prize. A layer can only ever capture part of that gap.
    """
    if df.empty:
        return {"available": False}
    per_day = df.groupby("day")["excess"]
    rand = float(df["excess"].mean())
    top = float(per_day.apply(lambda s: s.nlargest(max(1, int(len(s) * top_frac))).mean()).mean())
    bot = float(per_day.apply(lambda s: s.nsmallest(max(1, int(len(s) * top_frac))).mean()).mean())
    return {
        "available": True,
        "base_rate_beat": float(df["beat"].mean()),
        "mean_excess_random": rand,
        "oracle_top_decile_excess": top,
        "oracle_bottom_decile_excess": bot,
        "oracle_spread": top - bot,
        "prize_over_random": top - rand,
        "n": int(len(df)),
        "note": ("The oracle uses hindsight and is unreachable. It is the ceiling: "
                 "no middle layer can capture more than the gap between it and "
                 "random selection."),
    }


def learnability_test(df: pd.DataFrame, feature_names: list[str], spec: LabelSpec,
                      train_end: int, test_start: int, seed: int = 7) -> dict:
    """Fit on the past, score on the future, with an embargo between.

    Reports AUC on held-out data plus the realised excess return of the model's
    top decile, which is the number that matters — an AUC of 0.53 that produces
    no return is a statistic, not a layer.
    """
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.metrics import roc_auc_score
    except ImportError:
        return {"available": False, "reason": "scikit-learn not installed"}

    train = df[df["day"] <= train_end]
    test = df[df["day"] >= test_start]
    if len(train) < 5000 or len(test) < 1000:
        return {"available": False, "reason": f"train {len(train)}, test {len(test)}"}

    X_tr = train[feature_names].to_numpy(dtype=np.float64)
    X_te = test[feature_names].to_numpy(dtype=np.float64)
    y_tr = train["beat"].to_numpy()
    y_te = test["beat"].to_numpy()

    model = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_depth=4,
        l2_regularization=1.0, early_stopping=True, validation_fraction=0.15,
        random_state=seed)
    model.fit(X_tr, y_tr)
    p_te = model.predict_proba(X_te)[:, 1]
    p_tr = model.predict_proba(X_tr)[:, 1]

    out = {
        "available": True,
        "n_train": int(len(train)), "n_test": int(len(test)),
        "features": len(feature_names),
        "auc_train": float(roc_auc_score(y_tr, p_tr)),
        "auc_test": float(roc_auc_score(y_te, p_te)),
        "base_rate_test": float(y_te.mean()),
        "embargo_days": spec.embargo_days,
    }

    # The number that decides it: what the model's own top decile actually earned.
    t = test.assign(_p=p_te)
    top = t.groupby("day").apply(
        lambda g: g.nlargest(max(1, len(g) // 10), "_p")["excess"].mean(),
        include_groups=False)
    bot = t.groupby("day").apply(
        lambda g: g.nsmallest(max(1, len(g) // 10), "_p")["excess"].mean(),
        include_groups=False)
    out |= {
        "model_top_decile_excess": float(top.mean()),
        "model_bottom_decile_excess": float(bot.mean()),
        "model_spread": float(top.mean() - bot.mean()),
        "random_excess": float(test["excess"].mean()),
    }

    # A label-shuffled control. Anything above 0.5 here is leakage, not skill.
    rng = np.random.default_rng(seed + 1)
    shuffled = HistGradientBoostingClassifier(
        max_iter=120, learning_rate=0.05, max_depth=4, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15, random_state=seed)
    shuffled.fit(X_tr, rng.permutation(y_tr))
    out["auc_test_shuffled_labels"] = float(
        roc_auc_score(y_te, shuffled.predict_proba(X_te)[:, 1]))
    return out
