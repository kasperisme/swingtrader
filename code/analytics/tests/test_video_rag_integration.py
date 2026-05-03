"""Integration tests: services.video <-> services.rag wiring.

The video service should import taxonomy and retrieval functions from RAG
rather than redefining them. Verifies the data_fetcher delegates correctly.
"""

from unittest import mock

from services.video import config as video_config
from services.video import data_fetcher as video_df
from services.rag import taxonomy as rag_taxonomy
from services.rag import (
    compute_cluster_summary as rag_compute_cluster_summary,
    fetch_tickers_for_articles as rag_fetch_tickers_for_articles,
)


# ── taxonomy is re-exported from RAG, not redefined ────────────────────────

def test_video_clusters_are_rag_clusters():
    assert video_config.CLUSTERS is rag_taxonomy.CLUSTERS


def test_video_dim_label_map_is_rag_map():
    assert video_config.DIM_KEY_TO_LABEL is rag_taxonomy.DIM_KEY_TO_LABEL


def test_video_cluster_id_map_is_rag_map():
    assert video_config.CLUSTER_ID_TO_LABEL is rag_taxonomy.CLUSTER_ID_TO_LABEL


# ── data_fetcher delegates to RAG, not its own queries ─────────────────────

def test_compute_cluster_summary_is_rag_function():
    assert video_df.compute_cluster_summary is rag_compute_cluster_summary


def test_fetch_tickers_for_articles_is_rag_function():
    assert video_df.fetch_tickers_for_articles is rag_fetch_tickers_for_articles


def test_fetch_top_articles_passes_through_to_rag_with_video_defaults():
    sentinel = [{"id": 1}, {"id": 2}]
    with mock.patch.object(video_df, "get_top_articles", return_value=sentinel) as m:
        out = video_df.fetch_top_articles(max_articles=5)
    m.assert_called_once_with(hours=video_config.LOOKBACK_HOURS, limit=5)
    assert out is sentinel


def test_fetch_top_articles_uses_video_max_articles_when_omitted():
    with mock.patch.object(video_df, "get_top_articles", return_value=[]) as m:
        video_df.fetch_top_articles()
    _, kwargs = m.call_args
    assert kwargs["limit"] == video_config.MAX_ARTICLES


def test_fetch_cluster_trends_passes_through_to_rag():
    sentinel = [{"cluster_id": "MACRO_SENSITIVITY"}]
    with mock.patch.object(video_df, "get_cluster_trends", return_value=sentinel) as m:
        out = video_df.fetch_cluster_trends(hours=42)
    m.assert_called_once_with(hours=42)
    assert out is sentinel


def test_fetch_cluster_trends_uses_video_lookback_when_omitted():
    with mock.patch.object(video_df, "get_cluster_trends", return_value=[]) as m:
        video_df.fetch_cluster_trends()
    _, kwargs = m.call_args
    assert kwargs["hours"] == video_config.LOOKBACK_HOURS


def test_data_fetcher_public_api():
    """The video service exposes exactly the functions other code imports."""
    assert set(video_df.__all__) == {
        "fetch_cluster_trends",
        "fetch_top_articles",
        "fetch_tickers_for_articles",
        "compute_cluster_summary",
    }
