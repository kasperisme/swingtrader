"""LLM access for the autonomous researcher — Ollama, local and cloud.

One provider, one endpoint. Ollama serves local models and hosted "-cloud"
models through the same API, so a model is just a name and the daemon can be
pointed at a bigger one without touching any code.

Three things this layer exists to handle, all learned the hard way:

**Cloud models ignore the `format` schema.** Local Ollama enforces it; the
hosted models return markdown-fenced JSON of their own invention. The schema is
therefore sent BOTH as `format` and rendered into the prompt, and the reply is
validated here rather than trusted.

**Compliance is not competence.** A model that returns a perfectly-shaped
proposal can still have reasoned backwards — told that a stop "gives back 47% of
gross profit", gpt-oss tightened it. That does not corrupt results, because the
backtest arbitrates every proposal, but it does waste hours of overnight
compute. So acceptance rate is tracked per model and can be acted on.

**A 24/7 process must survive its dependencies.** Every failure degrades to the
next model in the chain and is counted, rather than raising at 3am.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

DEFAULT_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


@dataclass
class LLMResult:
    ok: bool
    data: dict | None = None
    model: str = ""
    latency_s: float = 0.0
    error: str = ""
    raw: str = ""
    attempts: int = 1


@dataclass
class ModelStats:
    """Per-model bookkeeping, including whether its ideas ever work.

    `accepted` is the number of proposals from this model that survived
    evaluation. It is the only measure that distinguishes a fast, compliant,
    confidently-wrong model from a useful one.
    """

    calls: int = 0
    failures: int = 0
    seconds: float = 0.0
    proposals: int = 0
    accepted: int = 0

    @property
    def acceptance(self) -> float:
        return self.accepted / self.proposals if self.proposals else 0.0

    def to_dict(self) -> dict:
        return {"calls": self.calls, "failures": self.failures,
                "avg_seconds": round(self.seconds / max(self.calls, 1), 1),
                "proposals": self.proposals, "accepted": self.accepted,
                "acceptance_rate": round(self.acceptance, 3)}


def extract_json(text: str) -> dict | None:
    """Recover an object from a decorated reply.

    Hosted models fence their JSON and sometimes prepend prose regardless of
    instructions. Take the outermost balanced object and nothing looser —
    anything more permissive starts inventing structure the model never emitted.
    """
    if not text:
        return None
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    if "```" in text:
        for part in text.split("```"):
            p = part.strip()
            if p.lower().startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                try:
                    obj = json.loads(p)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def validate(data: dict, schema: dict) -> tuple[bool, str]:
    """Shallow structural check against the declared schema.

    Not a full JSON-Schema validator — just enough to catch the failures that
    actually happen: a top-level array instead of an object, a missing required
    key, or an array where a string belongs. Anything subtler is caught
    downstream when the values are clipped to the search space.
    """
    if not isinstance(data, dict):
        return False, f"expected an object, got {type(data).__name__}"
    for key in schema.get("required", []):
        if key not in data:
            return False, f"missing required key '{key}'"
    props = schema.get("properties", {})
    for key, spec in props.items():
        if key not in data:
            continue
        want = spec.get("type")
        val = data[key]
        if want == "array" and not isinstance(val, list):
            return False, f"'{key}' should be an array"
        if want == "object" and not isinstance(val, dict):
            return False, f"'{key}' should be an object"
        if want == "string" and not isinstance(val, str):
            return False, f"'{key}' should be a string"
    return True, ""


class Ollama:
    """Local and hosted models through one endpoint."""

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 600.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as r:
                json.loads(r.read())
            return True
        except Exception:
            return False

    def installed(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=10) as r:
                return [m["name"] for m in json.loads(r.read()).get("models", [])]
        except Exception:
            return []

    def generate(self, model: str, prompt: str, schema: dict, system: str = "",
                 temperature: float = 0.5, num_ctx: int = 32768,
                 num_predict: int | None = None) -> LLMResult:
        opts = {"temperature": temperature, "num_ctx": num_ctx}
        if num_predict:
            # Left unset the server picks its own ceiling, and a long structured
            # reply comes back cut mid-object — which surfaces as "no JSON
            # object in reply" and reads like a compliance failure rather than a
            # truncation. Callers that know how long their reply can be say so.
            opts["num_predict"] = int(num_predict)
        payload = {
            "model": model, "prompt": prompt, "stream": False, "think": False,
            "format": schema,                       # honoured locally, ignored in cloud
            "options": opts,
        }
        if system:
            payload["system"] = system
        body = json.dumps(payload).encode()
        t0 = time.time()
        try:
            rq = urllib.request.Request(f"{self.url}/api/generate", data=body,
                                        headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(rq, timeout=self.timeout) as r:
                out = json.loads(r.read())
        except Exception as exc:
            return LLMResult(False, model=model, latency_s=time.time() - t0,
                             error=str(exc)[:200])
        if isinstance(out, dict) and out.get("error"):
            return LLMResult(False, model=model, latency_s=time.time() - t0,
                             error=str(out["error"])[:200])
        raw = out.get("response") or out.get("thinking") or ""
        data = extract_json(raw)
        if data is None:
            return LLMResult(False, model=model, latency_s=time.time() - t0,
                             error="no JSON object in reply", raw=raw[:1500])
        ok, why = validate(data, schema)
        return LLMResult(ok, data=data if ok else None, model=model,
                         latency_s=time.time() - t0, error="" if ok else why,
                         raw=raw[:1500])


SCHEMA_INSTRUCTION = (
    "Reply with ONE JSON object and nothing else — no prose, no markdown fences.\n"
    "It must match this schema exactly:\n{schema}\n"
)


class Client:
    """Model chain with validation, retry and per-model quality tracking."""

    def __init__(self, models: list[str] | None = None, url: str = DEFAULT_URL,
                 retries: int = 2):
        self.api = Ollama(url)
        env = os.environ.get("STRATEGYLAB_MODELS", "")
        self.models = models or ([m.strip() for m in env.split(",") if m.strip()]
                                 or self._default_chain())
        self.retries = retries
        self.stats: dict[str, ModelStats] = {}

    # Hosted first, local last so an overnight run survives a network outage
    # rather than dying at 3am. Measured on a realistic proposal prompt, all
    # three were 100% directionally correct; they differ mainly in latency
    # (gpt-oss:120b ~2.4s, gpt-oss:20b ~4.3s, glm-5.2 ~2-12s variable).
    CLOUD_CHAIN = ["glm-5.2:cloud", "gpt-oss:120b-cloud", "gpt-oss:20b-cloud"]

    def _default_chain(self) -> list[str]:
        installed = self.api.installed()
        local = [m for m in installed
                 if not any(t in m.lower() for t in ("embed", "bge", "minilm"))]
        return list(self.CLOUD_CHAIN) + local[:1]

    def _stat(self, model: str) -> ModelStats:
        return self.stats.setdefault(model, ModelStats())

    def status(self) -> dict:
        return {"reachable": self.api.available(), "chain": self.models,
                "installed": self.api.installed(),
                "stats": {k: v.to_dict() for k, v in self.stats.items()}}

    def record_outcome(self, model: str, proposals: int, accepted: int) -> None:
        """Feed evaluation results back, so a confidently-wrong model is visible.

        Format compliance says nothing about whether the ideas work. Only the
        backtest knows that, and this is where it gets written down.
        """
        st = self._stat(model)
        st.proposals += proposals
        st.accepted += accepted

    def complete(self, prompt: str, schema: dict, system: str = "",
                 temperature: float = 0.5) -> LLMResult:
        # The schema goes in the PROMPT as well as the format field: hosted
        # models ignore the field, and without it in the text they invent their
        # own shape.
        full = prompt + "\n\n" + SCHEMA_INSTRUCTION.format(
            schema=json.dumps(schema, indent=1))
        sys_msg = system or ("You are a quantitative researcher. You reply with a "
                             "single JSON object and nothing else.")
        last: LLMResult | None = None
        attempts = 0
        for model in self.models:
            for _ in range(self.retries):
                attempts += 1
                res = self.api.generate(model, full, schema, system=sys_msg,
                                        temperature=temperature)
                st = self._stat(model)
                st.calls += 1
                st.seconds += res.latency_s
                if res.ok:
                    res.attempts = attempts
                    return res
                st.failures += 1
                last = res
                log.warning("%s: %s", model, res.error)
        if last:
            last.attempts = attempts
        return last or LLMResult(False, error="no model available")
