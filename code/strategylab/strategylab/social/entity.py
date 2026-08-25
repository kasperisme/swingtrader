"""ticker -> the consumer-facing entities whose attention we can measure.

This module is the one Camillo actually monetised. TickerTags' product was not
a counter, it was a curated dictionary of word-combinations mapped to tickers,
and the counting was the easy half. Everything hard about this thesis is here.

**Why a naive Wikidata pull is not enough.** Asking Wikidata for "things this
company produces" returns three kinds of junk in roughly equal measure to the
signal, and each kind fails differently:

* **Category pages.** Deckers and Skechers both resolve to `Shoe`. Pageviews for
  `Shoe` measure the world's interest in footwear, which is shared across every
  footwear name and therefore cannot separate them. Worse, it would look like a
  working signal in a panel regression because it correlates with sector returns.
* **Patents.** Deckers returns "Footwear including a stabilizing sole", four
  times. These have no Wikipedia article and no consumers.
* **Subsidiaries and teams.** On Holding returns "On Athletics Club", "OAC
  Europe". Organisations, not products.

And the pull *misses* the entities that matter: Deckers' whole thesis is HOKA and
UGG, neither of which came back. So Wikidata is used here as a **candidate
generator only**, filtered mechanically and then validated against the pageviews
API. Anything that survives is still a candidate, not a fact.

**The look-ahead trap, stated up front.** It is very easy to build this map by
thinking of consumer trends you remember — Crocs, Stanley, Labubu — and looking
up their tickers. That map would produce a beautiful backtest and would be
worthless, because the selection used the outcome. The universe must be chosen
by *sector and liquidity only*, and the brand resolution must be mechanical.
`build_universe()` enforces the first; the second is why the filters below are
rules rather than a hand-written list.

**Point-in-time.** A brand maps to whoever owned it at the time. Rhode was
acquired by e.l.f. in 2025; pageviews for Rhode before that date belong to no
listed company. Wikidata carries acquisition qualifiers inconsistently, so
`valid_from` is populated where available and left None otherwise, and any study
using this map must treat a None as "unknown, exclude from pre-acquisition
windows" rather than "always valid".
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import CACHE_ROOT

log = logging.getLogger(__name__)

SPARQL = "https://query.wikidata.org/sparql"
UA = "swingtrader-strategylab/0.1 (research; k.rasmussen92@gmail.com)"

# Entities whose pageviews measure a CATEGORY rather than a firm. Any of these
# as an exact label is dropped: they are shared across competitors, so they
# cannot carry firm-specific information but will happily correlate with sector
# returns and look like a signal.
GENERIC_LABELS = {
    "shoe", "shoes", "footwear", "sneaker", "sneakers", "sportswear", "clothing",
    "apparel", "cosmetics", "makeup", "skin care", "skincare", "energy drink",
    "energy drinks", "soft drink", "beverage", "beer", "wine", "spirits",
    "sports equipment", "toy", "toys", "furniture", "software", "video game",
    "video games", "smartphone", "computer", "laptop", "automobile", "car",
    "electric vehicle", "restaurant", "coffee", "tea", "food", "snack",
    "clothing accessories", "handbag", "jewellery", "jewelry", "watch",
    "perfume", "fragrance", "shampoo", "soap", "detergent", "pet food",
    # Second pass, from the first real run over 226 consumer names. Every one of
    # these came back attached to two or more competitors in the same universe.
    "supermarket", "home appliance", "fast food", "hotel", "resort", "motel",
    "franchising", "tobacco", "cigarette", "cigar", "electronic cigarette",
    "smokeless tobacco", "heated tobacco product", "list of tobacco products",
    "tex-mex", "directory assistance", "eyewear", "alcoholic beverage",
    "cash and carry", "self-driving car", "retail", "department store",
    "grocery store", "convenience store", "e-commerce", "online shopping",
    "shopping mall", "airline", "cruise ship", "casino", "theme park",
    "bottled water", "sparkling water", "chocolate", "candy", "ice cream",
    "breakfast cereal", "pizza", "hamburger", "sandwich", "salad",
    "mobile app", "operating system", "web browser", "search engine",
    "streaming television", "social media", "credit card", "payment card",
}

# Wikidata P31 (instance of) classes that indicate a real consumer entity.
BRANDLIKE_QIDS = {
    "Q431289": "brand",
    "Q167270": "trademark",
    "Q2727213": "product line",
    "Q2095": "food",
    "Q40050": "drink",
    "Q7397": "software",
    "Q7889": "video game",
    "Q1361832": "beverage brand",
    "Q3966": "hardware",
    "Q42889": "vehicle",
    "Q207694": "product model",
}

# Patent titles are long, sentence-shaped and start with a gerund/noun phrase.
_PATENTISH = re.compile(r"\b(comprising|including|apparatus|method for|assembly|"
                        r"having a|with a)\b", re.I)


@dataclass
class Entity:
    ticker: str
    qid: str
    label: str
    article: str                 # en.wikipedia article title (underscored)
    kind: str                    # "product" | "company"
    valid_from: str | None = None   # ISO date ownership begins, None = unknown
    source: str = "wikidata"

    def to_dict(self) -> dict:
        return asdict(self)


def _sparql(query: str, timeout: int = 90, retries: int = 6) -> list[dict]:
    """POST a query, respecting the service's throttle.

    The Wikidata Query Service is aggressive about 429s and sends a
    `Retry-After` telling you exactly how long to wait. Honouring it is both
    faster and politer than exponential backoff guessed from nothing — an
    ignored Retry-After escalates to a temporary IP ban. POST is used rather
    than a query string because these queries exceed the practical GET length
    once the VALUES clause holds a batch of tickers.
    """
    data = urllib.parse.urlencode({"query": query}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(SPARQL, data=data, headers={
            "User-Agent": UA, "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return json.load(fh)["results"]["bindings"]
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            wait = float(exc.headers.get("Retry-After") or 0) or min(60, 5 * 2 ** attempt)
            log.info("sparql %d — waiting %.0fs (attempt %d/%d)",
                     exc.code, wait, attempt + 1, retries)
            time.sleep(wait)
        except Exception as exc:                       # noqa: BLE001
            if attempt == retries - 1:
                raise
            log.debug("sparql retry %d: %s", attempt + 1, exc)
            time.sleep(min(60, 5 * 2 ** attempt))
    return []


def _title(url: str) -> str:
    return urllib.parse.unquote(url.rsplit("/", 1)[-1]) if url else ""


# Two steps, not one. The single combined query — exchange listing, a three-way
# UNION over products, and the label service — reliably exceeded the Wikidata
# Query Service's 60s server-side timeout and came back as a dropped connection
# with no error message. Resolving tickers to QIDs first and then binding the
# product query to those QIDs turns one 60s+ timeout into 0.5s + 5s, because the
# second query starts from ten known entities instead of scanning the listing
# graph. Measured, not guessed.
# Q82059 = Nasdaq, Q13677 = NYSE. The exchange constraint is NOT optional: P249
# is a qualifier on a listing statement, so matching the ticker alone returns
# every company holding those letters anywhere in the world. Without it "COST"
# resolves to Costain Group (LSE construction) as well as Costco, and "EL" to
# EssilorLuxottica rather than Estee Lauder — and the products of both then get
# merged under one ticker.
_QID_Q = """
SELECT ?ticker ?company ?companyLabel ?article WHERE {
  VALUES ?ticker { %s }
  VALUES ?exchange { wd:Q82059 wd:Q13677 }
  ?company p:P414 ?ex . ?ex ps:P414 ?exchange ; pq:P249 ?ticker .
  ?article schema:about ?company ; schema:isPartOf <https://en.wikipedia.org/> .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# P1056 = product or material produced; P176 = manufacturer (reverse).
_PRODUCT_Q = """
SELECT ?company ?product ?productLabel ?article WHERE {
  VALUES ?company { %s }
  { ?company wdt:P1056 ?product } UNION { ?product wdt:P176 ?company }
  ?article schema:about ?product ; schema:isPartOf <https://en.wikipedia.org/> .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""

# P127 = owned by, with the P580 (start time) qualifier that makes the map
# point-in-time. Kept as its own query because the qualifier path is the
# expensive one and it is worth failing separately rather than taking the
# cheap product query down with it.
_OWNED_Q = """
SELECT ?company ?product ?productLabel ?article ?since WHERE {
  VALUES ?company { %s }
  ?product p:P127 ?own . ?own ps:P127 ?company .
  OPTIONAL { ?own pq:P580 ?since }
  ?article schema:about ?product ; schema:isPartOf <https://en.wikipedia.org/> .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def _values(tickers: list[str]) -> str:
    return " ".join(f'"{t}"' for t in tickers)


def _keep(label: str) -> bool:
    """Mechanical filters. See the module docstring for what each one catches."""
    lab = label.strip().lower()
    if lab in GENERIC_LABELS:
        return False
    if _PATENTISH.search(label) or len(label) > 60:
        return False
    if label.startswith("Q") and label[1:].isdigit():
        return False
    return True


def fetch_candidates(tickers: list[str], chunk: int = 20) -> list[Entity]:
    """Wikidata candidates for a ticker list, mechanically filtered.

    Returns the company article (needed as L2's placebo — investor attention
    rather than consumer attention) plus any surviving product/brand articles.
    """
    out: list[Entity] = []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]

        qid_to_ticker: dict[str, str] = {}
        for r in _sparql(_QID_Q % _values(batch)):
            art = _title(r.get("article", {}).get("value", ""))
            qid = r["company"]["value"].rsplit("/", 1)[-1]
            if not art:
                continue
            qid_to_ticker[qid] = r["ticker"]["value"]
            out.append(Entity(ticker=r["ticker"]["value"], qid=qid,
                              label=r["companyLabel"]["value"], article=art,
                              kind="company"))
        if not qid_to_ticker:
            continue

        vals = " ".join(f"wd:{q}" for q in qid_to_ticker)
        seen: set[tuple[str, str]] = set()
        for query, has_since in ((_PRODUCT_Q, False), (_OWNED_Q, True)):
            try:
                rows = _sparql(query % vals)
            except Exception as exc:                        # noqa: BLE001
                log.warning("product query failed for a batch: %s", str(exc)[:100])
                continue
            for r in rows:
                label = r["productLabel"]["value"]
                art = _title(r.get("article", {}).get("value", ""))
                tk = qid_to_ticker.get(r["company"]["value"].rsplit("/", 1)[-1])
                if not art or not tk or (tk, art) in seen or not _keep(label):
                    continue
                seen.add((tk, art))
                since = r.get("since", {}).get("value") if has_since else None
                out.append(Entity(ticker=tk,
                                  qid=r["product"]["value"].rsplit("/", 1)[-1],
                                  label=label, article=art, kind="product",
                                  valid_from=since[:10] if since else None))
        log.info("wikidata %d/%d tickers -> %d candidates",
                 min(i + chunk, len(tickers)), len(tickers), len(out))
    return out


# ----------------------------------------------------------------------
class EntityStore:
    """Disk-cached entity map. One JSON per ticker, same shape as the other
    stores in this project so it can be inspected and hand-corrected."""

    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or (CACHE_ROOT / "entities"))
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, ticker: str) -> Path:
        return self.dir / f"{ticker.replace('/', '_').replace('.', '-')}.json"

    def save(self, ticker: str, ents: list[Entity]) -> None:
        self._path(ticker).write_text(json.dumps([e.to_dict() for e in ents], indent=1))

    def load(self, ticker: str) -> list[Entity]:
        p = self._path(ticker)
        if not p.exists():
            return []
        try:
            return [Entity(**d) for d in json.loads(p.read_text())]
        except Exception:                                   # noqa: BLE001
            return []

    def cached_tickers(self) -> list[str]:
        return sorted(p.stem.replace("-", ".") for p in self.dir.glob("*.json"))

    def ensure(self, tickers: list[str], force: bool = False,
               chunk: int = 10, pause: float = 2.0) -> dict:
        """Resolve and cache, saving after every chunk.

        Chunked-and-saved rather than fetch-everything-then-write because the
        Wikidata endpoint throttles and occasionally drops the connection
        outright. A run that loses two hundred resolved tickers to a
        `RemoteDisconnected` on the last batch is a run nobody will re-attempt,
        so progress is durable and a failed chunk is logged and skipped rather
        than raised.
        """
        todo = [t for t in tickers if force or not self._path(t).exists()]
        stats = {"requested": len(tickers), "fetched": 0, "failed_chunks": 0,
                 "skipped": len(tickers) - len(todo)}
        for i in range(0, len(todo), chunk):
            batch = todo[i:i + chunk]
            try:
                ents = fetch_candidates(batch, chunk=chunk)
            except Exception as exc:                        # noqa: BLE001
                stats["failed_chunks"] += 1
                log.warning("chunk %s failed, skipping: %s", batch[:3], str(exc)[:120])
                continue
            by_ticker: dict[str, list[Entity]] = {t: [] for t in batch}
            for e in ents:
                by_ticker.setdefault(e.ticker, []).append(e)
            for t, es in by_ticker.items():
                # An empty list is a real answer ("Wikidata knows no products
                # for this ticker") and is cached so the next run does not
                # re-query it. Only a failed CHUNK is left uncached.
                self.save(t, es)
                stats["fetched"] += 1
            log.info("entities %d/%d tickers cached", min(i + chunk, len(todo)), len(todo))
            time.sleep(pause)
        stats["with_product"] = sum(
            1 for t in tickers if any(e.kind == "product" for e in self.load(t)))
        stats["products"] = sum(
            1 for t in tickers for e in self.load(t) if e.kind == "product")
        return stats
