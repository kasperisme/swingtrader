"""Investigate the crux — the one question the price actually turns on.

Every earlier attempt in this programme asked a language model to have an idea,
and it could not: asked for counterfactuals it produced twelve and all twelve
were already written up, because its priors ARE consensus. This loop does not
ask for an idea. `decompose.py` hands it a question that the published models
disagree about, and the job is only to find out whether the answer is
observable yet.

Tesla is the case that makes the shape obvious. Every rejected target is the
same variable at a different date — Truist's autonomy-in-2028 at +6%, the
consensus 2027 rollout at +27%, the software-P&L case at +43% — so the whole
$370-$500 spread reduces to: does paid, driverless robotaxi volume compound
across several metros before mid-2027?

Four rules, each from a failure earlier in this work:

* **News is not evidence.** By the governing assumption anything in the corpus
  is already in the price, so an investigation that answers "is this true?" by
  reading coverage has answered "has someone said it?" instead. The tool
  registry deliberately excludes news; `entail.py` already settles that
  question separately.

* **Refutation is a separate pass with its own context.** An agent asked to
  investigate a claim finds support for it, the same way a search run long
  enough clears any fixed threshold. So one pass gathers evidence and a second,
  which sees the evidence but not the first pass's conclusion, is asked to kill
  it. The probability comes from adjudicating both.

* **A proxy is named as a proxy.** Tesla's decisive observable is per-city app
  rank and DAU, which is not wired. Wikipedia attention to the robotaxi page is
  a real series and a weak substitute, and reporting it as though it settled
  the question would be the most damaging thing this module could do.

* **"Cannot settle it" is a first-class verdict.** It is also the expected one:
  the crux is by construction the thing nobody has resolved, and the
  decomposition usually says outright that the deciding measurement is missing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field

from ..config import LabConfig
from .tools import OBSERVABLE_COVERAGE, SCHEMAS, TOOLS

log = logging.getLogger(__name__)

PLAN_SYSTEM = """You plan an investigation into ONE question about a company.

You are given the question, the company, and the complete list of data tools
available. The tools are the only evidence you may use — there is no news tool,
deliberately: anything already written up is by assumption already in the price,
so coverage cannot tell you whether something is true.

Propose the checks worth running. For each: the tool, its arguments, what result
would support the claim, and what result would undercut it — stated BEFORE you
see any data, so the reading cannot drift to fit what comes back.

Most cruxes cannot be settled with this toolset, and saying so is the correct
answer. If a check is only a loose proxy for the real observable, mark it
`proxy: true` and say what it actually measures. Never dress a proxy as a
direct measurement."""

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["checks", "decisive_observable", "decisive_is_available"],
    "properties": {
        "decisive_observable": {
            "type": "string",
            "description": "What would ACTUALLY settle this, wired or not."},
        "decisive_is_available": {"type": "boolean"},
        "checks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["tool", "args_json", "supports_if", "undercuts_if",
                         "proxy", "measures"],
            "properties": {
                "tool": {"type": "string", "enum": sorted(TOOLS)},
                "args_json": {"type": "string"},
                "supports_if": {"type": "string"},
                "undercuts_if": {"type": "string"},
                "proxy": {"type": "boolean"},
                "measures": {"type": "string"}}}},
    },
}

EVIDENCE_SYSTEM = """You read the results of a pre-planned set of checks and say
what they show about one question.

Each check was registered in advance with what would support and what would
undercut the claim. Hold yourself to those, not to a reading invented now that
the numbers are visible.

Weigh a proxy as a proxy. If the decisive observable was unavailable, the
strongest honest conclusion is usually that the question remains open, and you
should say so rather than promoting a proxy to fill the gap."""

REFUTE_SYSTEM = """You are given a question, a set of measurements, and a claim
someone has drawn from them. Your job is to destroy the claim.

Attack it on: whether the measurement actually bears on the question; whether a
proxy is being read as a direct observation; whether the trend is real or a base
effect; whether an alternative explanation fits the same numbers; and whether
the sample is long enough to say anything.

