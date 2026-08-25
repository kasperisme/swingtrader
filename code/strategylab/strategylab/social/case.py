"""One rejected model, reconstructed — the analyst's case plus what the corpus says.

`vote.py` identifies published models the price declines to pay for. Each is a
specific, professionally-modelled argument that is *known* (it was published) and
*not believed* (the market is not paying it). This module turns one of those into
an investigable case.

**Two sources, deliberately.** The analyst position alone is thin: a target, a
headline, and one question from an earnings call. Building the case on that would
reconstruct the sell-side's view and nothing else, which is a narrow and
self-referential picture of why a price is where it is. So the corpus is
retrieved against the position's own drivers and supplies the rest — what has
actually been reported about the mechanisms the analyst is betting on, including
the parts that cut against them.

That combination is the point. The analyst says where to look; the articles say
what is there. Neither alone is enough:

* Analyst-only -> a summary of one bank's model, with no independent evidence.
* Corpus-only  -> the drift of coverage, with nobody's actual model behind it.

**What this is not.** It is not a judgement about whether the analyst is right.
The output is a reconstruction plus the observable that would settle it — the
probability comes later, from investigation against data that is not news, and
by assumption everything used here is already in the price.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

log = logging.getLogger(__name__)

ENDORSED_SYSTEM = """You reconstruct the published analyst case the market IS paying for.

This model sits at or near the current price. That makes it the most direct
evidence available of what the price actually contains — more direct than any
reverse-DCF, because a professional wrote down the assumptions and the market
is paying roughly that number.

State, as precisely as the evidence allows:

1. THE CASE — what this analyst assumes to arrive at a target the market agrees
   with. Ground it in the segments and numbers supplied.
2. LOAD-BEARING — the assumption this consensus view most depends on. If the
   analyst's own question to management is supplied, weight it heavily.
3. WHAT IT TAKES FOR GRANTED — the things this model assumes without arguing for
   them. These are the deepest part of what is priced in, because nobody is even
   debating them, and they are what a surprise would have to overturn.
4. WHAT WOULD BREAK IT — one observable, measurable OUTSIDE financial news, that
   would show this consensus view failing. News is already in the price, so a
   test you could only run by reading articles settles nothing.

You are NOT asked whether the consensus is right. You are asked what it consists
of. Where the retrieved coverage contradicts the model, say so — a consensus
resting on facts the coverage undercuts is a fragile consensus, and that is
worth knowing."""

SYSTEM = """You reconstruct a published analyst case that the market is NOT paying for.

You are given: the company and its segments; what the price arithmetically
requires; ONE analyst's published target and (where available) the question they
put to management on the last earnings call; and passages retrieved from news
coverage that bear on the drivers of that case.

The market has seen this target and is not paying it. Your job is to state, as
precisely as the evidence allows:

1. THE CASE — what this analyst must believe to reach that target. Ground it in
   the segments and the numbers you were given, not in generic optimism.
2. LOAD-BEARING — the single assumption the case turns on. If the analyst's own
   question to management is supplied, weight it heavily: analysts press on what
   their model is most exposed to.
3. THE MARKET'S OBJECTION — why a rational marginal buyer declines to pay this.
   This is the counter-argument and it must be real, not a strawman. If the
   coverage contains evidence against the case, use it.
4. WHAT WOULD SETTLE IT — one observable, measurable OUTSIDE financial news,
   that would distinguish the analyst being right from the market being right.
   News coverage is already in the price, so a test you could only run by
   reading articles settles nothing.

Use the retrieved passages as evidence about the drivers, and say plainly where
they support the case and where they undercut it. Where a passage contradicts
the analyst, say so — a reconstruction that only marshals supporting evidence is
worthless for deciding whether the market is right.

If the evidence is too thin to reconstruct the case, say so rather than
inventing a rationale. "This target is not explicable from what we can see" is a
legitimate and useful answer."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["case", "load_bearing", "market_objection", "observable",
                 "evidence_for", "evidence_against", "confidence_in_reconstruction"],
    "properties": {
        "case": {"type": "string"},
        "load_bearing": {"type": "string"},
        "market_objection": {"type": "string"},
        "observable": {"type": "string"},
        "data_source": {"type": "string",
                        "enum": ["consumer_attention", "app_ranks", "web_traffic",
                                 "pricing", "store_or_location_counts", "hiring",
                                 "unit_volumes", "other"]},
        "evidence_for": {"type": "array", "items": {"type": "string"}},
        "evidence_against": {"type": "array", "items": {"type": "string"}},
        "confidence_in_reconstruction": {
            "type": "string", "enum": ["high", "medium", "low", "not_explicable"]},
    },
}


