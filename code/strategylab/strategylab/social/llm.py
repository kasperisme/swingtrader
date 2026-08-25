"""One JSON completion, two backends.

The priced-in pipeline was written against Anthropic and each module opened its
own client. That was fine while the programme ran on fifteen hand-picked tickers
and someone watched every run. It stops being fine the moment the thing runs on
a schedule across the NYSE + NASDAQ universe: four calls per ticker times several
hundred tickers per pass is a bill that scales with coverage, and coverage is the
whole point of scheduling it.

So the transport is separated from the prompts. The prompts, the schemas and the
validation rules are the parts that were tuned against real runs and they do not
change; only the wire does.

## Which backend

`resolve()` returns a backend and an ordered model chain:

* `STRATEGYLAB_LLM_BACKEND=ollama` -> Ollama, chain from
  `STRATEGYLAB_OLLAMA_MODELS` (comma-separated), default `glm-5.1:cloud`.
* `STRATEGYLAB_LLM_BACKEND=anthropic` -> Anthropic, one model.
* unset -> Anthropic if `ANTHROPIC_API_KEY` is set, else Ollama if a daemon
  answers. The batch runner sets it explicitly rather than relying on this.

## What differs on the Ollama side, and why it is handled here

**Cloud models ignore the `format` field.** `autonomous.llm` learned this the
hard way and already renders the schema into the prompt, validates the reply and
retries down a chain. That code is reused rather than reimplemented — it is the
same failure mode, and a second copy of it would drift.

**There is no `effort` and no adaptive thinking.** Both are dropped for Ollama
rather than emulated. A knob that silently does nothing is worse than one that
is visibly absent, so `effort` is accepted and ignored, and the model actually
used is reported back on the result so a row can record what produced it.

**Context has to be sized.** Anthropic grows its window; Ollama takes `num_ctx`
up front and silently truncates the *front* of the prompt when the request
overflows — which, for these prompts, is the business brief and the analyst
position, i.e. the part that says what the question is. So the window is sized
from the prompt with headroom for the reply, and a prompt that cannot fit even
at the ceiling is refused rather than quietly cropped.

## What this does NOT cover

`investigate.py` runs a tool-use loop. Ollama's `/api/generate` has no tool
protocol, so that path stays on Anthropic and says so. It is off the batch
critical path — the batch produces reconstructions, and the crux investigation is
a per-ticker follow-up someone asks for.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

OLLAMA_DEFAULT_CHAIN = ["glm-5.1:cloud"]

# Ollama truncates the FRONT of an overlong prompt, which for these prompts is
# the question rather than the evidence. Size the window instead, and refuse
# rather than crop above the ceiling.
CTX_FLOOR = 8_192
CTX_CEILING = 131_072
CHARS_PER_TOKEN = 3.5


@dataclass
class Completion:
    """What came back, and what produced it."""

    data: dict | None = None
    model: str = ""
    backend: str = ""
    latency_s: float = 0.0
    error: str = ""
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.data is not None

    def to_dict(self) -> dict:
        return {"model": self.model, "backend": self.backend,
                "latency_s": round(self.latency_s, 2), "attempts": self.attempts,
                "error": self.error}


# ----------------------------------------------------------------------
def _anthropic_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def resolve(model: str | None = None) -> tuple[str, list[str]]:
    """(backend, model chain). Explicit env wins; otherwise take what exists."""
    from ..config import LabConfig

    want = (os.environ.get("STRATEGYLAB_LLM_BACKEND") or "").strip().lower()

    def _ollama_chain() -> list[str]:
        env = (os.environ.get("STRATEGYLAB_OLLAMA_MODELS")
               or os.environ.get("STRATEGYLAB_MODELS") or "")
        chain = [m.strip() for m in env.split(",") if m.strip()]
        return chain or list(OLLAMA_DEFAULT_CHAIN)

    if want == "ollama":
        # An explicit non-Claude model name overrides the chain; a Claude one is
        # ignored, because it is almost always LabConfig's default leaking
        # through a caller that did not mean to pick a model at all.
        if model and not model.startswith("claude"):
            return "ollama", [model]
        return "ollama", _ollama_chain()
    if want == "anthropic":
        return "anthropic", [model or os.environ.get("STRATEGYLAB_MODEL")
                             or LabConfig().llm_model]
    if want:
        raise ValueError(f"unknown STRATEGYLAB_LLM_BACKEND {want!r}; "
                         "expected 'ollama' or 'anthropic'")

    if model and not model.startswith("claude"):
        return "ollama", [model]
    if _anthropic_available():
        return "anthropic", [model or os.environ.get("STRATEGYLAB_MODEL")
                             or LabConfig().llm_model]
    return "ollama", _ollama_chain()


def available(backend: str | None = None) -> tuple[bool, str]:
    """Can the resolved backend actually be called? Reported, never raised."""
    b, chain = (backend, resolve()[1]) if backend else resolve()
    if b == "anthropic":
        return (_anthropic_available(),
                "" if _anthropic_available() else
                "ANTHROPIC_API_KEY unset or the anthropic package is missing")
    from ..autonomous.llm import Ollama
    api = Ollama()
    if not api.available():
        return False, f"no Ollama daemon at {api.url}"
    return True, f"ollama {api.url}, chain {chain}"


def _num_ctx(prompt_chars: int, max_tokens: int) -> int:
    """Window big enough for the prompt AND the reply, rounded to a power of two.

    The reply has to be counted: `num_ctx` covers both halves, so sizing on the
    prompt alone buys a window that fits the question and then truncates it to
    make room for the answer.
    """
    need = int(prompt_chars / CHARS_PER_TOKEN) + max_tokens + 512
    n = CTX_FLOOR
    while n < need and n < CTX_CEILING:
        n *= 2
    return min(n, CTX_CEILING)


# ----------------------------------------------------------------------
def complete_json(system: str, user: str, schema: dict, *, max_tokens: int,
                  effort: str = "medium", model: str | None = None,
                  temperature: float = 0.3,
                  thinking: bool = False) -> Completion:
    """One schema-constrained JSON reply, from whichever backend is configured.

    Returns a `Completion` rather than a bare dict so the caller can record WHAT
    produced a row. That matters more than it looks: `research_priced_in.model`
    is how a reader tells a frontier reconstruction from a local one, and every
    row this pipeline writes now carries a mix.
    """
    backend, chain = resolve(model)
    if backend == "anthropic":
        return _anthropic(chain[0], system, user, schema, max_tokens=max_tokens,
                          effort=effort, thinking=thinking)
    return _ollama(chain, system, user, schema, max_tokens=max_tokens,
                   temperature=temperature)


def _anthropic(model: str, system: str, user: str, schema: dict, *,
               max_tokens: int, effort: str, thinking: bool) -> Completion:
    import time
    try:
        import anthropic
    except ImportError:
        return Completion(backend="anthropic", error="anthropic package missing")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return Completion(backend="anthropic", error="ANTHROPIC_API_KEY unset")
    t0 = time.time()
    kwargs = {
        "model": model, "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": effort,
                          "format": {"type": "json_schema", "schema": schema}},
    }
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    try:
        client = anthropic.Anthropic()
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    except Exception as exc:                                  # noqa: BLE001
        return Completion(backend="anthropic", model=model, attempts=1,
                          latency_s=time.time() - t0, error=str(exc)[:200])
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if not text:
        return Completion(backend="anthropic", model=model, attempts=1,
                          latency_s=time.time() - t0, error="empty reply")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return Completion(backend="anthropic", model=model, attempts=1,
                          latency_s=time.time() - t0,
                          error=f"unparseable JSON: {exc}")
    return Completion(data=data, model=model, backend="anthropic", attempts=1,
                      latency_s=time.time() - t0)


def _ollama(chain: list[str], system: str, user: str, schema: dict, *,
            max_tokens: int, temperature: float) -> Completion:
    from ..autonomous.llm import SCHEMA_INSTRUCTION, Ollama

    api = Ollama()
    # The schema goes in the PROMPT as well as the format field. Hosted models
    # ignore the field entirely and invent their own shape without it.
    full = user + "\n\n" + SCHEMA_INSTRUCTION.format(
        schema=json.dumps(schema, indent=1))
    ctx = _num_ctx(len(full) + len(system), max_tokens)
    need = int((len(full) + len(system)) / CHARS_PER_TOKEN) + max_tokens
    if need > CTX_CEILING:
        return Completion(backend="ollama", error=(
            f"prompt needs ~{need:,} tokens, above the {CTX_CEILING:,} ceiling; "
            f"refusing rather than letting Ollama truncate the question"))

    last = Completion(backend="ollama", error="no model available")
    attempts = 0
    for m in chain:
        for _ in range(2):
            attempts += 1
            r = api.generate(m, full, schema, system=system,
                             temperature=temperature, num_ctx=ctx,
                             num_predict=max_tokens)
            if r.ok:
                return Completion(data=r.data, model=m, backend="ollama",
                                  latency_s=r.latency_s, attempts=attempts)
            log.warning("ollama %s: %s", m, r.error)
            last = Completion(backend="ollama", model=m, latency_s=r.latency_s,
                              error=r.error, attempts=attempts)
    return last
