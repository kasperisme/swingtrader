"""Tests for chart publication.

The thing being protected here is the labelling. An equity curve drawn on the
optimisation window is persuasive and wrong, and it is the artifact most likely
to be screenshotted away from its caption — so the tests assert that it cannot
reach the catalogue without being marked in-sample, and that a chart whose
filename nobody has written a caption for is skipped rather than published bare.
"""

from __future__ import annotations

import pytest

from strategylab.autonomous.charts_publish import (
    FLOW_REGISTRY, REGISTRY, ChartPublisher, _slug)
from strategylab.autonomous.publish import ResearchPublisher

# Every chart filename the writers in strategylab/charts.py emit.
EMITTED = {"perf_equity", "perf_folds", "perf_trades", "perf_sides",
           "perf_exposure", "search_reward", "search_sources", "search_operators"}


class FakeCursor:
    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.sink.append((sql, params))
    def fetchone(self): return (4,)


class FakeConn:
    def __init__(self): self.calls, self.commits = [], 0
    def cursor(self): return FakeCursor(self.calls)
    def commit(self): self.commits += 1


class FakeStorage:
    def __init__(self): self.uploaded = []
    def upload(self, path, file, file_options): self.uploaded.append(path)
    def get_public_url(self, key): return f"https://example.test/{key}"


@pytest.fixture
def cp():
    pub = ResearchPublisher(schema="swingtrader")
    pub._conn = FakeConn()
    c = ChartPublisher(pub, bucket="research")
    c._storage = lambda: FakeStorage()          # type: ignore[method-assign]
    return c


def test_every_emitted_chart_has_a_caption():
    """A chart the code can produce but cannot describe would publish unlabelled."""
    assert EMITTED <= set(REGISTRY), f"uncaptioned: {EMITTED - set(REGISTRY)}"


def test_equity_curve_is_marked_in_sample():
    assert REGISTRY["perf_equity"].sample_window == "dev"
    cap = REGISTRY["perf_equity"].caption
    assert "upper bound" in cap and "not a forecast" in cap


def test_performance_charts_are_all_dev_window():
    """None of the performance charts are drawn on unseen data, so none may
    claim to be."""
    for name in ("perf_equity", "perf_folds", "perf_trades", "perf_exposure"):
        assert REGISTRY[name].sample_window == "dev"


def test_search_diagnostics_are_not_return_series():
    for name in ("search_reward", "search_sources", "search_operators"):
        assert REGISTRY[name].sample_window == "n/a"


def test_all_captions_are_substantive():
    for name, meta in {**REGISTRY, **FLOW_REGISTRY}.items():
        assert len(meta.caption) > 60, f"{name} caption is too thin to stand alone"
        assert meta.title and meta.kind


def test_window_values_match_the_check_constraint():
    allowed = {"dev", "holdout", "vault", "full", "n/a"}
    for meta in {**REGISTRY, **FLOW_REGISTRY}.values():
        assert meta.sample_window in allowed


def test_unregistered_chart_is_skipped_not_published(cp, tmp_path, caplog):
    run = tmp_path / "evolve9"
    (run / "charts").mkdir(parents=True)
    (run / "charts" / "perf_equity.png").write_bytes(b"\x89PNG fake")
    (run / "charts" / "mystery_plot.png").write_bytes(b"\x89PNG fake")

    slugs = cp.publish_run_charts(run, trials=743)
    assert slugs == ["evolve9-perf-equity"]
    assert "mystery_plot" not in " ".join(slugs)


def test_registered_chart_carries_trials_and_window(cp, tmp_path):
    run = tmp_path / "evolve6"
    (run / "charts").mkdir(parents=True)
    (run / "charts" / "perf_equity.png").write_bytes(b"\x89PNG fake")
    cp.publish_run_charts(run, trials=151, genome_hash="abc123")

    sql, params = cp.pub._conn.calls[-1]
    assert "research_charts" in sql
    assert "dev" in params, "the in-sample window must be recorded"
    assert 151 in params, "the trial count must travel with the picture"
    assert "abc123" in params


def test_charts_default_to_draft(cp, tmp_path):
    run = tmp_path / "evolve6"
    (run / "charts").mkdir(parents=True)
    (run / "charts" / "perf_folds.png").write_bytes(b"x")
    cp.publish_run_charts(run, trials=10)
    params = cp.pub._conn.calls[-1][1]
    # published sits before (width, height), which were added later so the
    # figures could reserve layout space.
    assert params[-3] is False


def test_slug_is_stable_and_url_safe():
    assert _slug("evolve6", "perf_equity") == "evolve6-perf-equity"
    assert _slug("flow", "tier2_rho") == "flow-tier2-rho"