Do not be even-handed — a separate pass has already made the case in favour. If
after genuinely trying you cannot land a blow, say so plainly; a failed
refutation is informative precisely because it was attempted."""

VERDICT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["reading", "probability", "confidence", "settled",
                 "what_would_settle_it"],
    "properties": {
        "reading": {"type": "string"},
        "probability": {
            "type": "number",
            "description": "P(the claim in the crux resolves TRUE), 0-1."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "settled": {
            "type": "boolean",
            "description": "Can the available data actually decide this? Usually false."},
        "what_would_settle_it": {"type": "string"},
    },
}

REFUTE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["strongest_objection", "objections", "survives", "revised_probability"],
    "properties": {
        "strongest_objection": {"type": "string"},
        "objections": {"type": "array", "items": {"type": "string"}},
        "survives": {"type": "boolean"},
        "revised_probability": {"type": "number"},
    },
}


@dataclass
class Check:
    tool: str
    args: dict
    supports_if: str
    undercuts_if: str
    proxy: bool
    measures: str
    result: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class Investigation:
    ticker: str
    question: str
    decisive_observable: str = ""
    decisive_is_available: bool = False
    checks: list = field(default_factory=list)
    reading: str = ""
    probability: float = 0.5
    confidence: str = ""
    settled: bool = False
    what_would_settle_it: str = ""
    strongest_objection: str = ""
    objections: list = field(default_factory=list)
    survives_refutation: bool = False
    revised_probability: float = 0.5

    def to_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [asdict(c) if not isinstance(c, dict) else c
                       for c in self.checks]
        return d

    def brief(self) -> str:
        out = [f"INVESTIGATION — {self.ticker}", "", f"  Q: {self.question}", ""]
        out.append(f"  decisive observable: {self.decisive_observable}")
        out.append(f"  available here: {'yes' if self.decisive_is_available else 'NO'}")
        out.append("")
        for c in self.checks:
            tag = " [PROXY]" if c.proxy else ""
            out.append(f"  {c.tool}({json.dumps(c.args)}){tag}")
            out.append(f"     measures : {c.measures}")
            out.append(f"     supports : {c.supports_if[:110]}")
            out.append(f"     undercuts: {c.undercuts_if[:110]}")
            out.append(f"     result   : {c.error or json.dumps(c.result, default=str)[:200]}")
        out += ["", f"  READING     {self.reading}", "",
                f"  OBJECTION   {self.strongest_objection}", ""]
        for o in self.objections[1:4]:
            out.append(f"              - {o[:140]}")
        out += ["",
                f"  P(true) {self.probability:.2f} -> after refutation "
                f"{self.revised_probability:.2f}   "
                f"(confidence {self.confidence}; refutation "
                f"{'survived' if self.survives_refutation else 'LANDED'})",
                f"  SETTLED BY THE DATA: {'yes' if self.settled else 'NO'}",
                f"  WOULD SETTLE IT: {self.what_would_settle_it}"]
        return "\n".join(out)


def _client():
    try:
        import anthropic
    except ImportError:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return anthropic.Anthropic()
    except Exception:                                         # noqa: BLE001
        return None


def _ask(client, model, system, user, schema, effort="medium"):
    with client.messages.stream(
        model=model, max_tokens=8000,
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort,
                       "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        msg = stream.get_final_message()
    text = next((b.text for b in msg.content if b.type == "text"), None)
    return json.loads(text) if text else {}


def run(ticker: str, question: str, business_brief: str = "",
        model: str | None = None, effort: str = "medium") -> Investigation | None:
    """Plan -> measure -> read -> refute -> adjudicate."""
    client = _client()
    if client is None:
        return None
    model = model or os.environ.get("STRATEGYLAB_MODEL") or LabConfig().llm_model
    inv = Investigation(ticker=ticker, question=question)

    coverage = "\n".join(
        f"  {k}: {'available' if v[0] else 'NOT WIRED — ' + v[1]}"
        for k, v in OBSERVABLE_COVERAGE.items())
    tool_docs = "\n".join(
        f"  {t['name']}({', '.join(t['input_schema']['properties'])}) — "
        f"{t['description']}" for t in SCHEMAS)

    try:
        plan = _ask(client, model, PLAN_SYSTEM,
                    f"{business_brief}\n\nCOMPANY: {ticker}\n\nQUESTION:\n{question}\n\n"
                    f"TOOLS:\n{tool_docs}\n\nOBSERVABLE COVERAGE:\n{coverage}",
                    PLAN_SCHEMA, effort)
    except Exception as exc:                                  # noqa: BLE001
        log.warning("plan failed: %s", exc)
        return None
    inv.decisive_observable = plan.get("decisive_observable", "")
    inv.decisive_is_available = bool(plan.get("decisive_is_available"))

    for row in plan.get("checks", [])[:6]:
        try:
            args = json.loads(row.get("args_json") or "{}")
        except json.JSONDecodeError:
            continue
        c = Check(tool=row["tool"], args=args,
                  supports_if=row.get("supports_if", ""),
                  undercuts_if=row.get("undercuts_if", ""),
                  proxy=bool(row.get("proxy")), measures=row.get("measures", ""))
        fn = TOOLS.get(c.tool)
        if fn is None:
            c.error = f"no such tool {c.tool!r}"
        else:
            try:
                c.result = fn(**args)
            except Exception as exc:                          # noqa: BLE001
                c.error = f"{type(exc).__name__}: {exc}"[:200]
        inv.checks.append(c)

    measured = "\n\n".join(
        f"CHECK {i+1}: {c.tool}({json.dumps(c.args)})"
        f"{' [PROXY for: ' + c.measures + ']' if c.proxy else ''}\n"
        f"  registered supports-if: {c.supports_if}\n"
        f"  registered undercuts-if: {c.undercuts_if}\n"
        f"  RESULT: {c.error or json.dumps(c.result, default=str)[:1200]}"
        for i, c in enumerate(inv.checks))

    try:
        v = _ask(client, model, EVIDENCE_SYSTEM,
                 f"QUESTION:\n{question}\n\nDECISIVE OBSERVABLE: "
                 f"{inv.decisive_observable}\nAVAILABLE: "
                 f"{inv.decisive_is_available}\n\n{measured}",
                 VERDICT_SCHEMA, effort)
    except Exception as exc:                                  # noqa: BLE001
        log.warning("evidence pass failed: %s", exc)
        return inv
    inv.reading = v.get("reading", "")
    inv.probability = float(v.get("probability") or 0.5)
    inv.confidence = v.get("confidence", "")
    inv.settled = bool(v.get("settled"))
    inv.what_would_settle_it = v.get("what_would_settle_it", "")

    # Separate context: the refuter sees the measurements and the claim, never
    # the reasoning that produced it.
    try:
        r = _ask(client, model, REFUTE_SYSTEM,
                 f"QUESTION:\n{question}\n\nMEASUREMENTS:\n{measured}\n\n"
                 f"CLAIM TO DESTROY:\n{inv.reading}\n"
                 f"(stated at probability {inv.probability:.2f})",
                 REFUTE_SCHEMA, effort)
    except Exception as exc:                                  # noqa: BLE001
        log.warning("refutation failed: %s", exc)
        return inv
    inv.strongest_objection = r.get("strongest_objection", "")
    inv.objections = r.get("objections", [])
    inv.survives_refutation = bool(r.get("survives"))
    inv.revised_probability = float(r.get("revised_probability") or inv.probability)
    return inv
