"""LLM narratives per section (ticker + tag) via the Ollama model.

Each ticker and tag section is synthesized into a short, factual paragraph that
cites its stories by the briefing's reference numbers (``[1]``, ``[3]`` …). The
PDF then shows only these narratives plus a single reference list at the end —
no per-article rows — so a headline never appears twice.

Best-effort: any model/transport failure leaves a section's ``narrative`` empty
and the PDF falls back to a compact linked-headline list. Run
``assign_references`` first so each item already carries its ``ref`` number.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from services.news.llm.ollama_client import OllamaError, chat
from services.rag.taxonomy import DIM_KEY_TO_LABEL

log = logging.getLogger(__name__)

_TICKER_SYSTEM = (
    "You are a financial news editor writing a concise daily briefing for retail "
    "investors. Given a single stock and its last-24h news (each story carries a "
    "sentiment score from -1 to +1), write a tight 2-4 sentence narrative: the key "
    "developments and the overall tone of coverage. Cite the stories you draw on "
    "inline using their bracket numbers exactly as given, e.g. [1] or [2]. Be "
    "factual and neutral — no hype, no price targets, no investment advice. Use only "
    "the information in the provided stories; do not invent facts. Output the "
    "narrative paragraph only, no preamble or headings."
)

_TAG_SYSTEM = (
    "You are a financial news editor writing a concise daily briefing for retail "
    "investors. Given a theme and the day's tagged stories, write a tight 2-4 "
    "sentence narrative of what happened and why it matters. Cite the stories you "
    "draw on inline using their bracket numbers exactly as given, e.g. [1] or [2]. "
    "Be factual and neutral — no hype, no price targets, no investment advice. Use "
    "only the information in the provided stories; do not invent facts. Output the "
    "narrative paragraph only, no preamble or headings."
)


def _dim_labels(top_dimensions: list[Any], n: int = 2) -> str:
    out = []
    for entry in (top_dimensions or [])[:n]:
        key = entry.get("key") if isinstance(entry, dict) else (entry[0] if isinstance(entry, (list, tuple)) else None)
        if key:
            out.append(DIM_KEY_TO_LABEL.get(key, str(key).replace("_", " ")))
    return ", ".join(out)


def _ref(it: dict[str, Any]) -> str:
    r = it.get("ref")
    return f"[{r}]" if r else "-"


def _build_ticker_prompt(ticker: str, items: list[dict[str, Any]]) -> str:
    lines = [f"Stock: ${ticker}", "", "Sentiment-scored stories from the last 24 hours:"]
    for it in items:
        score = it.get("sentiment_score")
        score_str = f" sentiment {score:+.2f}" if isinstance(score, (int, float)) else ""
        reason = (it.get("sentiment_reason") or "").strip()
        reason_str = f" — {reason}" if reason else ""
        lines.append(f"{_ref(it)} {(it.get('title') or '').strip()}{score_str}{reason_str}")
    lines += ["", "Write the narrative paragraph now, citing sources as [n]."]
    return "\n".join(lines)


def _build_tag_prompt(tag: str, items: list[dict[str, Any]]) -> str:
    lines = [f"Theme: #{tag}", "", "Stories from the last 24 hours:"]
    for it in items:
        meta = []
        src = str(it.get("source") or "")
        if src and not src.startswith("http"):
            meta.append(src)
        dims = _dim_labels(it.get("top_dimensions"))
        if dims:
            meta.append(f"drivers: {dims}")
        line = f"{_ref(it)} {(it.get('title') or '').strip()}"
        if meta:
            line += f" ({'; '.join(meta)})"
        lines.append(line)
    lines += ["", "Write the narrative paragraph now, citing sources as [n]."]
    return "\n".join(lines)


async def _narrate(idx: int, kind: str, label: str, items: list[dict[str, Any]], model: str | None) -> tuple[int, str]:
    if not items:
        return idx, ""
    system = _TICKER_SYSTEM if kind == "ticker" else _TAG_SYSTEM
    prompt = _build_ticker_prompt(label, items) if kind == "ticker" else _build_tag_prompt(label, items)
    try:
        text, _ms = await chat(
            prompt=prompt,
            system=system,
            model=model,
            num_predict=int(os.environ.get("OLLAMA_BRIEFING_NUM_PREDICT", "260")),
        )
        return idx, (text or "").strip()
    except OllamaError as exc:
        log.warning("[briefing] narrative failed for %s %s: %s", kind, label, exc)
        return idx, ""
    except Exception as exc:  # noqa: BLE001 — narrative is optional
        log.warning("[briefing] narrative error for %s %s: %s", kind, label, exc)
        return idx, ""


def add_narratives(briefing: dict[str, Any]) -> dict[str, Any]:
    """Generate and attach a ``narrative`` to every ticker and tag section (sync).

    No-op when there are no sections with stories. Safe to call after
    gather_briefing / assign_references; never raises.
    """
    sections: list[tuple[str, dict[str, Any]]] = [
        ("ticker", s) for s in briefing.get("tickers", [])
    ] + [("tag", s) for s in briefing.get("tags", [])]
    work = [(i, kind, sec) for i, (kind, sec) in enumerate(sections) if sec.get("items")]
    if not work:
        return briefing

    model = os.environ.get("OLLAMA_BRIEFING_MODEL") or None

    async def _run() -> dict[int, str]:
        results = await asyncio.gather(
            *(
                _narrate(i, kind, sec.get("ticker") or sec.get("tag") or "", sec["items"], model)
                for i, kind, sec in work
            )
        )
        return dict(results)

    try:
        narratives = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        log.warning("[briefing] narrative batch failed: %s", exc)
        narratives = {}

    for i, _kind, sec in work:
        sec["narrative"] = narratives.get(i, "")
    return briefing


# Backwards-compatible alias.
add_tag_narratives = add_narratives
