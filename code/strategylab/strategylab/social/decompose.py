"""How much is priced in — the decomposition this whole construction is for.

Every stage before this one produces an input to a single question: **what does
the current price already pay for, and how much is each unpriced piece worth?**

    implied.py   the arithmetic — what revenue path the price requires
    analyst.py   the articulated views, and what their authors press on
    vote.py      where the price sits among them: endorsed vs rejected
    narrative.py the propositions in circulation, each with its scored impact
    tools.py     non-news measurement, where any exists
    -> here      per driver: how much of it is in the price, and what it is worth
    case.py      then investigates EACH driver this produces, one case per driver

Note the order, because it was the other way round and the inversion is the
point. `case.py` used to run first and reconstruct published analyst models,
which this module consumed. That made the decomposition downstream of a
firm-by-firm view and left the two outputs unjoinable — drivers keyed to
assumptions, cases keyed to banks. The price is the vote, so the drivers come
first and a case is now the evidence behind one of them.

**Why the value of an unpriced driver is measurable at all.** The published
models bracket the price. If a bank at $163 reaches that number largely on one
assumption the price does not share, then the distance between $163 and the
current price is an upper bound on what that assumption is worth if it proves
out. That is a real, if coarse, quantification — and it comes from professionals'
own models rather than from a discount rate we guessed.

Three disciplines carried in from earlier failures:

* **A driver in the corpus is priced in.** Being written up is the definition of
  known, so `entail.py`'s verdict is an input, not an opinion.
* **Bound, do not point-estimate.** "Worth up to $41, i.e. 33% of the price" is
  supportable from the model spread. "Worth $41" is not.
* **Say when it cannot be measured.** The observable that would settle Crocs is
  weekly markdown depth, and no tool here can read it. A decomposition that
  quietly swapped in a weaker proxy would be worse than one that reports the
  gap, so `testable` is carried per driver and printed.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from .tools import OBSERVABLE_COVERAGE

log = logging.getLogger(__name__)

SYSTEM = """You decompose a share price into what it already pays for and what it does not.

You are NOT deciding whether the company is a good investment, and NOT producing
a target. You are answering one question per driver: **how much of this is
already in the price?**

You are given: the business and its segments; the reverse-DCF path the price
requires; the full spread of published analyst models with where the price sits
among them; the propositions currently circulating in the news about this
company, each with the signed market impact its coverage carried; and a
statement of which observables can actually be measured with the data
available.

The circulating propositions are what the market has already been told, which by
assumption is what the price has already absorbed. Use them to decide what is
PRICED, never as evidence that something is TRUE.

**Write for an intelligent non-specialist, not for a sell-side desk.** This is
read on a public quote page. The reasoning must stay exact, but the language
must not assume the reader knows the trade:

 - Say what a term means the first time it earns its place. "trading at 35 times
   earnings, versus 12-18 times through the 2010s" — not "a 35x re-rating".
 - Ban the desk shorthand entirely: no "de-rate", "re-rate", "multiple
   compression", "run-rate", "TAM", "bps", "the print", "the tape", "legs",
   "bounded below", "load-bearing", "the annuity".
 - Prefer the plain verb. "the price already assumes" beats "is discounted in";
   "if that stops happening" beats "on normalization".
 - Keep every number — percentages, dollar figures, multiples and target levels
   are the substance. It is the vocabulary around them that changes, not them.
 - One idea per bullet, and say the consequence, not just the mechanism.

A reader who has never opened a broker note should finish each bullet knowing
what is being claimed and why it matters.

**Never write a literal share price in the prose.** Write the token `{price}`
wherever you would name the current price, and the renderer substitutes the live
quote. A price baked into the text is wrong the day after it is written, and it
is the one number on the page that is already displayed accurately elsewhere.

Percentages, multiples, CAGRs and target levels ARE analysis outputs and should
be stated plainly — it is only the subject's own current price that is
substituted.

Write the summary as four separate parts — `position`, `pays_for`, `declines`
and `crux`. Do not write one long paragraph and split it arbitrarily: each part
answers a different question and is read on its own. Keep list items to a single
clause carrying its own number.

