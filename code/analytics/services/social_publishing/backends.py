"""Aggregator backend interface + selector.

A backend is any module exposing:
    NAME: str
    NEEDS_ACCOUNT_ID: bool
    is_configured() -> bool
    account_id_for(platform: str) -> str | None
    publish(platform, caption, media_urls, kind, *, account_id,
            schedule_at=None) -> PublishResult   # schedule_at: aware UTC datetime
                                                  # or None for immediate publish

Optional (Zernio): best_time_slots(platform, account_id) -> list[dict].

Keeping this contract tiny means the asset/caption layer and the CLI never know
which aggregator is in use — swapping zernio↔ayrshare is one env var.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PublishResult:
    ok: bool
    urls: list[str] = field(default_factory=list)
    detail: str = ""


def get_backend(name: str):
    name = (name or "").lower()
    if name == "zernio":
        from . import zernio
        return zernio
    if name == "ayrshare":
        from . import ayrshare
        return ayrshare
    raise ValueError(
        f"Unknown SOCIAL_BACKEND {name!r}; expected 'zernio' or 'ayrshare'."
    )
