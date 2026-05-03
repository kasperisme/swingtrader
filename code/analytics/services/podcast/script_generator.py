from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader

from .config import (
    HANS_EXTRACT_MODEL,
    HANS_SCRIPT_MODEL,
    OLLAMA_BASE_URL,
    SCRIPTS_DIR,
    TEMPLATES_DIR,
)

log = logging.getLogger(__name__)

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)


class PodcastScriptError(Exception):
    pass


async def _validate_data(client: httpx.AsyncClient, data: dict) -> dict:
    """Use extraction model to validate and clean input data."""
    prompt = (
        "Validate and clean this market data dict. "
        "Remove null values, fill missing numeric fields with sensible defaults. "
        "Ensure impact_score is between 0 and 10. "
        "Return ONLY valid JSON, no explanation.\n\n"
        f"{json.dumps(data)}"
    )
    r = await client.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={"model": HANS_EXTRACT_MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    r.raise_for_status()
    raw = r.json().get("response", "")
    return _parse_json(raw) or data


async def _call_script_model(
    client: httpx.AsyncClient, messages: list[dict], retry_error: str | None = None
) -> str:
    """Call the script model via chat endpoint."""
    if retry_error:
        messages = messages + [
            {"role": "assistant", "content": messages[-1].get("content", "")},
            {
                "role": "user",
                "content": f"JSON parse error: {retry_error}\nReturn only valid JSON, no other text.",
            },
        ]
    r = await client.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": HANS_SCRIPT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.75, "num_predict": 4096},
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _parse_json(raw: str) -> dict | None:
    """Strip think blocks and markdown fences, attempt JSON parse."""
    # Strip <think>...</think> reasoning tokens
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # Everything before the first {
    idx = cleaned.find("{")
    if idx == -1:
        return None
    cleaned = cleaned[idx:]
    # Strip trailing markdown fences
    cleaned = re.sub(r"```[a-z]*\s*$", "", cleaned.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


async def generate_script(data: dict) -> dict:
    today = data.get("date", str(date.today()))
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient() as client:
        log.info("Validating market data via %s", HANS_EXTRACT_MODEL)
        clean_data = await _validate_data(client, data)

        template = _jinja_env.get_template("script_prompt.j2")
        user_prompt = template.render(data=clean_data)

        system_msg = (
            "You are Hans, the AI host of NewsImpact Daily podcast. "
            "You write engaging, information-dense market intelligence scripts. "
            "Always return ONLY valid JSON matching the specified structure. "
            "No preamble, no markdown, no explanation — start with { and end with }."
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt},
        ]

        log.info("Generating script via %s", HANS_SCRIPT_MODEL)
        raw = await _call_script_model(client, messages)
        script = _parse_json(raw)

        if script is None:
            log.warning("First parse failed, retrying once")
            raw2 = await _call_script_model(
                client, messages, retry_error="Could not locate valid JSON in response"
            )
            script = _parse_json(raw2)

        if script is None:
            raise PodcastScriptError(
                f"Script model returned unparseable JSON after retry. Raw: {raw[:500]}"
            )

    out_path = SCRIPTS_DIR / f"{today}.json"
    out_path.write_text(json.dumps(script, indent=2))
    log.info("Script saved: %s", out_path)
    return script