For each driver, give:
 - PRICED_IN_PCT: 0 to 100. How much of this driver's plausible value the current
   price already reflects. 100 means fully paid for; 0 means the price gives it
   no credit at all.
 - VALUE_IF_TRUE_PCT: what the driver is worth, as a percentage of the current
   price, if it proves out. BOUND IT using the published models — if a bank
   reaching a target 31% above the price rests mainly on this driver, then ~31%
   is the upper bound, not a point estimate. Never invent a number the model
   spread does not support.
 - BASIS: the specific evidence for the priced_in figure. Cite the arithmetic,
   the model spread, or a passage. An unsourced percentage is worthless here.
 - OBSERVABLE: the kind of measurement that would settle this driver, chosen
   from the observable kinds listed below and written with that exact key. Each
   driver is investigated separately afterwards and the measurement is dispatched
   off this key, so an invented one silently costs that driver its evidence.
 - TESTABLE: whether the supplied tool coverage can actually measure this
   driver's observable. Say false when it cannot; do not substitute a proxy.

Rules:
 - If a driver appears in the news corpus it is priced in by assumption. The
   question is then how much of its VALUE the price reflects, not whether the
   market has heard of it.
 - Drivers where the price and the published models agree are ~100% priced and
   are the least interesting; still list them, because knowing what the price
   HAS paid for is half the answer.
 - Prefer few well-evidenced drivers to many speculative ones."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["position", "pays_for", "declines", "crux", "drivers",
                 "unpriced_total_pct", "confidence"],
    "properties": {
        # Structured rather than one block of prose. The unstructured version
        # produced a genuinely good ~1,500-character paragraph that nobody could
        # read on a page: the position, the paid-for list, the declined list and
        # the crux were all in there, run together. Splitting them at generation
        # is better than parsing them out afterwards, because the model already
        # knows which sentence is doing which job.
        "position": {"type": "string",
                     "description": "ONE sentence: where the price sits versus "
                                    "the published models, and what that says."},
        "pays_for": {"type": "array", "items": {"type": "string"},
                     "description": "What the price fully reflects. Each item one "
                                    "clause with its number, not a paragraph."},
        "declines": {"type": "array", "items": {"type": "string"},
                     "description": "What the price does NOT pay for, each with "
                                    "what it would be worth."},
        "crux": {"type": "string",
                 "description": "The single investigable question, and whether "
                                "anything wired can actually settle it."},
        "drivers": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["driver", "segment", "priced_in_pct",
                             "value_if_true_pct", "basis", "testable"],
                "properties": {
                    "driver": {"type": "string"},
                    "segment": {"type": "string"},
                    "priced_in_pct": {"type": "number"},
                    "value_if_true_pct": {"type": "number"},
                    "basis": {"type": "string"},
                    "testable": {"type": "boolean"},
                    # Closed, not free text. `case.py` looks this key up in
                    # tools.OBSERVABLE_COVERAGE to decide which series to run,
                    # so a driver whose observable is invented gets no
                    # measurement at all — silently, which is the worst way to
                    # lose evidence.
                    "observable": {"type": "string",
                                   "enum": list(OBSERVABLE_COVERAGE)},
                }}},
        "unpriced_total_pct": {"type": "number"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}


@dataclass
class Decomposition:
    ticker: str
    price: float
    summary: str = ""            # flat join, kept for existing readers
    position: str = ""
    pays_for: list = field(default_factory=list)
    declines: list = field(default_factory=list)
    crux: str = ""
    drivers: list = field(default_factory=list)
    unpriced_total_pct: float = 0.0
    confidence: str = ""
    model_span: str = ""
    # The model that produced this allocation. `priced_in_pct` is the judged,
    # unvalidated tier, so which model judged it is part of the result.
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        out = [f"HOW MUCH IS PRICED IN — {self.ticker} @ ${self.price:,.2f}",
               f"  {self.model_span}", ""]
        if self.position:
            out += [self.position, ""]
        if self.pays_for:
            out += ["  THE PRICE PAYS FOR:"] + [f"    - {x}" for x in self.pays_for] + [""]
        if self.declines:
            out += ["  IT DECLINES TO PAY FOR:"] + [f"    - {x}" for x in self.declines] + [""]
        if self.crux:
            out += [f"  CRUX: {self.crux}", ""]
        out += [
               f"  {'driver':<44}{'priced':>8}{'worth':>8}  testable",
               "  " + "-" * 74]
        for d in sorted(self.drivers, key=lambda x: x.get("priced_in_pct", 100)):
            out.append(f"  {d.get('driver','')[:42]:<44}"
                       f"{d.get('priced_in_pct',0):>7.0f}%"
                       f"{d.get('value_if_true_pct',0):>7.0f}%"
                       f"  {'yes' if d.get('testable') else 'NO'}")
        out.append("")
        out.append(f"  Unpriced value across drivers, bounded by the model spread: "
                   f"~{self.unpriced_total_pct:.0f}% of price "
                   f"(reconstruction confidence: {self.confidence})")
        untestable = [d for d in self.drivers if not d.get("testable")]
        if untestable:
            out.append(f"\n  {len(untestable)} of {len(self.drivers)} drivers cannot be "
                       f"measured with the data wired up:")
            for d in untestable:
                out.append(f"    - {d.get('driver','')[:60]} "
                           f"({d.get('observable','no observable stated')[:60]})")
        return "\n".join(out)


