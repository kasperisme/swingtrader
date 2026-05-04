#!/usr/bin/env python3
"""
Verify the new Supabase-backed podcast publishing path end-to-end.

Run this after applying the two migrations to confirm:
  ✓ env vars present
  ✓ podcast_episodes has the new RSS columns
  ✓ podcast storage bucket exists, is public, accepts service-role writes
  ✓ uploaded objects are reachable at their public URL (no auth)
  ✓ podcast_episodes upsert + select round-trips
  ✓ analytics-side imports the new publisher cleanly

Usage:
    cd code/analytics
    .venv/bin/python scripts/verify_podcast_setup.py
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


_PASS = "\033[32m✓\033[0m"
_FAIL = "\033[31m✗\033[0m"
_INFO = "  "


def _check(label: str, ok: bool, detail: str = "") -> bool:
    icon = _PASS if ok else _FAIL
    print(f"{icon} {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    failures: list[str] = []

    # ── 1. env vars ─────────────────────────────────────────────────────
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    bucket = os.environ.get("PODCAST_STORAGE_BUCKET", "podcast")

    if not _check("SUPABASE_URL set", bool(url)):
        failures.append("SUPABASE_URL")
    if not _check("SUPABASE_KEY set (service role)", bool(key)):
        failures.append("SUPABASE_KEY")
    if failures:
        print("\nSet env vars in .env first.")
        return 1

    # ── 2. Supabase client ──────────────────────────────────────────────
    from shared.db import get_supabase_client
    try:
        client = get_supabase_client()
        _check("Supabase client connected", True)
    except Exception as exc:
        _check("Supabase client connected", False, str(exc))
        return 1

    # ── 3. podcast_episodes table has the new columns ───────────────────
    required_cols = {
        "audio_url", "cover_url", "file_size_bytes",
        "guid", "published_at", "description",
    }
    try:
        # Selecting the columns will 400 if any are missing.
        cols = ", ".join(sorted(required_cols))
        client.schema("swingtrader").table("podcast_episodes").select(cols).limit(0).execute()
        _check(f"podcast_episodes has columns {sorted(required_cols)}", True)
    except Exception as exc:
        _check("podcast_episodes has new RSS columns", False, str(exc))
        print(f"{_INFO}→ run migration 20260504_podcast_episodes_rss_columns.sql")
        failures.append("schema")

    # ── 4. Bucket exists ────────────────────────────────────────────────
    try:
        buckets = client.storage.list_buckets()
        names = {b.name for b in buckets} if buckets else set()
        if bucket in names:
            _check(f"Bucket '{bucket}' exists", True)
        else:
            _check(f"Bucket '{bucket}' exists", False, f"found: {sorted(names) or 'none'}")
            print(f"{_INFO}→ run migration 20260504_podcast_storage_bucket.sql")
            failures.append("bucket")
    except Exception as exc:
        _check(f"Bucket '{bucket}' exists", False, str(exc))
        failures.append("bucket")

    if "bucket" in failures or "schema" in failures:
        return 1

    # ── 5. Round-trip an upload ─────────────────────────────────────────
    # Bucket policy restricts MIMEs to audio/mpeg + image/png + image/jpeg,
    # so use a minimal valid 1×1 PNG (67 bytes) for the round-trip.
    storage = client.storage.from_(bucket)
    test_key = f"_verify/setup_{uuid.uuid4().hex[:8]}.png"
    test_body = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360606060000000050001a5f645400000000049454e44"
        "ae426082"
    )

    try:
        storage.upload(
            path=test_key,
            file=test_body,
            file_options={"content-type": "image/png", "upsert": "true"},
        )
        _check(f"Service-role upload to {bucket}/{test_key}", True)
    except Exception as exc:
        _check("Service-role upload", False, str(exc))
        return 1

    public_url = storage.get_public_url(test_key)
    _check(f"Public URL generated: {public_url[:80]}…", bool(public_url))

    # ── 6. Public fetch (no auth) ───────────────────────────────────────
    try:
        import urllib.request
        with urllib.request.urlopen(public_url, timeout=10) as resp:
            body = resp.read()
        if body == test_body:
            _check("Public URL fetch returns uploaded bytes (no auth)", True)
        else:
            _check("Public URL fetch byte-for-byte", False, "content mismatch")
            failures.append("public-fetch")
    except Exception as exc:
        _check("Public URL fetch", False, str(exc))
        failures.append("public-fetch")

    # ── 7. podcast_episodes upsert + read ───────────────────────────────
    test_guid = f"verify-{uuid.uuid4()}"
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        client.schema("swingtrader").table("podcast_episodes").upsert({
            "date": today,
            "title": "[verify] setup smoke test",
            "description": "ephemeral row written by verify_podcast_setup.py",
            "audio_url": public_url,
            "cover_url": public_url,
            "duration_seconds": 0,
            "file_size_bytes": len(test_body),
            "guid": test_guid,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "verify",   # not "published" so it never shows in the feed
        }, on_conflict="guid").execute()

        rows = (
            client.schema("swingtrader").table("podcast_episodes")
            .select("guid, audio_url")
            .eq("guid", test_guid)
            .execute()
        ).data or []
        if rows and rows[0]["audio_url"] == public_url:
            _check("podcast_episodes upsert + read round-trip", True)
        else:
            _check("podcast_episodes round-trip", False, f"got {rows!r}")
            failures.append("db-round-trip")
    except Exception as exc:
        _check("podcast_episodes upsert", False, str(exc))
        failures.append("db-round-trip")

    # ── 8. supabase_publisher imports cleanly ───────────────────────────
    try:
        from services.podcast.supabase_publisher import publish_episode  # noqa: F401
        _check("services.podcast.supabase_publisher imports cleanly", True)
    except Exception as exc:
        _check("supabase_publisher imports", False, str(exc))
        failures.append("imports")

    # ── 9. Cleanup ──────────────────────────────────────────────────────
    print()
    try:
        storage.remove([test_key])
        client.schema("swingtrader").table("podcast_episodes").delete().eq("guid", test_guid).execute()
        _check("Cleanup (test object + row removed)", True)
    except Exception as exc:
        _check("Cleanup", False, str(exc))

    print()
    if failures:
        print(f"\033[31m{len(failures)} check(s) failed:\033[0m {', '.join(failures)}")
        return 1
    print("\033[32mAll checks passed. Pipeline is ready to publish.\033[0m")
    print(f"Feed URL once an episode is published:")
    print("  https://newsimpactscreener.com/podcast/feed.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
