"""Does the coverage actually ASSERT this? — the veto, done by reading.

Embedding similarity was the wrong instrument for the veto and the evidence is
unambiguous. On Crocs it ruled a thesis about *spreading school-district
dress-code bans* already-covered by an article titled *"Crocs Bets Big On
Sandals As It Eyes $500 Million Milestone"* — at 0.75 — and did the same to a
bearish thesis about sub-$15 Temu lookalikes. Both are "about Crocs product
demand", which is all cosine can see. Neither proposition appears in that
article.

Similarity answers *is this the same subject*. The veto needs *is this
proposition asserted*, which is entailment, and entailment needs a reader.

So the two tools are used for what each is good at:

* **Embeddings retrieve.** Pulling the dozen most related passages out of
  hundreds of thousands of chunks is exactly what they are for, and they are
  reliable at it.
* **A model reads.** Given those passages and the proposition, it answers
  whether the text already says this — and must **quote the sentence** that says
  it. The quote requirement is the whole discipline: without it the model
  hand-waves "yes, this is broadly covered" for anything on-topic, which is the
  same failure as cosine with extra steps. With it, a claim of coverage is
  checkable against the corpus in one grep.

The asymmetry from `saturation.py` carries over unchanged. `COVERED` is a
conclusion — it is written up, therefore priced in. `NOT_COVERED` is a
non-answer: our corpus is a sample of the press, so absence from it is a reason
to go and investigate, never a finding.
"""

from __future__ import annotations

import html
import json
import logging
import os
from dataclasses import asdict, dataclass, field

from ..config import LabConfig

log = logging.getLogger(__name__)

# Curly vs straight quotes, dashes: cosmetic differences between what the
# scraper stored and what a model renders back.
_PUNCT = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"',
                        "\u201d": '"', "\u2013": "-", "\u2014": "-",
                        "\u00a0": " "})

SYSTEM = """You decide whether a PROPOSITION about a company is already asserted
in news coverage you are shown.

You are NOT judging whether the proposition is true, likely, or sensible. You
are judging one thing: does this text already say it?

Rules:
- Answer COVERED only if a passage asserts substantially the same proposition.
  You must supply a VERBATIM QUOTE from the supplied text that does so. No
  quote, no COVERED.
- Same SUBJECT is not the same PROPOSITION. An article about a company's sandal
  franchise does not cover a proposition about school dress-code bans, price
  increases, or low-cost competitors, even though all four are "about" that
  company's demand.
- The direction must match. Coverage saying a brand is declining does NOT cover
  a proposition that it stabilises; those are opposite claims about the same
  subject.
- A passing mention is not coverage of a proposition that turns on magnitude. If
  the proposition says a segment reaches 30% of revenue and the text merely
  notes the segment exists, that is PARTIAL, not COVERED.
- If unsure, answer NOT_COVERED. A false COVERED silently discards an idea; a
  false NOT_COVERED sends it on to be investigated, where it will be tested
  anyway. The second error is cheaper."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "reasoning"],
    "properties": {
        "verdict": {"type": "string",
                    "enum": ["COVERED", "PARTIAL", "NOT_COVERED"]},
        "quote": {"type": "string"},
        "source_title": {"type": "string"},
        "reasoning": {"type": "string"},
    },
}


@dataclass
class Entailment:
    verdict: str                  # COVERED | PARTIAL | NOT_COVERED
    reasoning: str = ""
    quote: str = ""
    source_title: str = ""
    n_passages: int = 0
    quote_verified: bool = False  # the quote was actually found in the passages

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


def _norm(s: str) -> str:
    """Normalise for quote verification.

    Article bodies carry raw HTML entities — the corpus contains
    "HEYDUDE&rsquo;s performance" — and a model quoting that text renders the
    apostrophe properly. The quote is then genuinely present and verification
    fails anyway, downgrading a correct COVERED to PARTIAL. Unescaping and
    folding punctuation removes an artifact that would otherwise look like the
    model hand-waving.
    """
    t = html.unescape(s or "").lower()
    t = t.translate(_PUNCT)
    return " ".join(t.split())


def covered(proposition: str, passages: list[tuple[str, str]],
            model: str | None = None, effort: str = "low") -> Entailment:
    """Is `proposition` asserted in `passages`? Each passage is (title, text).

    The returned quote is checked against the supplied passages before the
    verdict is trusted. A COVERED whose quote cannot be found is downgraded to
    PARTIAL — the model has paraphrased rather than located, which is precisely
    the hand-waving the quote requirement exists to catch, and it should not be
    able to veto an idea.
    """
    if not passages:
        return Entailment(verdict="NOT_COVERED", reasoning="no passages retrieved")
    client = _client()
    if client is None:
        return Entailment(verdict="NOT_COVERED",
                          reasoning="no LLM available; cannot judge entailment")
    model = model or os.environ.get("STRATEGYLAB_MODEL") or LabConfig().llm_model

    body = "\n\n".join(
        f"[{i+1}] {title}\n{text.strip()[:1400]}"
        for i, (title, text) in enumerate(passages))
    user = (f"PROPOSITION:\n{proposition}\n\n"
            f"COVERAGE ({len(passages)} passages, the most related in our corpus):\n"
            f"{body}")
    try:
        with client.messages.stream(
            model=model, max_tokens=4000,
            system=[{"type": "text", "text": SYSTEM}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": SCHEMA}},
        ) as stream:
            msg = stream.get_final_message()
    except Exception as exc:                                  # noqa: BLE001
        log.warning("entailment call failed: %s", exc)
        return Entailment(verdict="NOT_COVERED", reasoning=f"call failed: {exc}")

    text = next((b.text for b in msg.content if b.type == "text"), None)
    if not text:
        return Entailment(verdict="NOT_COVERED", reasoning="empty response")
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return Entailment(verdict="NOT_COVERED", reasoning="unparseable response")

    e = Entailment(verdict=d.get("verdict", "NOT_COVERED"),
                   reasoning=d.get("reasoning", ""), quote=d.get("quote", ""),
                   source_title=d.get("source_title", ""), n_passages=len(passages))
    if e.quote:
        hay = _norm(" ".join(t for _, t in passages))
        needle = _norm(e.quote)[:160]
        e.quote_verified = bool(needle) and needle in hay
    if e.verdict == "COVERED" and not e.quote_verified:
        e.verdict = "PARTIAL"
        e.reasoning = ("quote not found verbatim in the passages, so downgraded: "
                       + e.reasoning)
    return e
