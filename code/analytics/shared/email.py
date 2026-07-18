"""email.py — shared transactional-email utilities (Resend HTTP API).

Mirrors the TS lib in code/ui/lib/email so the Python fan-out can deliver
market-screening results to email-only subscribers at the same moment the
authed Telegram/in-app fan-out runs.

No new dependency: uses `requests` (already required) against Resend's REST
API instead of the Resend SDK.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as _stdhtml
import json
import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"
_DEFAULT_FROM = "News Impact Screener <noreply@newsimpactscreener.com>"


def _app_url() -> str:
    return (
        os.environ.get("NEXT_PUBLIC_APP_URL")
        or os.environ.get("APP_URL")
        or "https://newsimpactscreener.com"
    ).rstrip("/")


def app_url() -> str:
    """Public accessor for the canonical site base URL (no trailing slash)."""
    return _app_url()


# --- promo blocks (cross-sell / soft upsell) -------------------------------
# Reusable, self-contained HTML fragments for the dark-theme transactional
# emails. They carry NO copy of their own so the caller controls the message;
# only the styling is shared so briefing + screening emails stay consistent.
# Subscribers are anonymous (no plan tier), so upsell copy must stay generic.

_PROMO_ACCENT = "#f5a623"


def _hesc(s: Any) -> str:
    """HTML-escape text and URLs (quotes too) for safe interpolation."""
    return _stdhtml.escape(str(s), quote=True)


_SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def cta_primary(label: str, url: str) -> str:
    """The one dominant action — a solid amber button. Pass plain text."""
    return (
        f'<a href="{_hesc(url)}" style="display:inline-block;font-family:{_SANS};'
        f'font-size:15px;font-weight:700;color:#0b0f17;background:{_PROMO_ACCENT};'
        'padding:13px 22px;border-radius:8px;text-decoration:none;">'
        f'{_hesc(label)} &rarr;</a>'
    )


def cta_secondary(label: str, url: str) -> str:
    """Second-tier action — an outlined (ghost) amber button, ranked below primary."""
    return (
        f'<a href="{_hesc(url)}" style="display:inline-block;font-family:{_SANS};'
        f'font-size:14px;font-weight:600;color:{_PROMO_ACCENT};background:transparent;'
        'padding:11px 20px;border:1px solid #6b5620;border-radius:8px;'
        f'text-decoration:none;">{_hesc(label)} &rarr;</a>'
    )


def cta_tertiary(label: str, url: str) -> str:
    """Lowest-tier maintenance action — a quiet muted text link."""
    return (
        f'<a href="{_hesc(url)}" style="font-family:{_SANS};font-size:13px;'
        f'color:#6f7a90;text-decoration:underline;">{_hesc(label)}</a>'
    )


def cta_stack(*, primary: tuple[str, str], secondary: tuple[str, str],
              tertiary: tuple[str, str]) -> str:
    """Stack the three CTA tiers vertically: solid → outlined → muted link.

    Each arg is a (label, url) pair. Establishes one clear reading order —
    cross-sell first, upsell second, maintenance last.
    """
    return (
        f'<div style="margin:22px 0 0 0;">{cta_primary(*primary)}</div>'
        f'<div style="margin:12px 0 0 0;">{cta_secondary(*secondary)}</div>'
        '<div style="margin:16px 0 0 0;">'
        f'{cta_tertiary(*tertiary)}</div>'
    )


def _b64url_nopad(raw: bytes) -> str:
    """Unpadded base64url — matches Node Buffer.toString('base64url')."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sign_unsubscribe_token(email: str, slugs: list[str]) -> str:
    """Build an HMAC-signed unsubscribe token the TS /api/unsubscribe verifies.

    Format: base64url(json{email,slugs}) + "." + base64url(HMAC-SHA256(body)).
    The body string is hashed verbatim, so JSON whitespace/order is irrelevant
    as long as both sides hash the same bytes (TS re-derives over the token's
    body substring).
    """
    secret = os.environ.get("UNSUBSCRIBE_SECRET", "")
    body = _b64url_nopad(
        json.dumps({"email": email, "slugs": slugs}, separators=(",", ":")).encode("utf-8")
    )
    sig = _b64url_nopad(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def build_unsubscribe_url(email: str, slugs: list[str]) -> str:
    from urllib.parse import quote

    token = sign_unsubscribe_token(email, slugs)
    return f"{_app_url()}/api/unsubscribe?token={quote(token, safe='')}"


def sign_briefing_token(email: str) -> str:
    """HMAC-signed token for the news-briefing manage / unsubscribe links.

    Payload is just ``{email}`` — one briefing per email, so the email is the
    whole identity. Mirrors the TS ``signBriefingToken`` in
    code/ui/lib/email/briefing-subscriptions.ts (same secret, same body bytes),
    so links minted here verify there and vice-versa.
    """
    secret = os.environ.get("UNSUBSCRIBE_SECRET", "")
    body = _b64url_nopad(
        json.dumps({"email": email}, separators=(",", ":")).encode("utf-8")
    )
    sig = _b64url_nopad(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def build_briefing_manage_url(email: str) -> str:
    from urllib.parse import quote

    token = sign_briefing_token(email)
    return f"{_app_url()}/briefings/manage?token={quote(token, safe='')}"


def build_briefing_unsubscribe_url(email: str) -> str:
    from urllib.parse import quote

    token = sign_briefing_token(email)
    return f"{_app_url()}/api/briefings/unsubscribe?token={quote(token, safe='')}"


def send_email(
    *,
    to: str | list[str],
    subject: str,
    html: str,
    text: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    from_addr: str | None = None,
    tags: list[dict[str, str]] | None = None,
) -> tuple[bool, str]:
    """Send one transactional email via Resend. Never raises — returns (ok, info).

    `attachments` items: {"filename": str, "content": bytes|str}. Bytes are
    base64-encoded for the API; strings are assumed already-UTF-8 content and
    base64-encoded too.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return False, "RESEND_API_KEY not set"

    payload: dict[str, Any] = {
        "from": from_addr or os.environ.get("RESEND_FROM_EMAIL") or _DEFAULT_FROM,
        "to": to if isinstance(to, list) else [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if tags:
        payload["tags"] = tags
    if attachments:
        api_attachments = []
        for a in attachments:
            content = a.get("content")
            if isinstance(content, str):
                content = content.encode("utf-8")
            if not isinstance(content, (bytes, bytearray)):
                continue
            api_attachments.append(
                {
                    "filename": a["filename"],
                    "content": base64.b64encode(content).decode("ascii"),
                }
            )
        if api_attachments:
            payload["attachments"] = api_attachments

    try:
        r = requests.post(
            _RESEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if r.status_code >= 400:
            return False, f"Resend {r.status_code}: {r.text[:200]}"
        data = r.json()
        return True, str(data.get("id", ""))
    except Exception as exc:  # noqa: BLE001 — best-effort, never break the run
        return False, str(exc)
