"""Stage 2 — counterfactual theses, generated blind.

**The governing assumption: if it is in our database, it is priced in.** The
news corpus is not a place to look for alpha. It is how we establish the
baseline — what the current price already reflects — and the baseline is what
makes the actual question askable:

    Given everything the price already contains, what would have to be
    FUNDAMENTALLY DIFFERENT for the price to be wrong?

That is a counterfactual, not a forecast and not a stock pitch. It targets a
specific assumption embedded in the price and says what would have to break for
that assumption to fail, and what you would observe first if it were breaking.

**Why blind.** If the generator sees the news corpus it paraphrases it, and
since everything in the corpus is priced in by assumption, a paraphrase is
guaranteed to be worthless. So the generator receives the business
(`BusinessProfile.brief()`), the arithmetic (`ImpliedExpectations.brief()`) and
the reconstructed assumptions (`PricedIn`) — but never the article text those
assumptions were partly derived from.

**Blind is not airtight, and pretending otherwise would be the mistake.** The
model's training data contains years of coverage of these companies, so it
already knows roughly what consensus is. That leak biases generation TOWARD
consensus, which makes counterfactuals harder to find rather than easier — it
fails safe. But it also means a run producing six confident counterfactuals is
better read as evidence the framing is too loose than as six ideas.

**Three requirements**, each learned from a control failure rather than assumed:

* **Name the subject.** A thesis that never names the company or a brand is
  `OFF_TOPIC` and discarded — "margins will expand" is about nobody.
* **Be specific and quantified.** The thesis must state the consolidated revenue
  CAGR it implies, so it can be compared against what the price requires. That
  comparison is arithmetic; embedding similarity to journalism is not, and when
  the two disagreed the arithmetic was right.
* **Carry an observable that is NOT news.** By assumption the news is already in
  the price, so a thesis confirmable only from news is unfalsifiable in advance.
  It must name something measurable outside the corpus.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field

from ..config import LabConfig
from .business import BusinessProfile

log = logging.getLogger(__name__)

SYSTEM = """You generate COUNTERFACTUAL THESES against a stock's priced-in baseline.

You will be given what the market already assumes — reconstructed from the price
itself via a reverse DCF, plus the assumptions that explain it. Treat that
baseline as CORRECT and COMPLETE: everything in it is priced in.

Your job is the counterfactual. For each thesis, pick ONE named assumption in
that baseline and answer: what would have to be fundamentally different about
this business for that assumption to be wrong, and what would you observe first
if it were already starting to break?

This is not a stock pitch, not a price target, not a valuation opinion, and not
a list of reasons the company is good. A thesis that does not contradict a
specific stated assumption is not a counterfactual and will be rejected.

Every thesis MUST:
0. TARGET one named assumption from the priced-in baseline you were given, and
   say which. State plainly what that assumption is and how your thesis breaks it.
1. NAME the company or one of its named brands/products in the statement itself.
   A statement that could be about any company in the sector is rejected.
2. Be SPECIFIC enough to be wrong. Reference a named product, brand, channel,
   geography or customer behaviour — not "international expansion" or "margin
   improvement". State a direction and a rough magnitude where you can.
3. Attach to a REVENUE SEGMENT you were given, and state what share of revenue
   that segment is. A thesis about a 3%-of-revenue segment is worth less than
   the same thesis about a 70% segment, and you must say which it is.
4. Name an OBSERVABLE that is NOT FINANCIAL NEWS. Anything already written up in
   the press is priced in by assumption, so a thesis you could only confirm by
   reading coverage is useless. Name something measurable outside it: consumer
   search or attention to a named product, app ranks, store or location counts,
   street pricing, hiring, unit volumes. Say what would move, in which
   direction, and roughly by how much.
5. Name a FALSIFIER — the observation that would kill the thesis.
6. State CONSOLIDATED_REVENUE_CAGR_IF_TRUE: the total-company revenue CAGR, as a
   decimal (0.04 = 4%), that would result over the horizon if this thesis is
   right and everything else follows its current trajectory. This is the number
   that gets compared against what the price already requires, so derive it from
   the segment shares rather than asserting it.

Generate theses that are genuinely DIFFERENT from each other: different
mechanisms, different segments, different observables. Do not produce six
variations of one idea.

