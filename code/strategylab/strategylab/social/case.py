"""One driver, investigated — the case FOR a piece of the decomposition.

**This module used to reconstruct an analyst.** It took a published target the
price declines to pay and rebuilt the argument behind it. That answered a
question this programme is not actually asking. The price is the vote; the whole
construction works BACKWARDS from it — `implied.py` says what the price
arithmetically requires, `vote.py` says where it sits among the published models,
`decompose.py` breaks it into the drivers it does and does not pay for. A
per-analyst reconstruction sat outside that chain as a second, parallel way of
describing the same price, keyed to firms rather than to drivers, and nothing
downstream could join the two.

So a case is now an extension of a driver, one per driver, and it asks the
question the decomposition leaves open: **what do we actually know about this
assumption, and what could we measure to know more?**

Three sources, and they answer different questions. Keeping them apart is the
entire discipline of this module:

* **The scored coverage** (`narrative_read`) — how many claims in circulation
  bear on this driver, and their signed impact. This is evidence about how
  KNOWN the driver is, never about whether it is true. Being written up is the
  definition of known, and by the governing assumption known is priced. A driver
  the coverage is loud about is one the price has already heard.

* **The retrieved passages** — what that coverage actually says, in its own
  words, for and against. A reader, not a cosine: `entail.py` learned that
  similarity answers "same subject" where the question is "asserted or not".

* **The measurement** (`measure`) — the non-news series wired for this driver's
  observable, where one exists. This is the only source here that can speak to
  whether the driver is TRUE, precisely because the market has not already
  digested it. Most drivers have no such series and the honest output is to say
  so; `tools.py` reports the gap rather than substituting a proxy, and so does
  this module.

**What this is not.** It does not re-judge `priced_in_pct`. The decomposition
owns that number, unvalidated as it is, and a second model quietly revising it
would produce two estimates with one label. This module supplies the evidence a
reader needs to judge the number themselves.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import numpy as np

log = logging.getLogger(__name__)

SYSTEM = """You investigate ONE assumption behind a share price.

The price is the vote. Arithmetic has already worked backwards from it to this
driver and judged how much of the driver the price appears to reflect. You are
NOT re-deciding that share, and you are NOT producing a target or a
recommendation. You are stating what is known about this one assumption and what
it would take to know more.

You are given: the company and its segments; what the price arithmetically
requires; the driver, with the share of it already judged priced and what it is
worth if it proves out; a measured read of the scored news coverage on this
driver; passages retrieved from that coverage; and the result of whatever
non-news measurement is wired for the driver's observable — or a statement that
none is.

The three sources answer different questions and you must not blur them:

 - COVERAGE tells you how KNOWN this driver is. Being written up is the
   definition of known, and known is by assumption already in the price. Loud
   coverage is evidence the price has heard it, never evidence that it is true.
 - The PASSAGES tell you what is actually being asserted, in whose words, and
   where the reporting cuts against the driver.
 - The MEASUREMENT is the only thing here that speaks to whether the driver is
   TRUE, because it is the only thing the market has not already read.

State, as precisely as the evidence allows:

1. WHAT THE COVERAGE SAYS — the narrative in circulation about this driver, and
   how settled it is. Use the claim count and the signed impact you were given;
   say plainly when the coverage is thin, because thin coverage is a reason to
   go and look, not a finding.
2. EVIDENCE FOR and EVIDENCE AGAINST — what the passages assert on each side.
   Ground every item in a passage; an item you cannot point at is an opinion.
   Where the coverage undercuts the driver, say so — a case that only marshals
   supporting evidence is worthless for deciding anything.
3. WHAT THE DATA SHOWS — read the supplied measurement and say what it does and
   does not establish. If nothing is wired, say that outright. NEVER substitute a
   number from the news for a measurement: the news is the thing already priced.
4. WHAT WOULD STILL SETTLE IT — the specific observation that would move this
   driver from argued to observed, and whether any source we have could carry
   it. "Nothing available can settle this" is a legitimate and useful answer,
   and it is the common one.

Write for an intelligent non-specialist. Keep every number. Ban the desk
shorthand — no "de-rate", "re-rate", "multiple compression", "run-rate", "TAM",
"bps", "the print". Never write the company's current share price as a figure:
write the token {price} and it is substituted at render time.

