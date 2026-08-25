"""Generate and deliver one briefing PDF to a subscriber."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from shared.email import (
    build_briefing_manage_url,
    build_briefing_unsubscribe_url,
    build_signin_url,
    send_email,
)

from .action import choose_action
from .data import gather_briefing
from .narrative import add_narratives
from .render import render_briefing_email_html, render_briefing_pdf

log = logging.getLogger(__name__)


def _subject(briefing: dict[str, Any], tickers: list[str], tags: list[str]) -> str:
    bits = [f"${t}" for t in tickers[:3]] + [f"#{t}" for t in tags[:3]]
    extra = max(0, (len(tickers) + len(tags)) - len(bits))
    label = ", ".join(bits) + (f" +{extra} more" if extra else "")
    date = datetime.now(timezone.utc).strftime("%b %-d")
    return f"Your {date} briefing — {label}" if label else f"Your {date} news briefing"


def send_briefing(subscription: dict[str, Any], *, is_welcome: bool = False) -> tuple[bool, str]:
    """Build + send the briefing PDF for one subscription row. Never raises.

    Returns (ok, info). ``is_welcome`` tweaks the email copy for the first send.
    """
    email = (subscription.get("email") or "").strip().lower()
    if not email:
        return False, "no email"

    tickers = [str(t).upper() for t in (subscription.get("tickers") or [])]
    tags = [str(t).lower() for t in (subscription.get("tags") or [])]
    if not tickers and not tags:
        return False, "empty watchlist"

    try:
        briefing = gather_briefing(tickers, tags, hours=24)
        add_narratives(briefing)  # Ollama narrative per ticker + tag (best-effort)
        pdf_bytes = render_briefing_pdf(briefing)
    except Exception as exc:  # noqa: BLE001 — delivery is best-effort
        log.warning("[briefing] build failed for %s: %s", email, exc)
        return False, f"build failed: {exc}"

    manage_url = build_briefing_manage_url(email)
    unsubscribe_url = build_briefing_unsubscribe_url(email)

    # The one account-requiring ask, derived from this reader's own watchlist.
    # Best-effort: a briefing that cannot pick an action is still worth sending,
    # and falling back to the old CTA stack is strictly better than not sending.
    signin_url = action = None
    try:
        action = choose_action(briefing, tickers=tickers, tags=tags)
        signin_url = build_signin_url(email, action["next_path"])
    except Exception as exc:  # noqa: BLE001
        log.warning("[briefing] action selection failed for %s: %s", email, exc)
        signin_url = action = None

    html, text = render_briefing_email_html(
        briefing,
        manage_url=manage_url,
        unsubscribe_url=unsubscribe_url,
        is_welcome=is_welcome,
        signin_url=signin_url,
        action=action,
    )
    filename = f"news-briefing-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.pdf"

    ok, info = send_email(
        to=email,
        subject=_subject(briefing, tickers, tags),
        html=html,
        text=text,
        attachments=[{"filename": filename, "content": pdf_bytes}],
        tags=[{"name": "type", "value": "news_briefing"}],
    )
    if ok:
        log.info("[briefing] sent to %s (%d stories)", email, briefing.get("total_articles", 0))
    else:
        log.warning("[briefing] send failed for %s: %s", email, info)
    return ok, info