You have NOT been shown the news coverage of this company, and that is
deliberate — everything in it is priced in by assumption, so reproducing it is
worthless. Reason forward from the business and the arithmetic. If you find
yourself writing what you believe consensus already is, you are answering the
wrong question. If you cannot find a genuine counterfactual to a given
assumption, produce fewer theses rather than padding with optimism."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["theses"],
    "properties": {
        "theses": {
            # Structured-output schemas accept neither a minItems above 1 nor
            # maxItems at all, so array length cannot be constrained here. The
            # count is requested in the prompt and verified by the caller.
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "statement", "mechanism", "segment",
                             "materiality_pct", "observable", "data_source",
                             "falsifier", "horizon_months"],
                "properties": {
                    "id": {"type": "string"},
                    "statement": {"type": "string"},
                    "mechanism": {"type": "string"},
                    "segment": {"type": "string"},
                    "materiality_pct": {"type": "number"},
                    "consolidated_revenue_cagr_if_true": {"type": "number"},
                    "targets_assumption": {"type": "string"},
                    "observable": {"type": "string"},
                    "data_source": {
                        "type": "string",
                        "enum": ["consumer_attention", "app_ranks", "web_traffic",
                                 "pricing", "store_or_location_counts", "hiring",
                                 "unit_volumes", "other"]},
                    "falsifier": {"type": "string"},
                    "horizon_months": {"type": "integer"},
                },
            },
        }
    },
}


@dataclass
class GrowthThesis:
    id: str
    statement: str
    mechanism: str
    segment: str
    materiality_pct: float
    observable: str
    data_source: str
    falsifier: str
    horizon_months: int
    consolidated_revenue_cagr_if_true: float = 0.0
    targets_assumption: str = ""
    ticker: str = ""
    rejected: str = ""            # why the contract check dropped it, if it did
    entailment: object = None     # the corpus read, set by iterate_until_novel

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if k != "entailment"}
        d["entailment"] = (self.entailment.to_dict()
                           if hasattr(self.entailment, "to_dict") else None)
        return d


def _client():
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed")
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set")
        return None
    try:
        return anthropic.Anthropic()
    except Exception as exc:                                  # noqa: BLE001
        log.warning("Anthropic client unavailable: %s", exc)
        return None


def check_contract(t: GrowthThesis, entities: list[str]) -> str:
    """Enforce, in code, what the prompt asks for.

    A prompt is a request; this is the check. The saturation metric silently
    reports `OFF_TOPIC` for an unnamed thesis, which would look like "no gap
    found" rather than "the generator ignored the brief" — so the two failures
    are separated here, before scoring.
    """
    low = t.statement.lower()
    named = any(e.lower() in low for e in entities if len(e) > 2)
    if not named:
        return f"names no entity (expected one of {entities[:6]})"
    if len(t.statement.split()) < 8:
        return "statement too short to be falsifiable"
    if not t.observable.strip():
        return "no observable"
    if not t.falsifier.strip():
        return "no falsifier"
    return ""


def generate(profile: BusinessProfile, entities: list[str], n: int = 6,
             model: str | None = None, effort: str = "medium",
             extra_instruction: str = "") -> list[GrowthThesis]:
    """Generate `n` counterfactual theses from the business alone.

    `extra_instruction` carries the rejected-and-why block on later rounds of
    `iterate_until_novel`. It is appended to the USER message, not the system
    prompt, so the stable prefix stays cacheable across rounds.
    """
    client = _client()
    if client is None:
        return []
    model = model or os.environ.get("STRATEGYLAB_MODEL") or LabConfig().llm_model

    user = (f"{profile.brief()}\n\n"
            f"Generate {n} distinct growth theses for {profile.ticker}. "
            f"Reference the segment shares above when stating materiality.")
    if profile.description:
        user += f"\n\nBusiness description (from the company filing):\n{profile.description}"
    if extra_instruction:
        user += "\n" + extra_instruction

    try:
        with client.messages.stream(
            model=model, max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM}],
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": SCHEMA}},
        ) as stream:
            message = stream.get_final_message()
    except Exception as exc:                                  # noqa: BLE001
        log.warning("thesis generation failed: %s", exc)
        return []

    if getattr(message, "stop_reason", None) == "refusal":
        log.warning("generation declined")
        return []
    text = next((b.text for b in message.content if b.type == "text"), None)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("generation returned invalid JSON: %s", exc)
        return []

    out = []
    for d in payload.get("theses", []):
        try:
            t = GrowthThesis(ticker=profile.ticker, **d)
        except TypeError as exc:
            log.debug("skipping malformed thesis: %s", exc)
            continue
        t.rejected = check_contract(t, entities)
        out.append(t)
    return out