@dataclass
class Case:
    ticker: str
    firm: str
    analyst: str
    target: float
    implied_move: float
    stance: str
    case: str = ""
    load_bearing: str = ""
    market_objection: str = ""
    observable: str = ""
    data_source: str = ""
    evidence_for: list = field(default_factory=list)
    evidence_against: list = field(default_factory=list)
    confidence: str = ""
    n_passages: int = 0
    sources: list = field(default_factory=list)
    retrieval: dict = field(default_factory=dict)
    # Which model reconstructed this case. A batch pass mixes backends — a
    # ticker retried after a chain failure can be answered by a different model
    # than its neighbours — so the row has to say, not the run.
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        arrow = {"rejected_bull": "BULL", "rejected_bear": "BEAR"}.get(
            self.stance, "CONSENSUS")
        out = [f"[{arrow}] {self.firm} ${self.target:,.0f} ({self.implied_move:+.0%})"
               + (f" — {self.analyst}" if self.analyst else ""),
               f"   reconstruction confidence: {self.confidence} "
               f"({self.n_passages} passages"
               + ("" if self.retrieval.get("selective", True)
                  else f"; NOT SELECTIVE — only "
                       f"{self.retrieval.get('distinct_articles', 0)} articles exist, "
                       f"so this is most of the corpus, not a targeted pull")
               + ")",
               f"   THE CASE       {self.case}",
               f"   LOAD-BEARING   {self.load_bearing}",
               f"   MARKET SAYS    {self.market_objection}",
               f"   SETTLED BY     {self.observable}  [{self.data_source}]"]
        if self.evidence_for:
            out.append("   corpus FOR     " + "; ".join(e[:110] for e in self.evidence_for[:2]))
        if self.evidence_against:
            out.append("   corpus AGAINST " + "; ".join(e[:110] for e in self.evidence_against[:2]))
        return "\n".join(out)


def _retrieval_query(position, business) -> str:
    """What to pull from the corpus for this position.

    Built from the analyst's own question where there is one, because that is
    the driver they are exposed to, and from the target headline otherwise.
    Falling back to the ticker alone would retrieve the company's general
    coverage and tell us nothing specific to the case.
    """
    bits = [business.company or position.firm]
    if position.call_question:
        bits.append(position.call_question[:400])
    if position.headline:
        bits.append(position.headline)
    if not position.call_question and not position.headline:
        bits.append(f"{business.ticker} growth drivers and outlook")
    return " ".join(bits)


def build(position, space, business, implied_brief: str, k: int = 12,
          model: str | None = None, effort: str = "medium") -> Case:
    """Reconstruct one published model against the corpus.

    Handles BOTH stances, and the endorsed one is not an afterthought. Across
    twelve tickers, 93 of 303 published models were endorsed and 54 more sat in
    the neutral band — 49% of all evidence about the price, reaching the
    decomposition as a bare list of firm and target while the rejected models
    got full reconstructions. For Walmart that meant 51 of 54 models describing
    what the price contains were ignored in favour of 3 outliers describing what
    it does not. Since the question is what IS priced in, the model the market
    is paying is the primary evidence, not the footnote.
    """
    from .llm import available as _llm_available, complete_json

    c = Case(ticker=business.ticker, firm=position.firm, analyst=position.analyst,
             target=position.target, implied_move=position.implied_move,
             stance=position.stance)
    ok, why = _llm_available()
    if not ok:
        c.confidence = "not_explicable"
        c.case = f"no LLM available: {why}"
        return c

    # own_only: a case about this company's drivers must not be evidenced by a
    # peer's strategy article.
    passages = space.retrieve(_retrieval_query(position, business), k=k,
                              own_only=True)
    c.n_passages = len(passages)
    c.retrieval = space.retrieval_discrimination(k, own_only=True)
    c.sources = sorted({t for t, _ in passages if t})[:8]

    body = "\n\n".join(f"[{i+1}] {t}\n{x.strip()[:1200]}"
                       for i, (t, x) in enumerate(passages))
    endorsed = position.stance in ("endorsed", "neutral")
    header = ("THE POSITION THE MARKET IS ROUGHLY PAYING:"
              if endorsed else "THE POSITION THE MARKET IS NOT PAYING FOR:")
    user = (f"{business.brief()}\n\n{implied_brief}\n\n"
            f"{header}\n"
            f"  {position.firm} target ${position.target:,.0f} "
            f"({position.implied_move:+.0%} from the current price), "
            f"published {position.published}\n"
            f"  headline: {position.headline or '(none)'}\n"
            + (f"  this analyst asked management: \"{position.call_question}\"\n"
               if position.call_question else "")
            + (f"  management answered ({position.answered_by}): "
               f"\"{position.answer[:600]}\"\n"
               if getattr(position, 'answer', '') else "")
            + f"\nRETRIEVED COVERAGE ({len(passages)} passages):\n{body}")

    res = complete_json(ENDORSED_SYSTEM if endorsed else SYSTEM, user, SCHEMA,
                        max_tokens=8000, effort=effort, model=model)
    c.model = res.model
    if not res.ok:
        log.warning("case reconstruction failed for %s: %s", position.firm,
                    res.error)
        c.confidence = "not_explicable"
        c.case = f"reconstruction failed: {res.error}"
        return c

    d = res.data
    c.case = d.get("case", "")
    c.load_bearing = d.get("load_bearing", "")
    c.market_objection = d.get("market_objection", "")
    c.observable = d.get("observable", "")
    c.data_source = d.get("data_source", "")
    c.evidence_for = d.get("evidence_for", [])
    c.evidence_against = d.get("evidence_against", [])
    c.confidence = d.get("confidence_in_reconstruction", "")
    return c