Cite a passage by the number it is given below, in the form (Passage 4) or
(Passages 4, 7) — that exact form, never "Passage [4]" and never a range. Those
numbers are rendered as links to the article the passage came from, so a number
outside the range you were given points the reader at nothing. Cite wherever you
lean on a passage, in every field.

If the evidence is too thin to say anything specific, say so rather than
inventing a narrative."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["what_coverage_says", "evidence_for", "evidence_against",
                 "what_the_data_shows", "still_needed", "confidence"],
    "properties": {
        "what_coverage_says": {"type": "string"},
        "evidence_for": {"type": "array", "items": {"type": "string"}},
        "evidence_against": {"type": "array", "items": {"type": "string"}},
        "what_the_data_shows": {"type": "string"},
        "still_needed": {"type": "string"},
        "confidence": {"type": "string",
                       "enum": ["high", "medium", "low", "not_explicable"]},
    },
}


@dataclass
class Case:
    """The evidence behind one driver. Joined to `drivers_json` on `driver_index`."""
    ticker: str
    # The join key. `driver_index` is positional into the decomposition's
    # drivers array and is what the UI matches on; `driver` is the same row's
    # text, carried so the pairing is checkable by eye and survives a reorder.
    driver_index: int
    driver: str
    segment: str = ""
    priced_in_pct: float | None = None
    value_if_true_pct: float | None = None
    observable: str = ""
    testable: bool = False

    # Measured, not judged: how loudly the scored coverage speaks to this driver.
    narrative: dict = field(default_factory=dict)
    # The non-news series for this driver's observable, or the stated gap.
    measurement: dict = field(default_factory=dict)

    # The reading.
    what_coverage_says: str = ""
    evidence_for: list = field(default_factory=list)
    evidence_against: list = field(default_factory=list)
    what_the_data_shows: str = ""
    still_needed: str = ""
    confidence: str = ""

    n_passages: int = 0
    # [{title, slug}]. The slug is what makes a cited headline a link to the
    # article page; it is None when the corpus row has no slug, and the UI
    # renders those as plain text rather than a broken link.
    sources: list = field(default_factory=list)
    # [{n, title, slug}] — the retrieved passages IN THE ORDER THEY WERE
    # NUMBERED FOR THE MODEL, which is what makes a "(Passage 4)" citation in
    # the reading resolvable to the article it came out of.
    #
    # `sources` cannot do that job and must not be used for it: it is
    # deduplicated and sorted by title, so passage 4 of twelve is not its
    # fourth entry and usually is not even in the same position. Linking a
    # citation through `sources` would attribute a sentence to the wrong
    # article, which is worse than leaving it unlinked.
    passages: list = field(default_factory=list)
    retrieval: dict = field(default_factory=dict)
    # A batch pass mixes backends — a ticker retried after a chain failure can be
    # answered by a different model than its neighbours — so the row says, not
    # the run.
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        nar = self.narrative or {}
        out = [f"[driver {self.driver_index + 1}] {self.driver[:70]}",
               f"   priced {self.priced_in_pct:.0f}%" if self.priced_in_pct is not None
               else "   priced —",
               f"   coverage       {nar.get('n_related', 0)} related claims, "
               f"net impact {nar.get('net_impact', 0):+.2f} "
               f"({nar.get('positive', 0)}+/{nar.get('negative', 0)}-)",
               f"   measurement    " + (
                   f"{self.measurement.get('tool')} ran"
                   if self.measurement.get("result") is not None
                   else f"NOT WIRED — {self.measurement.get('note', 'no observable')[:60]}"),
               f"   COVERAGE SAYS  {self.what_coverage_says}",
               f"   DATA SHOWS     {self.what_the_data_shows}",
               f"   STILL NEEDED   {self.still_needed}"]
        if self.evidence_for:
            out.append("   corpus FOR     " + "; ".join(e[:110] for e in self.evidence_for[:2]))
        if self.evidence_against:
            out.append("   corpus AGAINST " + "; ".join(e[:110] for e in self.evidence_against[:2]))
        return "\n".join(out)


