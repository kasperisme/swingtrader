"""The sell-side's ARGUMENT, not its number.

A published price target is inert. It is disseminated the moment it exists, so
by our governing assumption it is already in the price, and using the consensus
figure as an anchor was a mistake — it smuggles a third party's forecast into a
reconstruction that is supposed to be derived from the price.

What is not inert is the **reasoning**: which assumptions a target rests on,
where analysts disagree, and what they keep asking management about. That is the
structure of the consensus belief, and a counterfactual has to contradict a
structure, not a number.

Two sources give it, and both are properly dated — unlike the consensus
estimates, whose historical rows turned out to be converged actuals:

* **Per-analyst targets** (`publishedDate`, `priceWhenPosted`). The dispersion is
  the point. On one day in July 2026 Crocs carried Goldman at $95 with a SELL,
  UBS at $120 NEUTRAL, and Baird at $163. The "consensus $136.78" is a number
  nobody holds; there are two incompatible views of the same company, and the
  axis they disagree on is the thing worth finding.
* **Earnings-call Q&A.** Analyst questions are the sell-side stating, in public,
  what its models turn on. When six analysts in a row ask about one segment,
  that segment is the consensus's load-bearing assumption. This is the closest
  thing to reading their notes that is actually obtainable.

Neither is used as an anchor for the arithmetic. Both are used to say what the
prevailing argument IS, which is what `priced_in()` should be describing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np

from ..data import fmp

log = logging.getLogger(__name__)

_V3 = "https://financialmodelingprep.com/api/v3"
_V4 = "https://financialmodelingprep.com/api/v4"


@dataclass
class Target:
    published: str
    company: str
    analyst: str
    target: float
    price_when_posted: float | None
    headline: str
    url: str

    @property
    def implied_upside(self) -> float | None:
        if self.price_when_posted:
            return self.target / self.price_when_posted - 1.0
        return None


@dataclass
class Question:
    analyst: str
    text: str
    answered_by: str = ""
    answer: str = ""


@dataclass
class AnalystView:
    ticker: str
    as_of: str
    targets: list = field(default_factory=list)
    target_low: float | None = None
    target_high: float | None = None
    target_median: float | None = None
    dispersion: float | None = None          # (high-low) / median
    bulls: list = field(default_factory=list)
    bears: list = field(default_factory=list)
    call_date: str = ""
    questions: list = field(default_factory=list)
    topics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self, max_q: int = 8) -> str:
        out = [f"THE SELL-SIDE ARGUMENT — {self.ticker} (as of {self.as_of})"]
        if self.targets:
            out.append(f"  {len(self.targets)} targets in the window: "
                       f"${self.target_low:,.0f} .. ${self.target_high:,.0f} "
                       f"(median ${self.target_median:,.0f}, "
                       f"dispersion {self.dispersion:.0%} of median)")
            if self.bulls and self.bears:
                b = self.bulls[0]
                r = self.bears[0]
                out.append(f"  the disagreement is real, not a range: "
                           f"{r.company} ${r.target:,.0f} vs {b.company} "
                           f"${b.target:,.0f} — a {b.target/r.target:.1f}x spread on "
                           f"the same company")
            out.append("  the number is priced in the day it prints; the SPREAD is "
                       "what says where the argument is.")
        if self.questions:
            out.append(f"\n  What the sell-side asked management on {self.call_date} "
                       f"({len(self.questions)} questions — this is what their models "
                       f"turn on):")
            for q in self.questions[:max_q]:
                out.append(f"    - [{q.analyst}] {q.text[:190]}")
        if self.topics:
            top = sorted(self.topics.items(), key=lambda kv: -kv[1])[:8]
            out.append("  recurring themes in the questions: "
                       + ", ".join(f"{k} x{v}" for k, v in top))
        return "\n".join(out)


# ----------------------------------------------------------------------
def targets(ticker: str, as_of: date | None = None, window_days: int = 120) -> list[Target]:
    """Per-analyst targets published on or before `as_of`.

    Point-in-time by `publishedDate`, which these rows carry — the reason this
    source is usable historically where the consensus-estimate rows are not.
    """
    try:
        rows = fmp._get(f"{_V4}/price-target", {"symbol": ticker}) or []
    except Exception as exc:                                  # noqa: BLE001
        log.debug("price targets unavailable for %s: %s", ticker, exc)
        return []
    cutoff = (as_of or date.today())
    out = []
    for r in rows:
        d = str(r.get("publishedDate", ""))[:10]
        if not d:
            continue
        try:
            pd_ = date.fromisoformat(d)
        except ValueError:
            continue
        if pd_ > cutoff or (cutoff - pd_).days > window_days:
            continue
        try:
            tgt = float(r.get("adjPriceTarget") or r.get("priceTarget") or 0)
        except (TypeError, ValueError):
            continue
        if tgt <= 0:
            continue
        try:
            pwp = float(r.get("priceWhenPosted") or 0) or None
        except (TypeError, ValueError):
            pwp = None
        out.append(Target(published=d, company=r.get("analystCompany") or "?",
                          analyst=r.get("analystName") or "",
                          target=tgt, price_when_posted=pwp,
                          headline=r.get("newsTitle") or "",
                          url=r.get("newsURL") or ""))
    return sorted(out, key=lambda t: t.published, reverse=True)


# Speaker turns are "Name: text". Management is whoever gives prepared remarks;
# analysts are whoever the Operator hands to. That distinction is what makes the
# Q&A extractable — the operator introducing a speaker is the reliable marker.
_TURN = re.compile(r"(?m)^([A-Z][A-Za-z.'\-\s]{2,40}):\s*")


def parse_transcript(content: str) -> list[tuple[str, str]]:
    """[(speaker, text)] in order."""
    parts = _TURN.split(content or "")
    out = []
    for i in range(1, len(parts) - 1, 2):
        out.append((parts[i].strip(), parts[i + 1].strip()))
    return out


def analyst_questions(turns: list[tuple[str, str]]) -> list[Question]:
    """Questions asked by analysts, with the answer that followed.

    A speaker is treated as an analyst when the Operator introduced them — the
    operator's job on these calls is precisely to hand to the next questioner,
    which makes it a more reliable marker than any name list. Management is
    everyone else, and the reply is the next non-operator turn.
    """
    out = []
    for i, (spk, text) in enumerate(turns):
        if spk.lower() != "operator":
            continue
        if i + 1 >= len(turns):
            break
        asker, question = turns[i + 1]
        if asker.lower() == "operator" or len(question) < 40:
            continue
        # Must actually ask something. The investor-relations host opens the
        # call immediately after the operator and was being captured as the
        # first "question" — "thank you for joining us to discuss Q2 results,
        # with me today are..." is housekeeping, not a model input. Requiring a
        # question mark separates the Q&A from the preamble without needing to
        # know who the IR contact is.
        if "?" not in question:
            continue
        answer_by, answer = "", ""
        if i + 2 < len(turns) and turns[i + 2][0].lower() != "operator":
            answer_by, answer = turns[i + 2]
        out.append(Question(analyst=asker, text=question,
                            answered_by=answer_by, answer=answer))
    return out


def latest_transcript(ticker: str, as_of: date | None = None) -> tuple[str, str]:
    """(date, content) of the most recent call held on or before `as_of`."""
    try:
        idx = fmp._get(f"{_V4}/earning_call_transcript", {"symbol": ticker}) or []
    except Exception as exc:                                  # noqa: BLE001
        log.debug("transcript index unavailable for %s: %s", ticker, exc)
        return "", ""
    cutoff = (as_of or date.today()).isoformat()
    best = None
    for row in idx:
        try:
            q, y, when = int(row[0]), int(row[1]), str(row[2])
        except (TypeError, ValueError, IndexError):
            continue
        if when[:10] <= cutoff and (best is None or when > best[2]):
            best = (q, y, when)
    if not best:
        return "", ""
    q, y, when = best
    try:
        d = fmp._get(f"{_V3}/earning_call_transcript/{ticker}",
                     {"quarter": q, "year": y}) or []
    except Exception:                                         # noqa: BLE001
        return "", ""
    return (when[:10], d[0].get("content", "") if d else "")


_THEMES = {
    "margin": ("margin", "gross margin", "operating margin"),
    "inventory": ("inventory", "destock", "channel inventory"),
    "pricing/promo": ("promotion", "discount", "price increase", "aur", "asp"),
    "tariffs": ("tariff", "duty", "sourcing"),
    "international": ("international", "china", "india", "europe", "emea", "asia"),
    "DTC vs wholesale": ("dtc", "direct-to-consumer", "wholesale", "door"),
    "new products": ("new product", "launch", "franchise", "silhouette", "innovation"),
    "marketing": ("marketing", "brand heat", "demand creation"),
    "capital returns": ("buyback", "repurchase", "debt paydown", "leverage"),
    "guidance": ("guidance", "outlook", "second half", "full year"),
}


def question_themes(questions: list[Question]) -> dict:
    """Count recurring themes. Six questions about one segment is the consensus
    telling you where its model is load-bearing."""
    counts: dict[str, int] = {}
    for q in questions:
        low = q.text.lower()
        for theme, words in _THEMES.items():
            if any(w in low for w in words):
                counts[theme] = counts.get(theme, 0) + 1
    return counts


def build(ticker: str, as_of: date | None = None) -> AnalystView:
    tg = targets(ticker, as_of)
    lo = hi = med = disp = None
    bulls = bears = []
    if tg:
        vals = np.array([t.target for t in tg], dtype=float)
        lo, hi, med = float(vals.min()), float(vals.max()), float(np.median(vals))
        disp = (hi - lo) / med if med else None
        ordered = sorted(tg, key=lambda t: -t.target)
        bulls, bears = ordered[:3], ordered[-3:][::-1]
    when, content = latest_transcript(ticker, as_of)
    qs = analyst_questions(parse_transcript(content)) if content else []
    return AnalystView(ticker=ticker, as_of=(as_of or date.today()).isoformat(),
                       targets=tg, target_low=lo, target_high=hi, target_median=med,
                       dispersion=disp, bulls=bulls, bears=bears,
                       call_date=when, questions=qs, topics=question_themes(qs))