# ----------------------------------------------------------------------
# The priced-in narrative — Stage 1.5.
# ----------------------------------------------------------------------
PRICED_IN_SYSTEM = """You reconstruct WHAT IS ALREADY PRICED IN to a stock.

You are given four things:
 (a) the business and its revenue segments,
 (b) a reverse-DCF stating what revenue path the current price requires,
 (c) THE SELL-SIDE ARGUMENT — the spread of individual price targets and the
     questions analysts actually asked management on the last earnings call,
 (d) claims circulating in financial coverage.

**Treat (c) as evidence about the STRUCTURE of the prevailing belief, never as a
forecast to adopt.** A published price target is disseminated the day it prints,
so the number itself is already in the price and carries no information. Two
things about it do carry information:

 - **The dispersion.** When one bank is at $95 with a Sell and another at $163,
   there is no consensus — there are two incompatible models of the company, and
   the axis they disagree on is the most important thing on this page. Never
   average them into a single view and never describe a wide spread as a
   "range"; say what the disagreement is ABOUT.
 - **The questions.** What analysts press management on is what their models
   turn on. If five of eight questions circle one issue, that issue is the
   load-bearing assumption of the entire sell-side view, whether or not it
   appears anywhere in the arithmetic.

Where the call transcript contradicts the arithmetic or the coverage, THE CALL
WINS on matters of fact about the business — management and analysts are
discussing the current quarter, while the reverse-DCF is a mechanical projection
and the coverage may be months stale. Say plainly when this happens.

Your job is NOT to say whether the stock is cheap or expensive, and NOT to give
a price target. It is to answer one question: **what must a marginal buyer at
today's price believe about this business?**

Write the set of assumptions that, taken together, explain the current price.
Be concrete and per-segment where the segment data supports it. Where the
reverse-DCF and the circulating coverage disagree, say so — that disagreement is
itself information.

Then state what the price does NOT appear to assume: outcomes that are plainly
possible for this business and are absent from the implied numbers. Be strict:
list only things the arithmetic actually leaves out, not everything optimistic
you can imagine. These become the targets for counterfactual theses, so each one
must be a specific assumption that could be shown wrong, not a hope.

Treat the circulating claims as ALREADY PRICED IN — they are given to you as
evidence of what the market has digested, never as news. Where a claim and the
arithmetic disagree, the arithmetic is the price and the claim is commentary.

Do NOT assert that something is unpriced if the earnings-call Q&A shows analysts
already modelling it. An assumption contradicted by what management guided to on
the last call is not a gap; it is an error in the reconstruction.

Ground every assumption in a number you were given. An assumption with no number
attached is a guess and does not belong here."""

PRICED_IN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "assumptions", "not_assumed", "tension"],
    "properties": {
        "summary": {"type": "string"},
        "assumptions": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["assumption", "evidence", "segment"],
                "properties": {"assumption": {"type": "string"},
                               "evidence": {"type": "string"},
                               "segment": {"type": "string"}}}},
        "not_assumed": {"type": "array", "items": {"type": "string"}},
        "tension": {"type": "string"},
    },
}


@dataclass
class PricedIn:
    ticker: str
    summary: str
    assumptions: list = field(default_factory=list)
    not_assumed: list = field(default_factory=list)
    tension: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        out = [f"WHAT THE PRICE ASSUMES — {self.ticker}", "", self.summary, ""]
        for a in self.assumptions:
            out.append(f"  - [{a.get('segment', '')}] {a.get('assumption', '')}")
            out.append(f"      evidence: {a.get('evidence', '')}")
        if self.not_assumed:
            out += ["", "  NOT apparently assumed:"]
            out += [f"    - {x}" for x in self.not_assumed]
        if self.tension:
            out += ["", f"  tension: {self.tension}"]
        return "\n".join(out)


def priced_in(profile: BusinessProfile, implied_brief: str, claims: list[str],
              analyst_brief: str = "", model: str | None = None,
              effort: str = "medium") -> PricedIn | None:
    """Reconstruct the assumptions embedded in today's price.

    Three inputs, and the third was the missing one.

    The reverse-DCF says what magnitude the price requires. The coverage says
    what has been MENTIONED. Neither says what the prevailing ARGUMENT is, and
    without that the reconstruction asserts things the market plainly does not
    believe. The first version of this claimed "HEYDUDE never stabilizes; the
    price gives zero credit to a trough" — while on the most recent earnings
    call an analyst asked management about "the recovery in HEYDUDE and the
    expectation for growth in Q4... a pretty steep acceleration that's
    embedded". A recovery was in the guidance. The reconstruction was
    confidently wrong about one of its own six assumptions, and no amount of
    arithmetic would have caught it.

    So the sell-side argument enters as structure, never as a forecast: the
    DISPERSION of individual targets (Goldman $95 Sell against Baird $163 is not
    a range, it is two incompatible models) and the QUESTIONS analysts pressed
    management on (five of eight on one revenue-recognition change is that
    change being the load-bearing assumption of every sell-side model).
    """
    client = _client()
    if client is None:
        return None
    model = model or os.environ.get("STRATEGYLAB_MODEL") or LabConfig().llm_model

    user = f"{profile.brief()}\n\n{implied_brief}\n"
    if analyst_brief:
        user += f"\n{analyst_brief}\n"
    user += (f"\nClaims currently circulating in coverage of {profile.ticker} "
             f"and its peers:\n"
             + "\n".join(f"  - {c}" for c in claims[:40]))
    try:
        with client.messages.stream(
            model=model, max_tokens=12000,
            system=[{"type": "text", "text": PRICED_IN_SYSTEM}],
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema",
                                      "schema": PRICED_IN_SCHEMA}},
        ) as stream:
            message = stream.get_final_message()
    except Exception as exc:                                  # noqa: BLE001
        log.warning("priced-in reconstruction failed: %s", exc)
        return None
    text = next((b.text for b in message.content if b.type == "text"), None)
    if not text:
        return None
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return None
    return PricedIn(ticker=profile.ticker, summary=d.get("summary", ""),
                    assumptions=d.get("assumptions", []),
                    not_assumed=d.get("not_assumed", []),
                    tension=d.get("tension", ""))


