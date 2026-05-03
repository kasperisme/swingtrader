"""Pure-function tests for compute_cluster_summary aggregation."""

from services.rag.sentiment import compute_cluster_summary


def test_empty_inputs():
    out = compute_cluster_summary([], [])
    assert out["cluster_ranking"] == []
    assert out["top_dimensions"] == []
    assert out["total_articles"] == 0


def test_dedupes_cluster_rows_by_keeping_first_occurrence():
    """Multiple rows for the same cluster_id collapse to the first one seen."""
    rows = [
        {"cluster_id": "MACRO_SENSITIVITY", "cluster_weighted_avg": 0.9, "bucket_article_count": 5},
        {"cluster_id": "MACRO_SENSITIVITY", "cluster_weighted_avg": 0.1, "bucket_article_count": 1},
    ]
    out = compute_cluster_summary(rows, [])
    assert len(out["cluster_ranking"]) == 1
    assert out["cluster_ranking"][0]["score"] == 0.9


def test_cluster_ranking_sorted_by_absolute_score():
    rows = [
        {"cluster_id": "A", "cluster_weighted_avg": 0.4, "bucket_article_count": 2},
        {"cluster_id": "B", "cluster_weighted_avg": -0.9, "bucket_article_count": 3},
        {"cluster_id": "C", "cluster_weighted_avg": 0.6, "bucket_article_count": 1},
    ]
    out = compute_cluster_summary(rows, [])
    ordered_ids = [r["cluster"] for r in out["cluster_ranking"]]
    assert ordered_ids == ["B", "C", "A"]      # |−0.9| > |0.6| > |0.4|


def test_cluster_label_falls_back_to_taxonomy_when_missing():
    rows = [{"cluster_id": "MACRO_SENSITIVITY", "cluster_weighted_avg": 0.5, "bucket_article_count": 1}]
    out = compute_cluster_summary(rows, [])
    assert out["cluster_ranking"][0]["label"] == "Macro Sensitivity"


def test_top_dimensions_requires_at_least_two_articles():
    """A dimension only ranks if it appears in >= 2 articles."""
    articles = [
        {"impact_json": {"interest_rate_sensitivity_duration": 0.9}},
        {"impact_json": {"sector_technology": 0.8}},
        {"impact_json": {"sector_technology": 0.6}},
    ]
    out = compute_cluster_summary([], articles)
    keys = {d["key"] for d in out["top_dimensions"]}
    assert "sector_technology" in keys                          # appears twice
    assert "interest_rate_sensitivity_duration" not in keys     # appears once


def test_top_dimensions_ranked_by_absolute_average():
    articles = [
        {"impact_json": {"a": 0.2, "b": -0.9}},
        {"impact_json": {"a": 0.4, "b": -0.7}},
    ]
    out = compute_cluster_summary([], articles)
    ordered_keys = [d["key"] for d in out["top_dimensions"]]
    assert ordered_keys[0] == "b"     # avg = -0.8 (|.8|)
    assert ordered_keys[1] == "a"     # avg =  0.3 (|.3|)


def test_top_dimensions_capped_at_six():
    articles = [
        {"impact_json": {f"dim_{i}": 0.5 for i in range(20)}},
        {"impact_json": {f"dim_{i}": 0.6 for i in range(20)}},
    ]
    out = compute_cluster_summary([], articles)
    assert len(out["top_dimensions"]) == 6


def test_non_numeric_impact_values_are_ignored():
    articles = [
        {"impact_json": {"a": 0.5, "b": "not a number", "c": None}},
        {"impact_json": {"a": 0.7}},
    ]
    out = compute_cluster_summary([], articles)
    keys = {d["key"] for d in out["top_dimensions"]}
    assert "a" in keys
    assert "b" not in keys and "c" not in keys


def test_total_articles_counts_input_length():
    articles = [{"impact_json": {}}, {"impact_json": {}}, {"impact_json": {"a": 0.1}}]
    assert compute_cluster_summary([], articles)["total_articles"] == 3
