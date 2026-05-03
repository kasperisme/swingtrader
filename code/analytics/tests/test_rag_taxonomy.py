"""Invariants on the canonical cluster/dimension taxonomy."""

from services.rag.taxonomy import (
    CLUSTERS,
    CLUSTER_ID_TO_LABEL,
    DIM_KEY_TO_LABEL,
)


def test_nine_clusters():
    assert len(CLUSTERS) == 9


def test_every_cluster_has_id_label_dimensions():
    for c in CLUSTERS:
        assert c["id"]
        assert c["label"]
        assert isinstance(c["dimensions"], list) and len(c["dimensions"]) >= 1


def test_cluster_ids_are_unique():
    ids = [c["id"] for c in CLUSTERS]
    assert len(ids) == len(set(ids))


def test_dimension_keys_are_unique_across_clusters():
    keys = [k for c in CLUSTERS for k, _ in c["dimensions"]]
    assert len(keys) == len(set(keys)), "dimension keys must be unique across all clusters"


def test_cluster_label_map_covers_every_cluster():
    for c in CLUSTERS:
        assert CLUSTER_ID_TO_LABEL[c["id"]] == c["label"]
    assert len(CLUSTER_ID_TO_LABEL) == len(CLUSTERS)


def test_dim_label_map_covers_every_dimension():
    expected = {k: lbl for c in CLUSTERS for k, lbl in c["dimensions"]}
    assert DIM_KEY_TO_LABEL == expected


def test_no_empty_or_whitespace_keys_or_labels():
    for c in CLUSTERS:
        for key, label in c["dimensions"]:
            assert key.strip() == key and key
            assert label.strip() == label and label


def test_known_dimensions_present():
    """Spot-check a handful of dimension keys other code references."""
    expected_present = {
        "interest_rate_sensitivity_duration",
        "sector_technology",
        "revenue_predictability",
        "debt_burden",
        "valuation_multiple",
        "china_revenue_exposure",
        "institutional_appeal",
    }
    assert expected_present.issubset(DIM_KEY_TO_LABEL.keys())
