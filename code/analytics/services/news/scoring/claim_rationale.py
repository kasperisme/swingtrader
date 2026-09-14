"""
The rationale gate for STORY_KEY_POINTS.

Every claim on an article page carries a one-sentence rationale, and most of
them said nothing. Duluth, 2026-09-14, verbatim:

    claim     "Quarterly revenue decreased by 7.8% in Q2."
    rationale "Recent top-line decline indicates ongoing operational struggle."

That is the claim again with adjectives. A rationale earns its slot only by
adding something the claim does not already contain — at least one of:

    number       a figure absent from the claim  ("≈ all of Q2 net income")
    horizon      when it bites                   ("next quarter", "FY2027")
    consequence  one step down the chain         (margin, EPS, guidance, multiple…)

The prompt asks for exactly that; this module checks it, so a model that
ignores the instruction produces a bare claim rather than filler. A rule this
blunt will reject some decent sentences — that is the intended trade: an empty
slot costs nothing, a restatement costs the reader's trust in every other line.

Mirrored in code/ui/lib/news/article-verdict.ts (``rationaleAddsInformation``)
so rows scored before the gate existed are held to the same rule on render.
Change both together.
"""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")

_HORIZON_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:next|this|coming|following|current)\s+(?:trading\s+)?"
        r"(?:session|week|month|quarter|year|fiscal\s+year|print|report|earnings|guide)s?\b",
        r"\bQ[1-4]\b",
        r"\b[1-4]Q\b",
        r"\bFY\s?'?\d{2,4}\b",
        r"\bH[12]\b",
        r"\b(?:19|20)\d{2}\b",
        r"\b\d+\s*(?:-|to)?\s*\d*\s*(?:trading\s+)?"
        r"(?:day|week|month|quarter|year|session)s?\b",
        r"\bwithin\s+(?:a|an|one|two|three|four|six|twelve)\s+"
        r"(?:day|week|month|quarter|year|session)s?\b",
        r"\b(?:year[- ]end|holiday\s+quarter|back[- ]to[- ]school|next\s+earnings)\b",
    )
)

# Concrete things a claim leads to. A rationale that names one the claim does
# not has taken a step down the chain; "weakness", "pressure" and "concerns"
# are deliberately absent — they are the vocabulary of restatement.
_CONSEQUENCE_TERMS: tuple[str, ...] = (
    "margin", "eps", "earnings per share", "guidance", "guide", "estimate",
    "consensus", "multiple", "p/e", "valuation", "re-rat", "rerat", "dividend",
    "buyback", "repurchase", "dilution", "dilutive", "share count", "cash burn",
    "runway", "covenant", "refinanc", "credit rating", "free cash flow", "fcf",
    "net debt", "leverage", "write-down", "writedown", "impairment", "layoff",
    "price target", "short interest", "squeeze", "delist", "bankrupt",
    "comps", "market share", "pricing power", "capex", "backlog",
    "order book", "default", "downgrade", "upgrade", "cost of capital",
    "customer acquisition",
)

_WORD_RE = re.compile(r"[a-z][a-z'-]+")
_STOP = frozenset(
    "the a an and or of to in on for with by at from as is are was were be been "
    "this that these those it its their which who into over under than more less "
    "has have had will would could may might can not no but so".split()
)


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMBER_RE.finditer(text)}


def _horizons(text: str) -> set[str]:
    out: set[str] = set()
    for rx in _HORIZON_RES:
        out.update(m.group(0).lower() for m in rx.finditer(text))
    return out


def _consequences(text: str) -> set[str]:
    lowered = text.lower()
    return {t for t in _CONSEQUENCE_TERMS if t in lowered}


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


def rationale_adds_information(point: str, rationale: str) -> bool:
    """True when ``rationale`` carries a number, horizon or consequence that
    ``point`` does not, and is not a near-verbatim paraphrase of it."""
    point = (point or "").strip()
    rationale = (rationale or "").strip()
    if not rationale:
        return False

    rw = _content_words(rationale)
    pw = _content_words(point)
    if rw and len(rw & pw) / len(rw) >= 0.7:
        return False

    return bool(
        (_numbers(rationale) - _numbers(point))
        or (_horizons(rationale) - _horizons(point))
        or (_consequences(rationale) - _consequences(point))
    )


_NOVELTY_ALIASES: dict[str, str] = {
    "new": "new",
    "fresh": "new",
    "novel": "new",
    "priced_in": "priced_in",
    "priced in": "priced_in",
    "priced-in": "priced_in",
    "pricedin": "priced_in",
    "known": "priced_in",
    "old": "priced_in",
    "stale": "priced_in",
}


def normalize_novelty(raw: object) -> str | None:
    """Map the model's novelty label onto ``new`` / ``priced_in``; None if unusable."""
    if not isinstance(raw, str):
        return None
    return _NOVELTY_ALIASES.get(raw.strip().lower())
