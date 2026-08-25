"""Does `priced_in_pct` mean anything? — the test that actually bears on it.

Tier 1 asked whether the vote quantities predict returns. They do not, and that
was never the claim. The claim is descriptive: **this driver is 25% priced in,
that one is 90%.** A description does not have to forecast to be useful, it has
to be accurate — so the test has to be of accuracy, not of prediction.

There is a falsifiable consequence, and it is the reason this module exists:

    If a driver is FULLY priced, news that resolves it should move the stock
    very little — the market already knew. If a driver is UNPRICED, news that
    resolves it should move the stock a lot.

So `priced_in_pct` should be **inversely related to the size of the price
reaction** when the driver's news arrives. That is measurable with article
timestamps and prices, and — importantly — with **no language model in the
outcome measurement.** The model proposes the decomposition; arithmetic scores it.

**The control is the whole test.** Company news clusters around earnings, when
the stock moves a lot regardless of subject, so raw reaction size mostly
measures "was this near a print". Every driver's reaction is therefore
normalised by the SAME ticker's average reaction across ALL its forward
articles. What is being tested is whether driver-matched days move MORE than
that ticker's ordinary news day, not whether they move at all.

**Known weakness, stated up front.** Matching articles to drivers is done by
embedding similarity, and `saturation.retrieval_discrimination` already showed
that is not selective on a thin corpus — 23 articles cannot be partitioned into
eight drivers. Expect the matching to be noisy, and read `selective` before
reading anything else.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import numpy as np

from ..config import CACHE_ROOT
from ..data.news import _connect
from ..data.prices import PriceStore
from .saturation import _unit, embed

log = logging.getLogger(__name__)

# Fetches are expensive and parameter-invariant; selection is neither.
_FETCH_CACHE: dict = {}

SCHEMA_NS = "swingtrader"
BENCHMARK = "SPY"


@dataclass
class Event:
    driver: str
    article_id: int
    title: str
    published: str
    similarity: float
    car: float | None = None          # market-adjusted, [0, +2] sessions


@dataclass
class DriverReaction:
    driver: str
    priced_in_pct: float
    n_events: int
    mean_abs_car: float | None
    relative_to_baseline: float | None    # vs this ticker's average article day
    events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["events"] = [asdict(e) for e in self.events]
        return d


def _load_prices(ticker: str):
    """Prices from whichever cache has the name, freshest first.

    `prices_live` holds the 900 most liquid names through today; the deep cache
    holds everything back to 1995 but stops at the vault boundary. Crocs is in
    the second and not the first, and the first version of this silently
    returned None for it — which surfaced as `baseline |CAR| = None` rather than
    as a missing-data error, i.e. an empty test that looked like a finished one.
    """
    for d in (CACHE_ROOT / "prices_live", None):
        store = PriceStore(cache_dir=d) if d else PriceStore()
        df = store.load(ticker)
        if df is not None and len(df):
            return df
    return None


def car(ticker: str, when: date, days: int = 2, store=None) -> float | None:
    """Market-adjusted return over [publication, +days], filled at the next open.

    Adjusted rather than raw because a company-news day is also a market day,
    and an unadjusted reaction on a +2% tape is mostly the tape.
    """
    a, b = _load_prices(ticker), _load_prices(BENCHMARK)
    if a is None or b is None:
        return None
    import pandas as pd
    ts = pd.Timestamp(when)

    def leg(df):
        after = df[df["date"] > ts]
        if len(after) < days + 1:
            return None
        o = float(after.iloc[0]["open"])
        c = float(after.iloc[min(days, len(after) - 1)]["close"])
        return (c / o - 1.0) if o > 0 else None

    ra, rb = leg(a), leg(b)
    if ra is None or rb is None:
        return None
    return ra - rb


# Syndicated templates that mention a ticker in a list without being about it.
# These are the reason the first version of this test measured nothing: they are
# generic valuation prose, so they sit close to ANY margin or multiple driver in
# embedding space, and they carry every ticker they name. Nike's "gross margin
# mean-reversion" driver matched Progress Software, Cava Group and American
# Express — and the price reaction was then computed on those articles' dates.
_TEMPLATE = re.compile(
    r"(surpasses market returns|some facts worth knowing|some information for "
    r"investors|is .{2,40} stock undervalued|dipped more than|declines more than|"
    r"lags the market|outpaces the market|what the options market tells us|"
    r"here's why .{2,40} (fell|rose|is a)|stock (declines|advances) while|"
    r"trading (up|down) .{1,12}% )", re.I)


def forward_articles(ticker: str, since: date, until: date,
                     names: list[str] | None = None,
                     max_articles: int = 3000) -> list[tuple]:
    """(article_id, title, published, chunk_text, embedding) after `since`.

    Deliberately re-queried rather than reusing a NarrativeSpace: that space is
    built on a LOOKBACK window ending at as_of, and the events we need are the
    ones that came AFTER it.
    """
    # Two steps, and a cache.
    #
    # One query with the tag OR-filter joined against the 1.8M-row embeddings
    # table times out — the same shape that broke the narrative space earlier.
    # Resolve ids against `news_articles` (218k rows, indexed on both paths),
    # then fetch chunks by id. The result is cached because a parameter sweep
    # re-runs selection seven times over identical data, and the fetch is the
    # only expensive part.
    key = (ticker, since.isoformat(), until.isoformat(), max_articles)
    if key in _FETCH_CACHE:
        rows = _FETCH_CACHE[key]
    else:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.id FROM {SCHEMA_NS}.news_articles a
                WHERE a.published_at > %s AND a.published_at <= %s
                  AND (a.search_tags && %s
                       OR EXISTS (SELECT 1 FROM {SCHEMA_NS}.news_article_tickers n
                                  WHERE n.article_id = a.id AND n.ticker = %s))
                ORDER BY a.published_at
                LIMIT %s
            """, (since.isoformat(), until.isoformat(), [ticker], ticker, 800))
            ids = [r[0] for r in cur.fetchall()]
            rows = []
            if ids:
                cur.execute(f"""
                    SELECT a.id, a.title, a.published_at::date, e.chunk_text,
                           e.embedding::text
                    FROM {SCHEMA_NS}.news_article_embeddings e
                    JOIN {SCHEMA_NS}.news_articles a ON a.id = e.article_id
                    WHERE e.article_id = ANY(%s)
                    ORDER BY a.published_at
                    LIMIT %s
                """, (ids, max_articles))
                rows = cur.fetchall()
        _FETCH_CACHE[key] = rows

    # Keep only articles that are ABOUT this company: the name (or a brand) in
    # the TITLE, and not a syndicated template. Tag membership alone is the
    # same many-to-many trap as everywhere else in this pipeline — an article
    # that merely mentions the ticker is not evidence about its drivers.
    if not names:
        return rows
    low = [n.lower() for n in names if n and len(n) > 2]
    kept = [r for r in rows
            if (r[1] or "") and not _TEMPLATE.search(r[1])
            and any(n in (r[1] or "").lower() for n in low)]
    return kept if len({r[0] for r in kept}) >= 12 else [
        r for r in rows if (r[1] or "") and not _TEMPLATE.search(r[1])]


