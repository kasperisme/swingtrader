"""
Single-pass technical-analysis prompt for the bulk Ollama worker.

Returns strict JSON: {status, comment, analysis_markdown}.
"""

from __future__ import annotations

import json
import re
from typing import Any


SYSTEM = (
    "You are a swing-trading technical analyst. You receive a compact "
    "snapshot of a single ticker's recent OHLCV at the chart granularity "
    "the user selected (1hour, 4hour, 1day, or 1week — see snapshot.granularity "
    "and snapshot.bar_label). The snapshot includes closes, SMAs, and volume "
    "summaries. Return a short, structured assessment.\n\n"
    "Always reply with a single JSON object — no prose, no code fences, no "
    "commentary outside the JSON. Schema:\n"
    '{\n'
    '  "status": "active" | "watchlist" | "pipeline" | "dismissed",\n'
    '  "comment": "<one short sentence — fits in a table cell>",\n'
    '  "analysis_markdown": "<2-4 short paragraphs of markdown>",\n'
    '  "entry": null | {\n'
    '    "direction": "long" | "short",\n'
    '    "price": <number — pivot/entry trigger price>,\n'
    '    "take_profit": <number, optional>,\n'
    '    "stop_loss": <number, optional>\n'
    '  }\n'
    '}\n\n'
    "Status semantics:\n"
    "- pipeline:  high-conviction setup, ready for action\n"
    "- watchlist: constructive but needs confirmation\n"
    "- active:    no clear edge, neutral\n"
    "- dismissed: clearly broken or no setup\n\n"
    "Entry rules (entry is OPTIONAL):\n"
    "- Whenever a tradeable setup is forming — a clear pivot, breakout level, "
    "pullback to support, or short trigger — populate `entry` with the price, "
    "direction, and stop/target if you can identify them. Otherwise set "
    "`entry` to null. Do not gate on subjective confidence; if you can name a "
    "level a trader could act on, include it.\n"
    "- Use the snapshot's last_close as the reference; entry price should be "
    "a real level visible in the recent action (recent high, SMA, swing low, etc.).\n\n"
    "analysis_markdown must use these labelled lines (each on its own line, "
    "bolded):\n"
    "**Trend:** ...\n"
    "**SMAs:** ...\n"
    "**Support:** $...\n"
    "**Resistance:** $...\n"
    "**Volume:** ...\n\n"
    "Then a final blank line and one short summary paragraph."
)


DEFAULT_USER_INSTRUCTION = "Run a technical analysis."


def with_trading_strategy(system_prompt: str, trading_strategy: str | None) -> str:
    """Mirror chart AI: prepend saved profile strategy to the system prompt."""
    text = (trading_strategy or "").strip()
    if not text:
        return system_prompt
    return (
        "## User's Trading Strategy\n"
        f"{text}\n"
        "Always align your analysis and recommendations to this strategy. "
        "Only highlight setups, signals, and risks that are relevant to it.\n\n"
        f"{system_prompt}"
    )


def build_system(trading_strategy: str | None = None) -> str:
    return with_trading_strategy(SYSTEM, trading_strategy)


