"""Resolve what to post for a ticker from its local ``output/setups/<TICKER>/``.

The folder is produced by the nis-stock-breakdown skill. This module turns it
into one ``PostPlan`` per requested platform — no network, no side effects. The
creative copy stays on disk; we only read it.

Per-platform caption resolution (first that exists wins):
    output/setups/<TICKER>/social/<platform>.txt    ← hand-tuned override
    output/setups/<TICKER>/caption.txt              ← the master caption

Optional override file: output/setups/<TICKER>/social/manifest.json
    {
      "instagram": {"kind": "video",    "media": "reel_chart.mp4"},
      "linkedin":  {"kind": "carousel", "media": ["slides/slide-01.png", ...]}
    }
Anything omitted falls back to the defaults below.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import config

# Reels, in preference order, when a plan asks for "video".
_REEL_CANDIDATES = ("reel_chart.mp4", "reel.mp4")


@dataclass
class PostPlan:
    platform: str
    caption: str
    kind: str                       # "video" | "carousel"
    media: list[Path] = field(default_factory=list)
    caption_source: str = ""        # which file the caption came from (for logs)


def ticker_dir(ticker: str) -> Path:
    d = config.SETUPS_DIR / ticker.upper()
    if not d.is_dir():
        raise FileNotFoundError(
            f"No setup folder for {ticker.upper()} at {d} — run the "
            f"nis-stock-breakdown skill first."
        )
    return d


def _resolve_reel(d: Path) -> Path:
    for name in _REEL_CANDIDATES:
        p = d / name
        if p.is_file():
            return p
    raise FileNotFoundError(
        f"No reel in {d} (looked for {', '.join(_REEL_CANDIDATES)})."
    )


def _resolve_slides(d: Path) -> list[Path]:
    slides = sorted((d / "slides").glob("slide-*.png"))
    if not slides:
        raise FileNotFoundError(f"No carousel slides in {d / 'slides'}.")
    return slides


def _resolve_caption(d: Path, platform: str) -> tuple[str, str]:
    override = d / "social" / f"{platform}.txt"
    master = d / "caption.txt"
    for src in (override, master):
        if src.is_file():
            text = src.read_text(encoding="utf-8").strip()
            if text:
                return text, str(src.relative_to(config.SETUPS_DIR))
    raise FileNotFoundError(
        f"No caption for {platform}: neither {override} nor {master} has text."
    )


def _load_manifest(d: Path) -> dict:
    mf = d / "social" / "manifest.json"
    if mf.is_file():
        return json.loads(mf.read_text(encoding="utf-8"))
    return {}


def _resolve_media(d: Path, kind: str, manifest_media) -> list[Path]:
    """Resolve the media paths for a plan, honouring a manifest override."""
    if manifest_media is not None:
        names = manifest_media if isinstance(manifest_media, list) else [manifest_media]
        paths = [d / n for n in names]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"Manifest media not found: {', '.join(missing)}")
        return paths
    return [_resolve_reel(d)] if kind == "video" else _resolve_slides(d)


def build_plans(ticker: str, platforms: list[str]) -> list[PostPlan]:
    """Build one PostPlan per platform. Raises if any asset is missing."""
    d = ticker_dir(ticker)
    manifest = _load_manifest(d)
    plans: list[PostPlan] = []
    for platform in platforms:
        if platform not in config.PLATFORMS:
            raise ValueError(
                f"Unknown platform {platform!r}; expected one of "
                f"{', '.join(config.PLATFORMS)}."
            )
        entry = manifest.get(platform, {})
        kind = entry.get("kind", config.DEFAULT_KIND[platform])
        if platform == "tiktok" and kind != "video":
            raise ValueError("TikTok supports video only; set kind='video'.")
        caption, caption_src = _resolve_caption(d, platform)
        media = _resolve_media(d, kind, entry.get("media"))
        plans.append(
            PostPlan(
                platform=platform,
                caption=caption,
                kind=kind,
                media=media,
                caption_source=caption_src,
            )
        )
    return plans