def build(business, implied_brief: str, vote, claims: list, tool_coverage: dict,
          model: str | None = None, effort: str = "medium") -> Decomposition | None:
    """Decompose the price into paid-for and not-paid-for.

    `claims` are `narrative.Claim`s — the propositions in circulation with their
    signed impact. They replaced a block of reconstructed analyst models, which
    used to be this call's evidence. The models were a second description of the
    same price keyed to firms; the claims are what the market has actually been
    told, which is the thing the drivers are a decomposition OF.
    """
    from .llm import available as _llm_available, complete_json

    ok, why = _llm_available()
    if not ok:
        log.warning("decomposition skipped: %s", why)
        return None

    top = sorted(claims, key=lambda c: -getattr(c, "weight", 0.0))[:24]
    claim_block = ("PROPOSITIONS IN CIRCULATION (signed market impact, most "
                   "weighted first):\n" +
                   "\n".join(f"  [{c.impact:+.2f}] {c.published}  {c.text[:240]}"
                             for c in top)) if top else (
        "PROPOSITIONS IN CIRCULATION: none scored in the window — the coverage "
        "is too thin to say what the market has been told.")

    cov = "\n".join(f"  {k}: {'MEASURABLE via ' + v['tool'] if v['testable'] else 'NOT MEASURABLE — ' + v['note']}"
                    for k, v in tool_coverage.items())

    user = (f"{business.brief()}\n\n{implied_brief}\n\n{vote.brief()}\n\n"
            f"{claim_block}\n\n"
            f"WHAT THE AVAILABLE DATA CAN AND CANNOT MEASURE:\n{cov}\n\n"
            f"Decompose the current price (write it as the token {{price}}, never "
            f"as a figure — it is ${vote.price:,.2f} today): which drivers does it already "
            f"pay for, and how much is each unpriced piece worth, bounded by the "
            f"published model spread (${vote.low:,.0f}..${vote.high:,.0f})?")
    res = complete_json(SYSTEM, user, SCHEMA, max_tokens=12000, effort=effort,
                        model=model, thinking=True)
    if not res.ok:
        log.warning("decomposition failed for %s: %s", business.ticker, res.error)
        return None
    d = res.data
    position = d.get("position", "")
    pays = [x for x in (d.get("pays_for") or []) if str(x).strip()]
    decl = [x for x in (d.get("declines") or []) if str(x).strip()]
    crux = d.get("crux", "")
    # A flat rendering so anything still reading `summary` keeps working.
    flat = " ".join(filter(None, [
        position,
        ("The price pays for: " + "; ".join(pays) + ".") if pays else "",
        ("It declines to pay for: " + "; ".join(decl) + ".") if decl else "",
        crux]))
    return Decomposition(
        ticker=business.ticker, price=vote.price, summary=flat,
        position=position, pays_for=pays, declines=decl, crux=crux,
        drivers=d.get("drivers", []),
        unpriced_total_pct=float(d.get("unpriced_total_pct") or 0),
        confidence=d.get("confidence", ""),
        model=res.model,
        model_span=(f"{vote.n_targets} published models ${vote.low:,.0f}.."
                    f"${vote.high:,.0f}, median ${vote.median:,.0f}; "
                    f"{vote.lean}"))