def build_user_prompt(
    ticker: str,
    snapshot: dict[str, Any],
    user_instruction: str | None = None,
) -> str:
    instruction = (user_instruction or "").strip() or DEFAULT_USER_INSTRUCTION
    return (
        f"Ticker: {ticker}\n\n"
        f"User request: {instruction}\n\n"
        f"Chart granularity: {snapshot.get('granularity', '1day')} "
        f"({snapshot.get('bar_label', 'daily')} bars)\n\n"
        f"Snapshot:\n"
        f"{json.dumps(snapshot, separators=(',', ':'))}\n\n"
        "Apply the user request when shaping your assessment. Return the JSON object only."
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def parse_response(raw: str) -> dict[str, Any]:
    """
    Tolerant parser: strips code fences, finds the outermost JSON object.
    Raises ValueError if nothing parseable comes back.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty response")
    text = _FENCE_RE.sub("", text).strip()

    # Find first { and last } — Ollama sometimes wraps in commentary.
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        raise ValueError(f"no JSON object in response: {text[:200]!r}")
    payload = json.loads(text[first : last + 1])

    status = str(payload.get("status", "")).lower().strip()
    if status not in {"active", "watchlist", "pipeline", "dismissed"}:
        status = "active"

    comment = str(payload.get("comment") or "").strip()
    analysis = str(payload.get("analysis_markdown") or "").strip()
    if not analysis:
        raise ValueError("missing analysis_markdown")

    return {
        "status": status,
        "comment": comment[:400],  # protect the column
        "analysis_markdown": analysis,
        "entry": _parse_entry(payload.get("entry")),
    }


def _parse_entry(raw: Any) -> dict[str, Any] | None:
    """Extract a tradeable entry from the LLM payload, or None."""
    if not isinstance(raw, dict):
        return None
    direction = str(raw.get("direction") or "").lower().strip()
    if direction not in {"long", "short"}:
        return None
    try:
        price = float(raw.get("price"))
    except (TypeError, ValueError):
        return None
    if price != price or price <= 0:  # NaN or non-positive
        return None
    out: dict[str, Any] = {"direction": direction, "price": round(price, 4)}
    for key in ("take_profit", "stop_loss"):
        v = raw.get(key)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f <= 0:
            continue
        out[key] = round(f, 4)
    return out


BULK_SUMMARY_SYSTEM = (
    "You summarize a completed bulk technical-analysis run across many tickers "
    "in a swing-trading screener. The user sees this in the 'All tickers' chat tab.\n\n"
    "Reply with markdown only (no JSON). Structure:\n"
    "1. First line: **Status:** Done | Error (match the run outcome)\n"
    "2. One short paragraph: high-level read of the screening — themes, how many "
    "names look actionable vs watch-only vs dismiss, anything surprising.\n"
    "3. Bullet list: counts by row status (pipeline / watchlist / active / dismissed) "
    "and note failed ticker count if any.\n"
    "4. One sentence on what to do next (e.g. review pipeline names, widen filters).\n"
    "Stay concise. Align with the user's trading strategy when provided."
)


def build_bulk_summary_prompt(
    *,
    job_status: str,
    total: int,
    succeeded: int,
    failed: int,
    status_counts: dict[str, int],
    user_prompt: str | None,
    chart_granularity: str,
    chart_date_from: str | None,
    chart_date_to: str | None,
    error_message: str | None = None,
) -> str:
    return (
        f"Run outcome: {job_status}\n"
        f"Tickers: total={total}, analyzed_ok={succeeded}, failed={failed}\n"
        f"Status breakdown: {json.dumps(status_counts, separators=(',', ':'))}\n"
        f"Chart granularity: {chart_granularity}\n"
        f"Date range: {chart_date_from or 'default'} to {chart_date_to or 'default'}\n"
        f"User bulk prompt: {(user_prompt or '').strip() or DEFAULT_USER_INSTRUCTION}\n"
        f"Error detail: {error_message or 'none'}\n"
    )


def format_bulk_summary_fallback(
    *,
    job_status: str,
    total: int,
    succeeded: int,
    failed: int,
    status_counts: dict[str, int],
    chart_granularity: str,
    error_message: str | None = None,
) -> str:
    label = "Done" if job_status == "done" else "Error"
    lines = [
        f"**Status:** {label}",
        "",
        (
            f"Analyzed **{succeeded}** of **{total}** tickers at **{chart_granularity}** granularity."
            + (f" **{failed}** could not be completed." if failed else "")
            + (f" {error_message}" if error_message else "")
        ),
        "",
        "**Row status counts:**",
    ]
    for key in ("pipeline", "watchlist", "active", "dismissed"):
        n = status_counts.get(key, 0)
        if n:
            lines.append(f"- {key}: {n}")
    if not any(status_counts.get(k, 0) for k in ("pipeline", "watchlist", "active", "dismissed")):
        lines.append("- (no status rows recorded)")
    lines.extend(["", "Open individual tickers in the list for full per-symbol write-ups."])
    return "\n".join(lines)


BULK_SUMMARY_SYSTEM = (
    "You summarize a completed bulk technical-analysis run across many tickers "
    "in a swing-trading screener. The user sees this in the 'All tickers' chat tab.\n\n"
    "Reply with markdown only (no JSON). Structure:\n"
    "1. First line: **Status:** Done | Error (match the run outcome)\n"
    "2. One short paragraph: high-level read of the screening — themes, how many "
    "names look actionable vs watch-only vs dismiss, anything surprising.\n"
    "3. Bullet list: counts by row status (pipeline / watchlist / active / dismissed) "
    "and note failed ticker count if any.\n"
    "4. One sentence on what to do next (e.g. review pipeline names, widen filters).\n"
    "Stay concise. Align with the user's trading strategy when provided."
)


def build_bulk_summary_prompt(
    *,
    job_status: str,
    total: int,
    succeeded: int,
    failed: int,
    status_counts: dict[str, int],
    user_prompt: str | None,
    chart_granularity: str,
    chart_date_from: str | None,
    chart_date_to: str | None,
    error_message: str | None = None,
) -> str:
    return (
        f"Run outcome: {job_status}\n"
        f"Tickers: total={total}, analyzed_ok={succeeded}, failed={failed}\n"
        f"Status breakdown: {json.dumps(status_counts, separators=(',', ':'))}\n"
        f"Chart granularity: {chart_granularity}\n"
        f"Date range: {chart_date_from or 'default'} to {chart_date_to or 'default'}\n"
        f"User bulk prompt: {(user_prompt or '').strip() or DEFAULT_USER_INSTRUCTION}\n"
        f"Error detail: {error_message or 'none'}\n"
    )


def format_bulk_summary_fallback(
    *,
    job_status: str,
    total: int,
    succeeded: int,
    failed: int,
    status_counts: dict[str, int],
    chart_granularity: str,
    error_message: str | None = None,
) -> str:
    label = "Done" if job_status == "done" else "Error"
    lines = [
        f"**Status:** {label}",
        "",
        (
            f"Analyzed **{succeeded}** of **{total}** tickers at **{chart_granularity}** granularity."
            + (f" **{failed}** could not be completed." if failed else "")
            + (f" {error_message}" if error_message else "")
        ),
        "",
        "**Row status counts:**",
    ]
    for key in ("pipeline", "watchlist", "active", "dismissed"):
        n = status_counts.get(key, 0)
        if n:
            lines.append(f"- {key}: {n}")
    if not any(status_counts.get(k, 0) for k in ("pipeline", "watchlist", "active", "dismissed")):
        lines.append("- (no status rows recorded)")
    lines.extend(["", "Open individual tickers in the list for full per-symbol write-ups."])
    return "\n".join(lines)
