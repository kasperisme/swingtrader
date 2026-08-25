"""The common narrative — the null hypothesis a thesis has to be different from.

Alpha in social arbitrage is not "a good story about a company". It is the
*delta* between what the market is already saying and what the data supports.
That makes the market's story the null, and it has to be extracted before any
thesis is generated, not compared against afterwards by eye.

Three things make this computable rather than impressionistic, and all three
already exist in the swingtrader news pipeline:

* **`news_impact_heads` / `STORY_KEY_POINTS`** — every scored article carries a
  handful of extracted claims with a signed impact each. That is the narrative
  already decomposed into propositions; no re-derivation needed.
* **`GROWTH_PROFILE`** — one of six scored dimensions per article. It answers
  "what does the coverage currently believe about this company's growth?",
  which is exactly the axis a growth thesis has to differ from.
* **`news_article_embeddings`** — 1.8M chunks in pgvector, so "is anyone already
  saying this?" is a similarity query rather than a reading exercise.

**The network matters as much as the ticker.** A company's narrative is carried
substantially by coverage of its competitors, suppliers and customers: a claim
about tariff exposure in the footwear trade shapes what is priced into CROX
whether or not CROX is named in the article. `network()` therefore assembles
three kinds of neighbour and keeps them labelled, because "my competitor is
struggling" and "my supplier is struggling" have opposite signs.

**What this measure cannot claim.** The corpus is a sample of the financial
press. A thesis absent from it may be thoroughly discussed on sell-side desks
and Bloomberg terminals. Narrative saturation measured here is a lower bound on
how well known something is, so a LOW score is weak evidence of a gap while a
HIGH score is strong evidence of saturation. The asymmetry is real and the
scoring must not pretend otherwise.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from ..data.news import _connect

log = logging.getLogger(__name__)

SCHEMA = "swingtrader"

# Structural tags that describe an article TYPE rather than a claim about the
# business. They dominate raw counts and make a dead narrative look busy — the
# same exclusion the trend-radar skill applies for the same reason.
PROCESS_TAGS = {
    "earnings", "guidance", "transcript", "lawsuit", "class_action",
    "securities_fraud", "securities_litigation", "investor_rights",
    "equity_research", "ratings", "valuation", "dividends", "ipo",
}


@dataclass
class Claim:
    """One proposition in circulation, with how loudly it is being said."""
    text: str
    impact: float                 # signed, [-1, +1], from the scorer
    article_id: int
    ticker: str                   # the ticker the article was linked to
    published: date
    weight: float = 1.0           # recency x |impact|, set by `narrative()`

    def __str__(self) -> str:
        return f"[{self.impact:+.2f}] {self.text[:150]}"


@dataclass
class Narrative:
    """What the market is currently saying about a company. The null."""
    ticker: str
    lookback_days: int
    claims: list[Claim] = field(default_factory=list)
    growth_profile: float | None = None      # mean over the sub-dimensions
    growth_dims: dict = field(default_factory=dict)   # the five, kept apart
    growth_n: int = 0
    article_count: int = 0
    network: dict[str, list[str]] = field(default_factory=dict)
    coverage_note: str = ""

    def top(self, n: int = 20) -> list[Claim]:
        return sorted(self.claims, key=lambda c: -c.weight)[:n]

    def corpus(self, n: int = 60) -> list[str]:
        """The claim texts a candidate thesis is differenced against."""
        return [c.text for c in self.top(n)]

    def summary(self) -> dict:
        pos = [c for c in self.claims if c.impact > 0.15]
        neg = [c for c in self.claims if c.impact < -0.15]
        return {"ticker": self.ticker, "articles": self.article_count,
                "claims": len(self.claims), "positive": len(pos), "negative": len(neg),
                "net_tone": float(np.mean([c.impact for c in self.claims]))
                if self.claims else None,
                "growth_profile": self.growth_profile, "growth_dims": self.growth_dims,
                "growth_n": self.growth_n,
                "network_size": sum(len(v) for v in self.network.values())}


# ----------------------------------------------------------------------
# The relationship graph's own vocabulary. Grouped by what each type means for
# a thesis rather than listed flat, because the groups are used differently:
# competitors set the frame a claim is judged against, the value chain carries
# corroboration or contradiction, and ownership names the BRANDS whose consumer
# attention the custom-data layer can actually measure.
REL_GROUPS = {
    "competitor": ("competitor",),
    "value_chain": ("supplier", "customer", "partner"),
    "owns": ("subsidiary", "acquirer"),
}


def network(ticker: str, lookback_days: int = 180, max_each: int = 8) -> dict:
    """The ticker's neighbourhood, from the LLM-extracted relationship graph.

    `swingtrader.ticker_relationship_edges` is the right source and the earlier
    version of this function ignored it, which was a mistake worth recording.
    Rolling a peer finder from raw news co-occurrence produced NVDA, AAPL and MU
    as Crocs' network — every mega-cap appears in every market wrap, so raw
    co-occurrence measures fame, not connection. Lift, a Poisson excess test and
    a share threshold each failed differently. The graph has none of those
    problems because it was built by reading what the articles actually assert:
    38k directional, typed, strength-weighted edges with per-edge evidence,
    canonicalised through `resolve_canonical_ticker`.

    Edges are read in BOTH directions — "NKE competes with CROX" and "CROX
    competes with NKE" are the same fact recorded from two articles — and ranked
    by `strength_avg * log1p(mention_count)` so a confidently-asserted edge seen
    once does not outrank a slightly weaker one seen thirty times.

    `owns` is the group that matters most for social arbitrage: it returns
    HEYDUDE for CROX. Brand names, not tickers, and brands are the entities the
    attention layer can actually measure.

    Industry membership is kept as a backbone because the graph is sparse for
    thinly-covered names — CROX has seven edges — and an empty network would
    silently narrow the narrative to the company's own press.
    """
    out: dict[str, list[str]] = {k: [] for k in REL_GROUPS}
    out["industry"] = []
    since = (date.today() - timedelta(days=max(lookback_days, 365))).isoformat()

    with _connect() as conn, conn.cursor() as cur:
        try:
            cur.execute(f"""
                SELECT CASE WHEN from_ticker = %s THEN to_ticker ELSE from_ticker END AS peer,
                       rel_type,
                       MAX(strength_avg) AS strength,
                       SUM(mention_count) AS mentions
                FROM {SCHEMA}.ticker_relationship_network_resolved_v
                WHERE (from_ticker = %s OR to_ticker = %s)
                  AND rel_type NOT IN ('n/a', 'none', 'other')
                  AND (last_seen_at IS NULL OR last_seen_at >= %s)
                GROUP BY 1, 2
                ORDER BY MAX(strength_avg) * ln(1 + SUM(mention_count)) DESC
            """, (ticker, ticker, ticker, since))
            rows = cur.fetchall()
        except Exception as exc:                             # noqa: BLE001
            log.warning("relationship graph unavailable (%s); industry only", exc)
            conn.rollback()
            rows = []

    for group, kinds in REL_GROUPS.items():
        seen: list[str] = []
        for peer, rel, _strength, _mentions in rows:
            if rel in kinds and peer and peer != ticker and peer not in seen:
                seen.append(peer)
            if len(seen) >= max_each:
                break
        out[group] = seen

    try:
        # `listing_metadata()` carries no market cap, so ranking on it degrades
        # to sorting tickers as strings — it returned WWW, WEYS, VRA as Nike's
        # peers. The raw listing rows have the cap.
        from ..data.universe import UniverseBuilder
        listed = {r["symbol"]: r for r in UniverseBuilder().listed()}
        mine = (listed.get(ticker) or {}).get("industry")
        if mine:
            peers = [(float(r.get("market_cap") or 0), sym)
                     for sym, r in listed.items()
                     if sym != ticker and r.get("industry") == mine]
            peers = [x for x in peers if x[0] > 0] or peers
            out["industry"] = [sym for _, sym in sorted(peers, reverse=True)[:max_each]]
    except Exception as exc:                                 # noqa: BLE001
        log.debug("listing rows unavailable: %s", exc)
    return out


def _claims(cur, tickers: list[str], since: str, limit: int,
            max_tickers: int = 4) -> list[Claim]:
    """STORY_KEY_POINTS rows, unpacked into one Claim per key point.

    `reasoning_json` maps kp_N -> the claim text, `scores_json` maps the same
    key to its signed impact. They are stored as parallel objects rather than
    one structure, so they are zipped on the key here.
    """
    # Claims are extracted per ARTICLE, and the ticker link is many-to-many, so
    # an article tagged with eight names donates every one of its key points to
    # all eight. Unfiltered, Crocs' narrative came back containing the Iran deal,
    # WTI crude at $80 and US natural gas storage — all real claims, none of them
    # about Crocs. Restricting to articles about at most `max_tickers` companies
    # is the same market-wrap exclusion the co-mention graph needs, for exactly
    # the same reason: a claim is only attributable to a ticker when the piece it
    # came from was actually about that ticker.
    cur.execute(f"""
        WITH focused AS (
            SELECT nat.article_id
            FROM {SCHEMA}.news_article_tickers nat
            JOIN {SCHEMA}.news_articles art ON art.id = nat.article_id
            WHERE COALESCE(art.published_at, art.created_at) >= %s
            GROUP BY nat.article_id
            HAVING COUNT(*) <= %s
        )
        SELECT h.article_id, h.scores_json, h.reasoning_json, nat.ticker,
               COALESCE(a.published_at, a.created_at)::date
        FROM {SCHEMA}.news_impact_heads h
        JOIN focused f ON f.article_id = h.article_id
        JOIN {SCHEMA}.news_article_tickers nat ON nat.article_id = h.article_id
        JOIN {SCHEMA}.news_articles a ON a.id = h.article_id
        WHERE h.cluster = 'STORY_KEY_POINTS'
          AND nat.ticker = ANY(%s)
          AND COALESCE(a.published_at, a.created_at) >= %s
        ORDER BY COALESCE(a.published_at, a.created_at) DESC
        LIMIT %s
    """, (since, max_tickers, tickers, since, limit))
    out = []
    for aid, scores, reasoning, tk, pub in cur.fetchall():
        if not isinstance(reasoning, dict):
            continue
        scores = scores if isinstance(scores, dict) else {}
        for key, text in reasoning.items():
            if not text:
                continue
            # The scorer writes "claim — why it matters"; the claim is the part
            # that belongs in the narrative corpus.
            head = str(text).split(" — ")[0].strip()
            if len(head) < 25:
                continue
            out.append(Claim(text=head, impact=float(scores.get(key) or 0.0),
                             article_id=int(aid), ticker=tk, published=pub))
    return out


def narrative(ticker: str, lookback_days: int = 180, include_network: bool = True,
              max_claims: int = 4000, half_life_days: float = 45.0,
              max_tickers: int = 4, as_of=None) -> Narrative:
    """Assemble the null: what is currently being said about this company.

    Claims are weighted by |impact| x exponential recency decay. Decay rather
    than a hard cutoff because a narrative does not switch off — a story from
    four months ago is still part of what is priced, just less of it. The
    half-life is the one free parameter and is reported with the result.
    """
    net = network(ticker, lookback_days) if include_network else {}
    # `owns` holds BRAND names (HEYDUDE), not tickers — they have no rows in the
    # news-ticker link table, so they are excluded from the claim scope here and
    # handed to the attention layer instead.
    peers = (net.get("competitor", []) + net.get("value_chain", [])
             + net.get("industry", []))
    scope = [ticker] + sorted(set(peers))
    ref = as_of or date.today()
    since = (ref - timedelta(days=lookback_days)).isoformat()

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(f"""
            SELECT COUNT(DISTINCT a.id)
            FROM {SCHEMA}.news_article_tickers nat
            JOIN {SCHEMA}.news_articles a ON a.id = nat.article_id
            WHERE nat.ticker = %s AND COALESCE(a.published_at, a.created_at) >= %s
        """, (ticker, since))
        n_articles = int(cur.fetchone()[0])

        claims = _claims(cur, scope, since, max_claims, max_tickers)

        # GROWTH_PROFILE is not one number: scores_json holds five sub-dimensions
        # (eps_growth_rate, eps_acceleration, revenue_growth_rate,
        # earnings_revision_trend, forward_growth_expectations). They are kept
        # apart because they say different things — a thesis about accelerating
        # demand contradicts a negative `forward_growth_expectations` far more
        # directly than a negative `eps_growth_rate`, which is backward-looking.
        # Rows with an all-zero object are the scorer declining to score rather
        # than a genuine neutral reading, and are excluded.
        cur.execute(f"""
            SELECT kv.key, AVG((kv.value)::text::float), COUNT(*)
            FROM {SCHEMA}.news_impact_heads h
            JOIN {SCHEMA}.news_article_tickers nat ON nat.article_id = h.article_id
            JOIN {SCHEMA}.news_articles a ON a.id = h.article_id
            CROSS JOIN LATERAL jsonb_each(h.scores_json) kv
            WHERE h.cluster = 'GROWTH_PROFILE' AND nat.ticker = %s
              AND COALESCE(a.published_at, a.created_at) >= %s
              AND h.scores_json::text <> '{{}}'
              AND jsonb_typeof(kv.value) = 'number'
              AND (kv.value)::text::float <> 0
            GROUP BY 1
        """, (ticker, since))
        gp = {k: (float(v), int(n)) for k, v, n in cur.fetchall()}
        growth_dims = {k: v for k, (v, _) in gp.items()}
        growth_n = sum(n for _, n in gp.values())
        growth = (float(np.mean(list(growth_dims.values()))) if growth_dims else None)

    today = date.today()
    for c in claims:
        age = max(0, (today - c.published).days)
        c.weight = abs(c.impact) * float(np.exp(-np.log(2) * age / half_life_days))
        # A claim about the company itself outweighs one about a peer: the peer
        # article shapes the narrative but is not about this business.
        if c.ticker != ticker:
            c.weight *= 0.4

    note = (f"{n_articles} articles on {ticker} and {len(claims)} claims across "
            f"{len(scope)} names over {lookback_days}d. Corpus is a sample of the "
            f"financial press: a LOW saturation score is weak evidence of a gap, "
            f"a HIGH score is strong evidence of saturation.")
    return Narrative(ticker=ticker, lookback_days=lookback_days, claims=claims,
                     growth_profile=growth, growth_dims=growth_dims, growth_n=growth_n,
                     article_count=n_articles, network=net, coverage_note=note)
