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
    "snapshot of a single ticker's last 6 months of daily price action "
    "(closes, SMAs, volume) and return a short, structured assessment.\n\n"
    "Always reply with a single JSON object — no prose, no code fences, no "
    "commentary outside the JSON. Schema:\n"
    '{\n'
    '  "status": "active" | "watchlist" | "pipeline" | "dismissed",\n'
    '  "comment": "<one short sentence — fits in a table cell>",\n'
    '  "analysis_markdown": "<2-4 short paragraphs of markdown>"\n'
    '}\n\n'
    "Status semantics:\n"
    "- pipeline:  high-conviction setup, ready for action\n"
    "- watchlist: constructive but needs confirmation\n"
    "- active:    no clear edge, neutral\n"
    "- dismissed: clearly broken or no setup\n\n"
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


def build_user_prompt(
    ticker: str,
    snapshot: dict[str, Any],
    user_instruction: str | None = None,
) -> str:
    instruction = (user_instruction or "").strip() or DEFAULT_USER_INSTRUCTION
    return (
        f"Ticker: {ticker}\n\n"
        f"User request: {instruction}\n\n"
        f"Snapshot (last 6 months of daily bars):\n"
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
    }