# ----------------------------------------------------------------------
# The novelty search — and why it is dangerous.
# ----------------------------------------------------------------------
AVOID_TEMPLATE = """
Your previous attempts were REJECTED because each one is already written up in
the financial press, and by assumption anything already written up is in the
price. Here is what you produced and the article that already covers it:

{rejected}

Do not restate these, and do not produce near-variants of them. If the obvious
angles on this business are all taken, that is itself the finding — produce
fewer theses rather than reaching for something vague. A thesis that survives
only because it is too woolly to match anything is worse than no thesis.
"""


def _avoid_block(rejected: list[tuple]) -> str:
    lines = []
    for t, r in rejected:
        lines.append(f"  - {t.statement[:180]}")
        e = getattr(t, "entailment", None)
        if e is not None and getattr(e, "quote", ""):
            lines.append(f"      already stated in \"{e.source_title[:70]}\": "
                         f"\"{e.quote[:150]}\"")
    return AVOID_TEMPLATE.format(rejected="\n".join(lines))


def iterate_until_novel(profile, entities, scorer, n_per_round: int = 5,
                        max_rounds: int = 4, want: int = 3,
                        effort: str = "medium", log_fn=print) -> dict:
    """Generate, veto against the corpus, feed the rejects back, repeat.

    **This is a search, and searches manufacture false positives.** Generating
    until something clears a filter is the same move as running hypotheses until
    one clears |t| > 2 — do it long enough and the filter is guaranteed to be
    beaten by something, usually by whatever was vaguest rather than whatever
    was truest. The discovery loop answers this by raising its bar with the
    trial count; the same honesty is needed here, but the bar is a corpus match
    and cannot be raised, so the defences are different:

    * **The attempt count is reported next to every survivor.** "3 survived of
      24 attempts" and "3 survived of 5" are completely different claims and
      must not print the same way.
    * **Rounds are capped.** Running until success is not a stopping rule.
    * **Survivors are tiered by how close they came to matching.** A thesis that
      is on-subject but unmatched is a candidate; one that matches nothing at
      all is more likely to be too vague to test than to be original, because
      the corpus is dense on any well-covered name.
    * **Exhaustion is a real answer.** "Every angle on this business is already
      written up" is information, and the loop is allowed to return nothing.
    """
    survivors, rejected_all, attempts = [], [], 0
    for rnd in range(1, max_rounds + 1):
        extra = _avoid_block(rejected_all) if rejected_all else ""
        batch = generate(profile, entities, n=n_per_round, effort=effort,
                         extra_instruction=extra)
        if not batch:
            break
        attempts += len(batch)
        fresh_rejects = []
        for t in batch:
            if t.rejected:
                log_fn(f"   round {rnd}: [{t.id}] dropped by contract — {t.rejected}")
                continue
            # Retrieve with embeddings, judge with a reader. Cosine ruled a
            # school-dress-code thesis covered by a sandals article at 0.75; it
            # can see subject, not proposition.
            from .entail import covered
            r = scorer.score(t.statement)
            ent = covered(t.statement, scorer.retrieve(t.statement, k=10))
            t.entailment = ent
            if ent.verdict == "COVERED":
                fresh_rejects.append((t, r))
            else:
                survivors.append((t, r))
        rejected_all.extend(fresh_rejects)
        log_fn(f"   round {rnd}: {len(batch)} generated, "
               f"{len(fresh_rejects)} already in corpus, "
               f"{len(survivors)} surviving so far")
        if len(survivors) >= want:
            break
    return {"survivors": survivors, "rejected": rejected_all,
            "attempts": attempts, "rounds": rnd if attempts else 0}
