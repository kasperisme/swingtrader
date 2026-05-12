#!/usr/bin/env python3
"""
Cluster news_article_embeddings into hourly or daily UTC buckets.

Uses mean-pooled vectors per article, L2-normalised MiniBatchKMeans, then Ollama /api/chat
to write ``reverse_embedding_text`` per cluster from member chunk excerpts.

Prereq: apply migration 20260512140000_news_embedding_time_clusters.sql
  (hourly + daily cluster_runs / cluster_centroids / cluster_articles tables).

Usage (from code/analytics, after .env with DB creds + Ollama running):
  python scripts/cluster_news_embedding_buckets.py --granularity hour --since 2026-05-10 --until 2026-05-12
  python scripts/cluster_news_embedding_buckets.py --granularity day --since 2026-05-01 --dry-run
  python scripts/cluster_news_embedding_buckets.py --granularity day --since 2026-05-01 --embed-model mxbai-embed-large --label-model llama3.2

Env:
  SUPABASE_SCHEMA (default swingtrader), OLLAMA_EMBED_MODEL (default mxbai-embed-large),
  SUPABASE_DB_DIRECT_URL or SUPABASE_URL + SUPABASE_DB_PWD
  OLLAMA_BASE_URL (default http://localhost:11434)
  OLLAMA_CLUSTER_LABEL_MODEL (else OLLAMA_IMPACT_MODEL, OLLAMA_NARRATIVE_MODEL, else llama3.2)
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

from dotenv import load_dotenv

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_REPO_ROOT / ".env")
sys.path.insert(0, str(_REPO_ROOT))

from services.news.embeddings.time_bucket_clustering import run_cli  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--granularity",
        choices=("hour", "day"),
        required=True,
        help="UTC hour buckets or UTC calendar-day buckets",
    )
    p.add_argument(
        "--since",
        required=True,
        help="ISO date (YYYY-MM-DD) or datetime; start of range (inclusive-ish: first bucket may begin at UTC floor before this moment)",
    )
    p.add_argument(
        "--until",
        default=None,
        help="ISO date or datetime (default: now UTC). Range is [since, until).",
    )
    p.add_argument(
        "--embed-model",
        default=None,
        help="Must match news_article_embeddings.embedding_model (default: OLLAMA_EMBED_MODEL or mxbai-embed-large)",
    )
    p.add_argument("--max-k", type=int, default=40, help="Cap on cluster count")
    p.add_argument(
        "--min-per-cluster",
        type=int,
        default=5,
        help="Heuristic target minimum articles per cluster when choosing k",
    )
    p.add_argument("--random-state", type=int, default=42)
    p.add_argument("--dry-run", action="store_true", help="Do not write DB; print plan only")
    p.add_argument(
        "--label-model",
        default=None,
        help="Ollama chat model for cluster labels (default: OLLAMA_CLUSTER_LABEL_MODEL or OLLAMA_IMPACT_MODEL …)",
    )
    p.add_argument(
        "--ollama-base-url",
        default=None,
        help="Ollama base URL (default: OLLAMA_BASE_URL or http://localhost:11434)",
    )
    p.add_argument(
        "--ollama-timeout",
        type=float,
        default=120.0,
        help="Seconds per Ollama /api/chat call (each cluster = one call)",
    )
    p.add_argument(
        "--max-cluster-chars",
        type=int,
        default=14_000,
        help="Max characters of chunk excerpts sent to the label model per cluster",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    out = run_cli(
        granularity=args.granularity,
        since=args.since,
        until=args.until,
        embedding_model=args.embed_model,
        max_k=int(args.max_k),
        min_per_cluster=int(args.min_per_cluster),
        random_state=int(args.random_state),
        dry_run=bool(args.dry_run),
        label_model=args.label_model,
        ollama_base_url=args.ollama_base_url,
        ollama_timeout=float(args.ollama_timeout),
        max_cluster_prompt_chars=int(args.max_cluster_chars),
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
