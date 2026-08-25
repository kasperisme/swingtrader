"""The middle layer, and the test of whether one can exist.

The load-bearing test is `test_learnability_finds_a_planted_edge`: a
learnability test that cannot detect a real, learnable edge proves nothing when
it comes back empty. Its mirror, `test_learnability_is_a_coin_flip_on_noise`,
is what makes the empty answer mean something.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.features import FeatureBank
from strategylab.pipeline.attainability import (LabelSpec, build_dataset,
                                                learnability_test, oracle_bound)


def _panel(n=1400, m=60, seed=0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.018, (n, m))
    close = 40.0 * np.exp(np.cumsum(r, axis=0))
    spread = np.abs(rng.normal(0, 0.01, close.shape))
    high, low = close * (1 + spread), close * (1 - spread)
    open_ = np.clip(close * (1 + rng.normal(0, 0.004, close.shape)), low, high)
    dates = pd.bdate_range("2012-01-02", periods=n).values.astype("datetime64[D]")
    syms = [f"L{i:02d}" for i in range(m)] + ["SPY"]
    bench = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.009, n)))
    close = np.column_stack([close, bench])
    high = np.column_stack([high, bench * 1.004])
    low = np.column_stack([low, bench * 0.996])
    open_ = np.column_stack([open_, bench])
    vol = rng.lognormal(14.0, 0.4, close.shape)
    p = Panel(dates=dates, symbols=syms, open=open_, high=high, low=low,
              close=close, volume=vol)
    return p, FeatureBank(p, benchmark_close=bench)


def _mask(panel):
    m = np.zeros(panel.close.shape, dtype=bool)
    m[300:-40, :-1] = True          # exclude the benchmark column
    return m


def test_build_dataset_labels_forward_excess_over_the_benchmark():
    panel, bank = _panel()
    feats = {"f": np.asarray(bank.get("ret", days=5), dtype=float)}
    df = build_dataset(panel, bank, _mask(panel), feats, LabelSpec(horizon=10))
    assert len(df) > 5000
    assert set(["day", "col", "excess", "beat", "f"]).issubset(df.columns)
    assert df["beat"].isin([0, 1]).all()
    assert abs(df["beat"].mean() - (df["excess"] > 0).mean()) < 1e-12


def test_dataset_never_labels_from_the_present_bar():
    """Features are as-of t; the label starts at the open of t+1."""
    panel, bank = _panel()
    feats = {"f": np.asarray(bank.get("ret", days=5), dtype=float)}
    spec = LabelSpec(horizon=10)
    base = build_dataset(panel, bank, _mask(panel), feats, spec)
    K = 900
    px = panel.close.copy()
    rng = np.random.default_rng(3)
    fac = np.ones(panel.close.shape)
    fac[K + 1:] = np.exp(np.cumsum(rng.normal(0, 0.05, fac[K + 1:].shape), axis=0))
    later = Panel(dates=panel.dates, symbols=list(panel.symbols),
                  open=panel.open * fac, high=panel.high * fac,
                  low=panel.low * fac, close=px * fac, volume=panel.volume)
    after = build_dataset(later, FeatureBank(later, benchmark_close=later.close[:, -1]),
                          _mask(panel), {"f": np.asarray(
                              FeatureBank(later).get("ret", days=5), dtype=float)}, spec)
    a = base[base["day"] < K - spec.horizon - 2][["day", "col", "f"]].reset_index(drop=True)
    b = after[after["day"] < K - spec.horizon - 2][["day", "col", "f"]].reset_index(drop=True)
    ok = np.isfinite(a["f"]) & np.isfinite(b["f"])
    assert ok.sum() > 100
    assert np.allclose(a["f"][ok], b["f"][ok]), "a feature peeked past its own bar"


def test_oracle_bound_brackets_random_selection():
    panel, bank = _panel()
    feats = {"f": np.asarray(bank.get("ret", days=5), dtype=float)}
    df = build_dataset(panel, bank, _mask(panel), feats, LabelSpec(horizon=10))
    o = oracle_bound(df)
    assert o["available"]
    assert o["oracle_top_decile_excess"] > o["mean_excess_random"]
    assert o["oracle_bottom_decile_excess"] < o["mean_excess_random"]
    assert o["oracle_spread"] > 0
    assert 0.3 < o["base_rate_beat"] < 0.7


def _split(panel, spec):
    n = panel.close.shape[0]
    return int(n * 0.65) - spec.embargo_days, int(n * 0.70)


def test_learnability_finds_a_planted_edge():
    """A test that cannot detect a real edge proves nothing when it is empty."""
    pytest.importorskip("sklearn")
    panel, bank = _panel(seed=5)
    spec = LabelSpec(horizon=10, sample_every=1)
    mask = _mask(panel)
    feats = {"noise": np.asarray(bank.get("ret", days=5), dtype=float)}
    df = build_dataset(panel, bank, mask, feats, spec)
    # Plant a feature that genuinely carries the label.
    rng = np.random.default_rng(9)
    df["cheat"] = df["beat"] + rng.normal(0, 0.45, len(df))
    tr, te = _split(panel, spec)
    r = learnability_test(df, ["noise", "cheat"], spec, tr, te)
    assert r["available"]
    assert r["auc_test"] > 0.75, f"planted edge not detected: AUC {r['auc_test']:.3f}"


def test_learnability_is_a_coin_flip_on_noise():
    """THE test. With nothing to learn, the model must come back at 0.50."""
    pytest.importorskip("sklearn")
    panel, bank = _panel(seed=6)
    spec = LabelSpec(horizon=10, sample_every=1)
    mask = _mask(panel)
    rng = np.random.default_rng(11)
    feats = {f"n{i}": rng.normal(size=panel.close.shape) for i in range(6)}
    df = build_dataset(panel, bank, mask, feats, spec)
    tr, te = _split(panel, spec)
    r = learnability_test(df, list(feats), spec, tr, te)
    assert r["available"]
    assert abs(r["auc_test"] - 0.5) < 0.05, f"AUC {r['auc_test']:.3f} on pure noise"


def test_shuffled_label_control_is_reported():
    """Anything above 0.5 on shuffled labels is leakage, not skill — the
    control is what certifies the embargo actually worked."""
    pytest.importorskip("sklearn")
    panel, bank = _panel(seed=7)
    spec = LabelSpec(horizon=10, sample_every=1)
    rng = np.random.default_rng(13)
    feats = {f"n{i}": rng.normal(size=panel.close.shape) for i in range(4)}
    df = build_dataset(panel, bank, _mask(panel), feats, spec)
    tr, te = _split(panel, spec)
    r = learnability_test(df, list(feats), spec, tr, te)
    assert abs(r["auc_test_shuffled_labels"] - 0.5) < 0.06


def test_embargo_separates_train_from_test():
    panel, bank = _panel()
    spec = LabelSpec(horizon=10, embargo_days=21)
    feats = {"f": np.asarray(bank.get("ret", days=5), dtype=float)}
    df = build_dataset(panel, bank, _mask(panel), feats, spec)
    tr, te = _split(panel, spec)
    assert te - tr >= spec.embargo_days
    assert df[df["day"] <= tr]["day"].max() + spec.embargo_days <= te