# ----------------------------------------------------------------------
def narrative_read(space, driver_text: str, claims: list, top_k: int = 6) -> dict:
    """How loudly, and in which direction, the scored coverage speaks to a driver.

    Deterministic. `space.claim_vecs` is built from `own_claims` in the order it
    was given them, so the vectors align positionally with the `Claim` objects
    the caller passes here — which is what makes a signed impact available per
    claim rather than an unlabelled similarity.

    The relatedness bar is measured off this ticker's own distribution (mean +
    1 sd) rather than chosen. A fixed cosine threshold is the mistake
    `saturation.py` documents at length: it does not survive a different
    embedding model, a different company, or a thinner corpus, and it silently
    admitted word salad the one time it was guessed.
    """
    from .saturation import _unit, embed

    vecs = getattr(space, "claim_vecs", None)
    if vecs is None or not len(vecs) or not claims:
        return {"n_claims_scanned": 0, "n_related": 0, "net_impact": 0.0,
                "positive": 0, "negative": 0, "top": [],
                "note": "no scored claims in the corpus for this ticker"}

    n = min(len(vecs), len(claims))
    sims = (vecs[:n] @ _unit(embed(driver_text))).astype(float)
    bar = float(sims.mean() + sims.std())
    order = np.argsort(-sims)[:top_k]
    related = [i for i in order if sims[i] >= bar]
    # Nothing clears the bar on a corpus that is uniformly on-topic; fall back to
    # the single nearest claim rather than reporting silence, and say which
    # happened so the reader can tell a real hit from a floor.
    chosen = related or list(order[:1])

    impacts = [float(claims[i].impact) for i in chosen]
    return {
        "n_claims_scanned": n,
        "n_related": len(related),
        "net_impact": float(np.mean(impacts)) if impacts else 0.0,
        "positive": sum(1 for x in impacts if x > 0.15),
        "negative": sum(1 for x in impacts if x < -0.15),
        "top": [{"text": claims[i].text[:400],
                 "impact": float(claims[i].impact),
                 "published": str(claims[i].published),
                 "similarity": round(float(sims[i]), 3)} for i in chosen],
        "note": ("" if related else
                 "no claim clears this corpus's own relatedness bar — the "
                 "coverage does not speak to this driver directly"),
    }


def measure(ticker: str, driver: dict, entity: str = "") -> dict:
    """Run the non-news series wired for this driver's observable, if any.

    The registry is deliberately small and mostly says no. That is the point:
    `tools.py` reports which observables are reachable rather than swapping in a
    weaker proxy, and a case that quietly did the swap would be the most
    damaging thing in this file.
    """
    from .tools import TOOLS, coverage_report

    kind = str(driver.get("observable") or "").strip()
    rep = coverage_report(kind) if kind else {
        "kind": "", "testable": False, "tool": None,
        "note": "the decomposition named no observable for this driver"}
    out = {**rep, "result": None, "error": ""}
    if not rep.get("testable") or not rep.get("tool"):
        return out
    fn = TOOLS.get(rep["tool"])
    if fn is None:
        out["error"] = f"tool {rep['tool']!r} is named by the coverage map but not registered"
        return out
    try:
        if rep["tool"] == "attention_series":
            out["result"] = fn(ticker, entity or ticker)
        else:
            out["result"] = fn(ticker)
    except Exception as exc:                                  # noqa: BLE001
        # A dead data source is a fact about the evidence, not a reason to lose
        # the case: the reading still runs, with the gap stated.
        out["error"] = str(exc)[:200]
        log.warning("measurement failed for %s/%s: %s", ticker, rep["tool"], exc)
    return out


def _driver_block(driver: dict) -> str:
    bits = [f"THE DRIVER: {driver.get('driver', '')}"]
    if driver.get("segment"):
        bits.append(f"  segment: {driver['segment']}")
    if driver.get("priced_in_pct") is not None:
        bits.append(f"  judged already priced in: {driver['priced_in_pct']:.0f}% "
                    f"(an unvalidated estimate — do not revise it)")
    if driver.get("value_if_true_pct") is not None:
        bits.append(f"  worth if it proves out: {driver['value_if_true_pct']:+.0f}% "
                    f"of the price, bounded by the published model spread")
    if driver.get("basis"):
        bits.append(f"  the basis given for that share: {driver['basis']}")
    bits.append(f"  observable named: {driver.get('observable') or '(none)'}")
    return "\n".join(bits)


def _narrative_block(nar: dict) -> str:
    if not nar.get("n_claims_scanned"):
        return "SCORED COVERAGE ON THIS DRIVER:\n  none — no scored claims for this ticker"
    lines = [f"SCORED COVERAGE ON THIS DRIVER "
             f"({nar['n_related']} of {nar['n_claims_scanned']} claims in "
             f"circulation bear on it; mean signed impact "
             f"{nar['net_impact']:+.2f}, {nar['positive']} positive / "
             f"{nar['negative']} negative):"]
    for c in nar.get("top", []):
        lines.append(f"  [{c['impact']:+.2f}] {c['published']}  {c['text'][:220]}")
    if nar.get("note"):
        lines.append(f"  NOTE: {nar['note']}")
    return "\n".join(lines)


