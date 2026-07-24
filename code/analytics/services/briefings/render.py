"""Render a briefing payload to a styled PDF (Playwright) and an email body.

The PDF is an on-brand, print-friendly "research note": a dark header band over
a light body so it reads well both on screen and on paper. No external template
engine — the HTML is assembled here so the service has no new dependency beyond
Playwright (already in requirements.txt).
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Any

from shared.email import app_url

from .data import internal_article_url

log = logging.getLogger(__name__)

_AMBER = "#f5a623"
_INK = "#0b0f17"


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _fmt_dt(value: Any) -> str:
    """ISO timestamp → 'Jun 11, 14:30 UTC' (best-effort; blank on failure)."""
    if not value:
        return ""
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%b %-d, %H:%M UTC")
    except Exception:  # noqa: BLE001
        return ""


def _today_label() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %-d, %Y")


def _clean_source(source: Any) -> str:
    """`news_articles.source` often holds a full URL — show a tidy hostname."""
    s = str(source or "").strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        try:
            from urllib.parse import urlparse

            host = urlparse(s).netloc.lower()
            return host[4:] if host.startswith("www.") else host
        except Exception:  # noqa: BLE001
            return ""
    return s


def _sentiment_pill(score: float) -> str:
    if score >= 0.15:
        bg, fg, label = "rgba(16,185,129,0.14)", "#0f9d6b", f"▲ {score:+.2f}"
    elif score <= -0.15:
        bg, fg, label = "rgba(239,68,68,0.14)", "#d4433a", f"▼ {score:+.2f}"
    else:
        bg, fg, label = "rgba(100,116,139,0.14)", "#64748b", f"● {score:+.2f}"
    return (
        f'<span style="display:inline-block;font:600 11px ui-monospace,Menlo,monospace;'
        f'padding:2px 8px;border-radius:999px;background:{bg};color:{fg};">{label}</span>'
    )


def _ref_badge(ref: Any) -> str:
    if not ref:
        return ""
    return (
        f'<a href="#ref-{int(ref)}" style="text-decoration:none;font:700 10px ui-monospace,Menlo,monospace;'
        f'color:{_AMBER};vertical-align:super;">[{int(ref)}]</a> '
    )


def _narrative_html(narrative: str) -> str:
    """Render a section narrative, linkifying [n] citations to the references."""
    if not narrative:
        return ""
    safe = _esc(narrative)
    safe = re.sub(
        r"\[(\d+)\]",
        lambda m: f'<a href="#ref-{m.group(1)}" style="text-decoration:none;color:{_AMBER};font-weight:700;">[{m.group(1)}]</a>',
        safe,
    )
    return (
        '<div style="margin:8px 0 2px;padding:14px 16px;background:#f8fafc;border-left:3px solid '
        f'{_AMBER};border-radius:0 8px 8px 0;font:400 13.5px/1.6 system-ui;color:#334155;">{safe}</div>'
    )


def _compact_list_html(items: list[dict[str, Any]]) -> str:
    """Fallback when a narrative couldn't be generated: a tight list of linked
    headlines with their [n] badge. Titles still resolve to the references."""
    rows = []
    for it in items:
        url = internal_article_url(it.get("slug"), it.get("article_id"))
        rows.append(
            '<li style="margin:0 0 6px;font:400 13px/1.5 system-ui;color:#334155;">'
            f'{_ref_badge(it.get("ref"))}'
            f'<a href="{_esc(url)}" style="color:{_INK};text-decoration:none;font-weight:600;">{_esc(it.get("title", ""))}</a>'
            '</li>'
        )
    return f'<ul style="list-style:none;padding:0;margin:8px 0 0;">{"".join(rows)}</ul>'


def _section_body(section: dict[str, Any]) -> str:
    narrative = section.get("narrative", "")
    if narrative:
        return _narrative_html(narrative)
    return _compact_list_html(section.get("items", []))


def _ticker_section_html(section: dict[str, Any]) -> str:
    ticker = _esc(section["ticker"])
    avg = float(section.get("avg_sentiment") or 0.0)
    count = section.get("article_count", 0)
    head = (
        '<div style="display:flex;align-items:baseline;justify-content:space-between;margin:26px 0 6px;">'
        f'<h2 style="font:700 18px ui-monospace,Menlo,monospace;color:{_INK};margin:0;">${ticker}</h2>'
        f'<span style="font:500 12px system-ui;color:#94a3b8;">{count} stor{"y" if count == 1 else "ies"} · avg {_sentiment_pill(avg)}</span>'
        '</div>'
    )
    if not section.get("items"):
        return head + '<p style="font:400 13px system-ui;color:#94a3b8;margin:8px 0 0;">No notable coverage in the last 24 hours.</p>'
    return head + _section_body(section)


def _tag_section_html(section: dict[str, Any]) -> str:
    tag = _esc(section["tag"])
    count = section.get("article_count", 0)
    head = (
        '<div style="display:flex;align-items:baseline;justify-content:space-between;margin:26px 0 6px;">'
        f'<h2 style="font:700 18px system-ui;color:{_INK};margin:0;">#{tag}</h2>'
        f'<span style="font:500 12px system-ui;color:#94a3b8;">{count} stor{"y" if count == 1 else "ies"}</span>'
        '</div>'
    )
    if not section.get("items"):
        return head + '<p style="font:400 13px system-ui;color:#94a3b8;margin:8px 0 0;">No tagged coverage in the last 24 hours.</p>'
    return head + _section_body(section)


def _references_html(briefing: dict[str, Any]) -> str:
    """End-of-PDF numbered source list — links to newsimpactscreener.com."""
    refs = briefing.get("references") or []
    if not refs:
        return ""
    rows = []
    for r in refs:
        src_name = _clean_source(r.get("source"))
        src = f' · <span style="color:#64748b;">{_esc(src_name)}</span>' if src_name else ""
        when = _fmt_dt(r.get("published_at"))
        when_html = f' · <span style="color:#94a3b8;">{_esc(when)}</span>' if when else ""
        rows.append(
            f'<li id="ref-{int(r["n"])}" style="margin:0 0 7px;font:400 12px/1.5 system-ui;color:#334155;">'
            f'<span style="font:700 11px ui-monospace,Menlo,monospace;color:{_AMBER};">[{int(r["n"])}]</span> '
            f'<a href="{_esc(r["url"])}" style="color:{_INK};text-decoration:none;font-weight:600;">{_esc(r["title"])}</a>'
            f'{src}{when_html}</li>'
        )
    return (
        '<div style="margin-top:34px;padding-top:16px;border-top:2px solid #eef1f6;">'
        f'<h2 style="font:700 15px system-ui;color:{_INK};margin:0 0 12px;">Sources &amp; references</h2>'
        f'<ol style="list-style:none;padding:0;margin:0;">{"".join(rows)}</ol>'
        '</div>'
    )


def _watchlist_summary(briefing: dict[str, Any]) -> str:
    parts = [f'${_esc(s["ticker"])}' for s in briefing.get("tickers", [])]
    parts += [f'#{_esc(s["tag"])}' for s in briefing.get("tags", [])]
    return " · ".join(parts) if parts else "your watchlist"


def render_briefing_pdf_html(briefing: dict[str, Any]) -> str:
    """Full HTML document for the PDF attachment."""
    sections = "".join(_ticker_section_html(s) for s in briefing.get("tickers", []))
    sections += "".join(_tag_section_html(s) for s in briefing.get("tags", []))

    app_base = app_url()
    total = briefing.get("total_articles", 0)
    if total == 0:
        sections += (
            '<div style="margin-top:30px;padding:24px;border:1px dashed #cbd5e1;border-radius:12px;text-align:center;">'
            '<p style="font:500 14px system-ui;color:#64748b;margin:0;">A quiet 24 hours — no scored coverage for your watchlist. '
            'We&rsquo;ll keep watching and send the next briefing when news breaks.</p></div>'
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  body {{ margin: 0; background: #ffffff; color: {_INK};
          font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }}
  a {{ color: {_INK}; }}
</style></head>
<body>
  <div style="background:{_INK};color:#fff;border-radius:14px;padding:26px 28px;">
    <div style="font:700 11px ui-monospace,Menlo,monospace;letter-spacing:.22em;text-transform:uppercase;color:{_AMBER};">
      News Impact Screener · Daily Briefing
    </div>
    <div style="font:800 26px/1.2 system-ui;margin:10px 0 4px;">{_esc(_watchlist_summary(briefing))}</div>
    <div style="font:400 13px system-ui;color:#9aa6bd;">
      {_esc(_today_label())} · last 24 hours · {total} scored stor{"y" if total == 1 else "ies"}
    </div>
  </div>
  <div style="padding:4px 2px 0;">
    {sections}
  </div>
  {_references_html(briefing)}
  <div style="margin-top:24px;padding-top:14px;border-top:1px solid #eef1f6;font:400 11px system-ui;color:#94a3b8;">
    Narratives and impact scores are model-generated from the linked news for research only — not investment advice.
    Generated by <a href="{_esc(app_base)}" style="color:#64748b;">News Impact Screener</a>.
  </div>
</body></html>"""


