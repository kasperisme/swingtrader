"""
Embeddings maintenance CLI.

Usage examples:
  python -m news_impact.embeddings_cli --enqueue-missing --limit 500
  python -m news_impact.embeddings_cli --process-pending --limit 100
  python -m news_impact.embeddings_cli --process-pending --retry-failed --limit 200
  python -m news_impact.embeddings_cli --cleanup-orphans
"""

from __future__ import annotations

import argparse
import logging
import pathlib

from dotenv import load_dotenv

from news_impact.embeddings import (
    cleanup_embedding_orphans,
    enqueue_missing_embedding_jobs,
    process_embedding_jobs,
)

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m news_impact.embeddings_cli",
        description="Queue/process/cleanup article embeddings",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enqueue-missing", action="store_true", help="Enqueue rows missing embedding jobs")
    mode.add_argument("--process-pending", action="store_true", help="Process queued embedding jobs")
    mode.add_argument("--cleanup-orphans", action="store_true", help="Delete orphan embeddings/jobs")
    parser.add_argument("--limit", type=int, default=100, help="Max rows/jobs to process")
    parser.add_argument("--retry-failed", action="store_true", help="Include failed jobs when processing")
    parser.add_argument("--embed-model", default=None, help="Override OLLAMA_EMBED_MODEL")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout seconds")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    try:
        from src.health import JobHeartbeat
        _heartbeat = JobHeartbeat
    except ImportError:
        from contextlib import nullcontext as _heartbeat  # type: ignore[assignment]

    if args.enqueue_missing:
        with _heartbeat("embeddings_enqueue", expected_interval_h=24.0):
            n = enqueue_missing_embedding_jobs(limit=args.limit)
            print(f"enqueued_missing={n}")
        return

    if args.process_pending:
        job_name = "embeddings_retry" if args.retry_failed else "embeddings_process"
        interval = 24.0 if args.retry_failed else 10 / 60  # 10 min in fractional hours
        with _heartbeat(job_name, expected_interval_h=interval):
            ok, bad = process_embedding_jobs(
                limit=args.limit,
                retry_failed=bool(args.retry_failed),
                model=args.embed_model,
                timeout=float(args.timeout),
            )
            print(f"completed={ok} failed={bad}")
        return

    with _heartbeat("embeddings_cleanup", expected_interval_h=168.0):  # weekly
        deleted_emb, deleted_jobs = cleanup_embedding_orphans()
        print(f"deleted_embeddings={deleted_emb} deleted_jobs={deleted_jobs}")


if __name__ == "__main__":
    main()
