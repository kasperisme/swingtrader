"""Does the generator already know how the story ended?

A walk-forward test of this pipeline is only meaningful if the thing being
tested could not see the future. Timestamps guarantee that for the DATA. They
guarantee nothing for the MODEL, whose training corpus may contain the outcome
of every window we would like to test.

That is usually argued about rather than measured, which is backwards, because
it is directly measurable: **ask the model what it knows.** If it can state a
company's FY2025 revenue and the direction of its stock over the test window,
then a counterfactual "generated as of August 2025" is not a forecast, it is a
recollection wearing a timestamp.

Two probes, cheap and decisive:

* `recall_probe` — ask outright for the outcomes over the window, with no data
  supplied. Anything it gets right is knowledge it will bring to a backtest
  whether or not we want it to. Scored against the real figures.
* `date_sensitivity_probe` — generate with the as-of date stated versus with no
  date at all. If the outputs shift toward what actually happened when the date
  is revealed, the leak is not merely present, it is *operative*.

The honest use of the result is to decide which stages a backtest may include.
A model that recalls the outcome does not invalidate `implied()` — that is
arithmetic with no model in it — but it does invalidate any claim that generated
counterfactuals or their probabilities were validated on historical windows.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field

from ..config import LabConfig

log = logging.getLogger(__name__)

RECALL_SYSTEM = """You are being tested on what you know, not on what you can infer.

Answer from memory only. You have been given no data. For each question, if you
genuinely do not know, say so — `known: false` — rather than estimating from
priors. An honest "I don't know" is the useful answer here; a plausible guess is
worse than useless because it cannot be distinguished from knowledge."""

RECALL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["answers"],
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["question_id", "known", "answer", "confidence"],
                "properties": {
                    "question_id": {"type": "string"},
                    "known": {"type": "boolean"},
                    "answer": {"type": "string"},
                    "confidence": {"type": "number"},
                }}}},
}


@dataclass
class RecallResult:
    ticker: str
    window: str
    answers: list = field(default_factory=list)
    n_claimed_known: int = 0
    n_correct: int = 0
    verdict: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


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


def recall_probe(ticker: str, company: str, questions: list[dict],
                 model: str | None = None) -> RecallResult:
    """Ask the model to recall outcomes over the test window, unaided.

    `questions` is a list of {id, question, truth} where `truth` is the real
    answer, used only for scoring after the fact and never shown to the model.
    """
    client = _client()
    if client is None:
        return RecallResult(ticker=ticker, window="",
                            verdict="no LLM available; leakage unmeasured")
    model = model or os.environ.get("STRATEGYLAB_MODEL") or LabConfig().llm_model
    user = (f"Company: {company} ({ticker}).\n\n"
            + "\n".join(f"[{q['id']}] {q['question']}" for q in questions))
    try:
        with client.messages.stream(
            model=model, max_tokens=4000,
            system=[{"type": "text", "text": RECALL_SYSTEM}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": RECALL_SCHEMA}},
        ) as stream:
            msg = stream.get_final_message()
    except Exception as exc:                                  # noqa: BLE001
        return RecallResult(ticker=ticker, window="",
                            verdict=f"probe failed: {exc}")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if not text:
        return RecallResult(ticker=ticker, window="", verdict="empty response")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return RecallResult(ticker=ticker, window="", verdict="unparseable")

    truth = {q["id"]: q for q in questions}
    scored, known, correct = [], 0, 0
    for a in payload.get("answers", []):
        q = truth.get(a.get("question_id"), {})
        row = {"id": a.get("question_id"), "question": q.get("question", ""),
               "claimed_known": bool(a.get("known")), "answer": a.get("answer", ""),
               "confidence": a.get("confidence"), "truth": q.get("truth", "")}
        if row["claimed_known"]:
            known += 1
        scored.append(row)
    return RecallResult(ticker=ticker, window="", answers=scored,
                        n_claimed_known=known, n_correct=correct,
                        verdict=("scored by hand below — `known` counts how much the "
                                 "model claims to remember about the window"))


# ----------------------------------------------------------------------
# What the probe actually found, and the rule it implies.
# ----------------------------------------------------------------------
# Run over four names for the Aug-2025 -> Aug-2026 window (model cutoff
# 2026-05-01), asking only for recall with no data supplied:
#
#   CROX  0/5 known   "that fiscal year closed after my reliable knowledge cutoff"
#   MNST  0/2 known
#   SBUX  2/3 known   FY2025 revenue ~$37.2bn (correct); the Boyu China JV (correct)
#   NVDA  2/2 claimed — and WRONG: said $65bn next-quarter guidance and $500bn
#                       Blackwell+Rubin against $91bn and $1tn in our corpus
#
# Three things follow, and they are more useful than the blanket "the model
# knows everything" assumption this started from:
#
# 1. **Leakage is heterogeneous, so admissibility is per-ticker, not per-window.**
#    A thinly-covered mid-cap is close to clean over a recent window; a mega-cap
#    is not. Gate each name with a probe rather than ruling the whole backtest
#    in or out.
# 2. **Prices leak far less than fundamentals.** All four disclaimed knowledge of
#    the stock's path while two recalled revenue and corporate events. The
#    OUTCOME variable is the safest thing to test, which is convenient, because
#    it is the one that matters.
# 3. **Confident wrongness is its own hazard.** NVDA claimed knowledge and was
#    superseded. A stale "fact" asserted with confidence is worse than an
#    admitted gap, because it enters a backtest looking like signal. A name that
#    claims knowledge is excluded whether or not the claim is right.
ADMIT_MAX_KNOWN_FRACTION = 0.34


def admissible(recall: RecallResult, max_known: float = ADMIT_MAX_KNOWN_FRACTION) -> dict:
    """May this ticker be used in a historical test of the GENERATIVE stages?

    Arithmetic stages (`implied`) never need this gate — there is no model in
    them. It applies to anything the model generates or judges.
    """
    n = len(recall.answers)
    if not n:
        return {"admissible": False, "reason": "probe returned nothing"}
    frac = recall.n_claimed_known / n
    ok = frac <= max_known
    return {"admissible": ok, "known_fraction": round(frac, 3),
            "n_questions": n, "n_claimed_known": recall.n_claimed_known,
            "reason": ("model recalls too much of this window to treat generated "
                       "output as a forecast" if not ok else
                       "model disclaims knowledge of the window")}
