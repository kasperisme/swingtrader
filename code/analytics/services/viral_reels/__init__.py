"""
viral_reels — data-driven reel generator.

Turns the News Impact Screener data foundation (plus external sources like
FMP price/OHLC) into short vertical "bar chart race" video reels in the style
of r/dataisbeautiful.

Split of responsibilities:
  - Python (this package) — deterministic data acquisition. Builds time-bucketed
    race keyframes from Supabase news-impact views and merges external series.
  - Claude Code (the `viral-reel` skill) — the creative director. Picks the
    story, writes the copy, assembles the final ReelSpec.
  - Remotion (the `reel/` Node project) — renders the ReelSpec to an MP4.

See README.md for the full pipeline and the `viral-reel` skill for orchestration.
"""

from __future__ import annotations

__all__ = ["data_sources", "spec", "story_finder"]
