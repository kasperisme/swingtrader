"""Cluster + dimension glossary for podcast agents.

Derives plain-English definitions from the canonical news-scoring source
(``services.news.scoring.dimensions``) so producer, researcher, and writer
agents can translate internal taxonomy labels into listener-friendly
meaning instead of speaking raw labels and decimals on air.
"""

from __future__ import annotations

from functools import lru_cache

from services.news.scoring.dimensions import CLUSTERS as _SCORING_CLUSTERS
from services.rag.taxonomy import CLUSTER_ID_TO_LABEL


@lru_cache(maxsize=1)
def build_taxonomy_glossary() -> str:
    """Render the cluster/dimension glossary as a stable text block.

    Each cluster is followed by its component dimensions and the
    description copied verbatim from the news-scoring definitions. The
    block is safe to splice into Jinja templates or f-string system
    prompts.
    """
    sections: list[str] = []
    for cluster_id, dims in _SCORING_CLUSTERS.items():
        cluster_label = CLUSTER_ID_TO_LABEL.get(
            cluster_id, cluster_id.replace("_", " ").title()
        )
        lines: list[str] = [f"CLUSTER — {cluster_label}"]
        for d in dims:
            lines.append(f"  - {d['label']}: {d['description']}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