def _measurement_block(m: dict) -> str:
    if m.get("result") is not None:
        import json as _json
        return (f"NON-NEWS MEASUREMENT ({m.get('tool')}):\n"
                f"  {_json.dumps(m['result'], default=str)[:1800]}")
    why = m.get("error") or m.get("note") or "no observable named"
    return ("NON-NEWS MEASUREMENT: NONE AVAILABLE.\n"
            f"  {why}\n"
            "  Do not substitute a figure from the news for this. Say it cannot "
            "be measured with what is wired.")


def build(driver: dict, index: int, space, business, implied_brief: str, vote,
          claims: list, k: int = 12, model: str | None = None,
          effort: str = "medium", entity: str = "") -> Case:
    """Investigate one driver: the coverage on it, and the data outside it."""
    from .llm import available as _llm_available, complete_json

    text = str(driver.get("driver") or "").strip()
    c = Case(ticker=business.ticker, driver_index=index, driver=text,
             segment=str(driver.get("segment") or ""),
             priced_in_pct=driver.get("priced_in_pct"),
             value_if_true_pct=driver.get("value_if_true_pct"),
             observable=str(driver.get("observable") or ""),
             testable=bool(driver.get("testable")))

    # Both evidence halves are deterministic and run whether or not a model is
    # available: a case with no reading is still a case with a measured coverage
    # read and a series attached, which is more than the old path produced on a
    # model failure.
    c.narrative = narrative_read(space, text, claims)
    c.measurement = measure(business.ticker, driver, entity=entity)

    ok, why = _llm_available()
    if not ok:
        c.confidence = "not_explicable"
        c.what_coverage_says = f"no LLM available: {why}"
        return c

    # own_only: evidence about THIS company's driver must not be carried by a
    # peer's strategy article.
    passages = space.retrieve(text, k=k, own_only=True)
    c.n_passages = len(passages)
    c.retrieval = space.retrieval_discrimination(k, own_only=True)
    slugs = getattr(space, "slug_by_title", {})
    seen_titles = sorted({t for t, _ in passages if t})[:8]
    c.sources = [{"title": t, "slug": slugs.get(t)} for t in seen_titles]
    # Numbered exactly as `body` below numbers them for the model, so a
    # citation it writes can be turned back into a link.
    c.passages = [{"n": i + 1, "title": t, "slug": slugs.get(t)}
                  for i, (t, _) in enumerate(passages)]

    # Labelled "Passage 4" rather than "[4]" so the header reads as the citation
    # the model is asked to write. Numbered exactly as `c.passages` above.
    body = "\n\n".join(f"Passage {i + 1} — {t}\n{x.strip()[:1200]}"
                       for i, (t, x) in enumerate(passages))
    user = (f"{business.brief()}\n\n{implied_brief}\n\n"
            f"WHERE THE PRICE SITS: {vote.n_targets} published models "
            f"${vote.low:,.0f}..${vote.high:,.0f}, median ${vote.median:,.0f}; "
            f"{vote.lean}\n\n"
            f"{_driver_block(driver)}\n\n"
            f"{_narrative_block(c.narrative)}\n\n"
            f"{_measurement_block(c.measurement)}\n\n"
            f"RETRIEVED COVERAGE ({len(passages)} passages):\n{body}")

    res = complete_json(SYSTEM, user, SCHEMA, max_tokens=8000, effort=effort,
                        model=model)
    c.model = res.model
    if not res.ok:
        log.warning("case failed for %s driver %d: %s", business.ticker, index,
                    res.error)
        c.confidence = "not_explicable"
        c.what_coverage_says = f"reading failed: {res.error}"
        return c

    d = res.data
    c.what_coverage_says = d.get("what_coverage_says", "")
    c.evidence_for = d.get("evidence_for", [])
    c.evidence_against = d.get("evidence_against", [])
    c.what_the_data_shows = d.get("what_the_data_shows", "")
    c.still_needed = d.get("still_needed", "")
    c.confidence = d.get("confidence", "")
    return c