def render_briefing_pdf(briefing: dict[str, Any]) -> bytes:
    """Render the briefing HTML to PDF bytes via headless Chromium (Playwright)."""
    from playwright.sync_api import sync_playwright

    doc = render_briefing_pdf_html(briefing)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(doc, wait_until="networkidle")
            pdf = page.pdf(format="A4", print_background=True)
        finally:
            browser.close()
    return pdf


def render_briefing_email_html(
    briefing: dict[str, Any],
    *,
    manage_url: str,
    unsubscribe_url: str,
    is_welcome: bool = False,
) -> tuple[str, str]:
    """Short email body (the PDF carries the detail). Returns (html, text)."""
    watchlist = _watchlist_summary(briefing)
    total = briefing.get("total_articles", 0)
    intro = (
        "Welcome aboard — here&rsquo;s your first briefing."
        if is_welcome
        else "Here&rsquo;s your daily briefing."
    )
    lead = (
        f"{total} scored stor{'y' if total == 1 else 'ies'} for {_esc(watchlist)} in the last 24 hours."
        if total
        else f"A quiet 24 hours for {_esc(watchlist)} — no scored coverage yet today."
    )

    # CTA priority: cross-sell (primary) → upgrade (secondary) → edit (tertiary).
    from shared.email import app_url, cta_stack
    _base = app_url()
    # utm_medium=email → GA4 buckets these as the Email channel; campaign splits the magnet.
    _screen_url = (
        f"{_base}/marketscreenings"
        "?utm_source=newsimpactscreener&utm_medium=email&utm_campaign=briefing&utm_content=briefing_email"
    )
    _upgrade_url = (
        f"{_base}/pricing"
        "?utm_source=newsimpactscreener&utm_medium=email&utm_campaign=briefing&utm_content=briefing_email"
    )
    ctas = cta_stack(
        primary=("See what the screens flagged", _screen_url),
        secondary=("Get real-time alerts + AI summaries", _upgrade_url),
        tertiary=("Or edit your briefing", manage_url),
    )

    html_body = f"""<!doctype html><html><body style="margin:0;background:#0b0f17;padding:28px;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:520px;margin:0 auto;background:#111620;border:1px solid #1e2533;border-radius:14px;padding:28px;color:#e6e9ef;">
    <p style="font:700 11px ui-monospace,Menlo,monospace;letter-spacing:.2em;text-transform:uppercase;color:{_AMBER};margin:0 0 14px;">News Impact Screener</p>
    <h1 style="font:700 20px system-ui;margin:0 0 8px;color:#fff;">{intro}</h1>
    <p style="font:400 14px/1.6 system-ui;color:#8b93a7;margin:0 0 18px;">{lead} The full report — headlines, sentiment and impact — is attached as a PDF. Watching <span style="color:#e6e9ef;font-weight:600;">{_esc(watchlist)}</span>.</p>
    {ctas}
    <p style="font:400 12px/1.6 system-ui;color:#5b6478;margin:24px 0 0;padding:16px 0 0;border-top:1px solid #1e2533;">
      You get this because you signed up at newsimpactscreener.com/briefings.
      <a href="{_esc(unsubscribe_url)}" style="color:#8b93a7;">Unsubscribe</a>
    </p>
  </div>
</body></html>"""

    text_body = (
        f"{'Welcome aboard — your first briefing.' if is_welcome else 'Your daily briefing.'}\n\n"
        f"{total} scored stories for {watchlist} in the last 24 hours. Full report attached as PDF.\n\n"
        f"See what the screens flagged: {_screen_url}\n"
        f"Get real-time alerts + AI summaries: {_upgrade_url}\n"
        f"Or edit your briefing: {manage_url}\n\n"
        f"Unsubscribe: {unsubscribe_url}\n"
    )
    return html_body, text_body