def run(ticker: str, as_of: date, drivers: list[dict], horizon_days: int = 365,
        n_events: int = 8, floor_pct: float = 75.0, car_days: int = 2,
        names: list[str] | None = None, top_pct: float | None = None,
        max_events: int | None = None) -> dict:
    """Score a decomposition's drivers against what actually moved the stock.

    `car_days` is a real parameter now. It was hard-coded at 2 while a sweep
    appeared to vary it, so the event-window sensitivity check returned three
    identical rows and looked like robustness.
    """
    until = min(date.today(), as_of + timedelta(days=horizon_days))
    rows = forward_articles(ticker, as_of, until, names=names)
    if not rows:
        return {"error": f"no forward articles for {ticker} after {as_of}"}
    if _load_prices(ticker) is None:
        return {"error": f"no price history cached for {ticker} in either store"}

    # Aggregate chunks to ARTICLES before ranking.
    #
    # The row limit is on chunk rows, and a mega-cap's articles are long: 400
    # rows of Apple coverage is about 27 distinct articles. Every driver's
    # top-decile then selected the same handful, so each driver's mean |CAR|
    # equalled the baseline exactly — AAPL, AMZN and TSLA returned a reaction of
    # 1.000x for every single driver, 20 of 81 observations carrying no
    # information at all while still counting toward n. An article's similarity
    # to a driver is the MAX over its chunks; one strongly-matching passage is
    # what makes the article about that driver.
    import json as _json
    from collections import defaultdict
    by_article: dict[int, dict] = {}
    chunk_vecs = defaultdict(list)
    for r in rows:
        by_article.setdefault(r[0], {"title": r[1], "published": r[2]})
        chunk_vecs[r[0]].append(_unit(_json.loads(r[4])))
    art_ids = list(by_article)
    if not art_ids:
        return {"error": f"no usable forward articles for {ticker}"}
    mats = {a: np.vstack(v) for a, v in chunk_vecs.items()}
    # Baseline: this ticker's average |CAR| across ALL its forward article days.
    # Without it, a driver matched to earnings-week articles looks important
    # when it has only been matched to volatile days.
    seen, base, car_by_article = set(), [], {}
    for a in art_ids:
        seen.add(a)
        c = car(ticker, by_article[a]["published"], days=car_days)
        car_by_article[a] = c
        if c is not None:
            base.append(abs(c))
    baseline = float(np.mean(base)) if base else None

    # Selection rule, settled.
    #
    # A per-driver percentile plus a cap was two knobs doing one job, and the
    # cap always won: top_pct 80 and 88 gave identical answers because
    # max_events bound first, so the "relative selection" was inert. Worse, the
    # pooled correlation swung from -0.046 to -0.174 across reasonable settings
    # of a knob nobody had a reason to prefer.
    #
    # Now: every driver gets the SAME number of events (so reactions are
    # comparable across drivers), chosen by rank, above a floor set from the
    # TICKER'S whole driver x article similarity matrix. The floor adapts to the
    # corpus — which is what the per-driver percentile was trying and failing to
    # do — and it prevents forcing N matches onto a driver nothing resembles.
    if top_pct is not None or max_events is not None:
        log.warning("top_pct/max_events are deprecated; use floor_pct/n_events")
        n_events = max_events or n_events

    usable = [d for d in drivers if f"{d.get('driver','')}{d.get('basis','')}".strip()]
    driver_sims: list = []
    for d in usable:
        text = f"{d.get('driver','')} {d.get('basis','')}"
        q = _unit(embed(text))
        sims = np.array([float((mats[a] @ q).max()) for a in art_ids])
        driver_sims.append(sims)
    if not driver_sims:
        return {"error": "no usable drivers"}
    floor = float(np.percentile(np.concatenate(driver_sims), floor_pct))

    out = []
    for d, sims in zip(usable, driver_sims):
        order = np.argsort(-sims)
        evs, used = [], set()
        for i in order:
            if sims[i] < floor or len(evs) >= n_events:
                break
            aid = art_ids[i]
            if aid in used:
                continue
            used.add(aid)
            meta = by_article[aid]
            evs.append(Event(driver=d.get("driver", ""), article_id=int(aid),
                             title=meta["title"] or "",
                             published=str(meta["published"]),
                             similarity=float(sims[i]),
                             car=car_by_article.get(aid)))
        cars = [abs(e.car) for e in evs if e.car is not None]
        m = float(np.mean(cars)) if cars else None
        out.append(DriverReaction(
            driver=d.get("driver", ""),
            priced_in_pct=float(d.get("priced_in_pct") or 0),
            n_events=len(evs), mean_abs_car=m,
            relative_to_baseline=((m / baseline) if (m and baseline) else None),
            events=evs))

    scored = [r for r in out if r.relative_to_baseline is not None]
    corr = t = float("nan")
    if len(scored) >= 4:
        x = np.array([r.priced_in_pct for r in scored], dtype=float)
        y = np.array([r.relative_to_baseline for r in scored], dtype=float)
        if x.std() > 1e-9 and y.std() > 1e-9:
            corr = float(np.corrcoef(x, y)[0, 1])
            n = len(scored)
            t = float(corr * np.sqrt((n - 2) / max(1e-9, 1 - corr ** 2)))
    return {"ticker": ticker, "as_of": as_of.isoformat(), "until": until.isoformat(),
            "n_forward_articles": len(art_ids), "baseline_abs_car": baseline,
            "drivers": [r.to_dict() for r in out],
            "corr_priced_in_vs_reaction": corr, "t_stat": t,
            "n_scored_drivers": len(scored),
            "hypothesis": ("priced_in_pct should be NEGATIVELY correlated with the "
                           "relative reaction: what the market already knows should "
                           "not move it."),
            "selection": f"top {n_events} by rank, above the {floor_pct:.0f}th "
                         f"percentile of this ticker's whole driver x article "
                         f"similarity matrix (floor {floor:.3f})",
            "car_days": car_days,
            "caveat": ("Driver-to-article matching is embedding similarity, which "
                       "is not selective on a thin corpus. Few drivers and few "
                       "events per driver mean this is a direction check, not a "
                       "significance test.")}
