"""Admin gating via the ADMIN_USER_IDS env var (comma-separated UUIDs)."""

from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_admin_user_ids() -> frozenset[str]:
    raw = os.environ.get("ADMIN_USER_IDS", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def is_admin(user_id: str | None) -> bool:
    if not user_id:
        return False
    return user_id in get_admin_user_ids()


def assert_is_admin(user_id: str | None) -> None:
    if not is_admin(user_id):
        raise PermissionError("Admin access required")
