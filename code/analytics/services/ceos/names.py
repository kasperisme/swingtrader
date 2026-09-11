"""Turning FMP's CEO strings into a display name, a slug and a match key.

FMP decorates names inconsistently across its own endpoints: the profile says
"Mr. Jen-Hsun Huang", key-executives says "Jen-Hsun Huang", the proxy
compensation rows say "Jen-Hsun Huang President and CEO", and credentials ride
along as "Lisa T. Su Ph.D." or "John Smith, CPA". Everything here exists to
see those as one person without ever inventing a name FMP did not give us —
"Timothy D. Cook" stays "Timothy D. Cook"; nothing guesses "Tim Cook".
"""

from __future__ import annotations

import re
import unicodedata

HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "dame", "rev", "hon", "lord"}

# Post-nominal credentials: dropped from the display name. Generational
# suffixes (Jr., III) are NOT here — they tell two people apart.
CREDENTIALS = {
    "phd", "md", "jd", "mba", "cpa", "cfa", "esq", "pe", "cma", "dds", "dvm",
    "facs", "frcs", "facc", "rph", "pharmd", "msc", "bsc", "ma", "ms", "llb",
    "llm", "cbe", "obe", "mbe", "kbe", "ao", "ac", "cpa/abv", "cgma", "ca",
}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm_token(tok: str) -> str:
    return re.sub(r"[^a-z/]", "", fold(tok))


def fold(s: str) -> str:
    """Lower-case ASCII: 'Ángel' -> 'angel'."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def clean_name(raw: str | None) -> str | None:
    """'Mr. Jen-Hsun Huang' -> 'Jen-Hsun Huang'; 'John Smith, CPA' -> 'John Smith'.

    Returns None for strings that are not a name at all (FMP occasionally
    carries 'N/A' or a bare title).
    """
    if not raw:
        return None
    s = " ".join(str(raw).split())
    if not s or fold(s) in {"n/a", "na", "none", "null", "-"}:
        return None

    parts = [p.strip() for p in s.split(",") if p.strip()]
    head, rest = parts[0], parts[1:]
    tail = [p for p in rest if _norm_token(p) in SUFFIXES]

    tokens = head.split()
    while tokens and _norm_token(tokens[0]) in HONORIFICS:
        tokens.pop(0)
    while len(tokens) > 1 and _norm_token(tokens[-1]) in CREDENTIALS:
        tokens.pop()
    if not tokens:
        return None
    return " ".join(tokens + tail)


def slugify(name: str) -> str:
    s = fold(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


def name_tokens(name: str) -> list[str]:
    """Folded word tokens with suffixes removed: 'Robert A. Iger Jr.' -> ['robert','a','iger']."""
    toks = [t for t in re.split(r"[^a-z0-9]+", fold(name)) if t]
    return [t for t in toks if t not in SUFFIXES]


def surname(name: str) -> str | None:
    toks = name_tokens(name)
    return toks[-1] if toks else None


def given(name: str) -> str | None:
    toks = [t for t in name_tokens(name) if len(t) > 1]
    return toks[0] if len(toks) > 1 else None


def same_person(a: str, b: str) -> bool:
    """Loose match between two renderings of a name from FMP.

    Same surname and a compatible given name: equal, or one a prefix of the
    other ('Tim' / 'Timothy'), or either side missing a given name. Surname
    alone is not enough — family companies put two Dells or two Murdochs in
    the same filing.
    """
    sa, sb = surname(a), surname(b)
    if not sa or sa != sb:
        return False
    ga, gb = given(a), given(b)
    if not ga or not gb:
        return True
    return ga.startswith(gb[:3]) or gb.startswith(ga[:3])


_CEO_TITLE = re.compile(r"\b(ceo|chief executive)\b", re.I)


def is_ceo_title(title: str | None) -> bool:
    return bool(title and _CEO_TITLE.search(title))
