"""Is this already priced in? — confirming the baseline, not hunting a gap.

**The governing assumption of this module: if it is in our database, it is
priced in.** The corpus is scored financial press. By the time a proposition has
been written up, scored and indexed, the market has had it. There is no alpha to
be found by searching this corpus, and no version of this module should claim
otherwise.

That assumption makes the corpus valuable for exactly one thing, and it is not
the thing the first version of this module tried to do. It is a **map of the
baseline** — the set of propositions the current price already reflects. Knowing
that precisely is what makes a counterfactual thesis possible: you cannot say
what would change a price without first saying what the price already contains.

**So the verdicts are deliberately asymmetric, and one of them is a non-answer:**

* ``PRICED_IN``  — the proposition is in the corpus. Strong. It has been said,
  scored and indexed, so it is in the price. Nothing further to do with it.
* ``NOT_FOUND``  — the proposition is not in the corpus. **This is not evidence
  of anything.** Our corpus is a sample of the press; sell-side notes, terminal
  chatter and everything said out loud on a desk are outside it. A NOT_FOUND is
  a prompt to go and look at data that is not news, never a finding.
* ``OFF_TOPIC``  — the thesis does not name the company or a brand.
* ``INCONCLUSIVE`` — too few claims about the ticker itself to say either way.

The earlier design had a ``GAP`` verdict, which asserted that absence from the
corpus meant a proposition was unpriced. That was a false claim in the strong
direction and it was doing real damage: it ranked Crocs theses by embedding
distance from journalism while the arithmetic of the price said something
completely different. `implied.py` is now the null that matters — what the price
requires — and this module confirms which propositions are demonstrably already
inside it.

## The mechanics, and why they are still worth having

Two axes, because the naive one-axis version could not tell "nobody has said
this" from "this is not about anything":

* **Topicality** — an entity gate. Does the thesis name the company or one of
  its brands? Embedding similarity was the wrong instrument: a one-sentence
  claim and a multi-paragraph article chunk are different registers, so cosine
  measured how chunk-like a sentence reads rather than what it is about.
* **Saturation** — excess max-similarity to the ticker's OWN claims over a
  size-matched background of other companies' claims. Every comparison here is
  size-matched because the max of N draws grows with N regardless of meaning;
  that bias appeared in three separate places before it was pinned.

`python -m strategylab.social.cli control <TICKER>` calibrates the thresholds
against a matched null and verifies them on known-answer probes. Re-run it after
any change to the embedding model.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from ..data.news import _connect

log = logging.getLogger(__name__)

SCHEMA = "swingtrader"
OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "mxbai-embed-large")

# mxbai-embed-large is asymmetric: queries must carry this prefix and documents
# must not. The corpus was embedded document-side, so a query embedded without
# the prefix lands in a different part of the space and every similarity comes
# back uniformly low — which would read as "nothing is being said about this",
# the exact false positive this module exists to prevent.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def embed(text: str, timeout: float = 60.0) -> list[float]:
    """Embed a query string via Ollama.

    Tries `/api/embed` then `/api/embeddings`. The fallback is not decoration:
    the installed Ollama answers `/api/embed` by dropping the connection rather
    than returning 404, so a handler that only catches HTTP 404 (as the
    analytics copy of this does) raises `RemoteProtocolError` and never reaches
    the endpoint that works.
    """
    q = (text or "").strip()
    if not q:
        return []
    payloads = [("/api/embed", {"model": EMBED_MODEL, "input": [QUERY_PREFIX + q]}),
                ("/api/embeddings", {"model": EMBED_MODEL, "prompt": QUERY_PREFIX + q})]
    for path, body in payloads:
        req = urllib.request.Request(
            OLLAMA + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                d = json.load(fh)
        except Exception as exc:                             # noqa: BLE001
            log.debug("ollama %s failed: %s", path, exc)
            continue
        if isinstance(d.get("embeddings"), list) and d["embeddings"]:
            return [float(x) for x in d["embeddings"][0]]
        if isinstance(d.get("embedding"), list):
            return [float(x) for x in d["embedding"]]
    raise RuntimeError(
        f"could not embed via {OLLAMA} (model {EMBED_MODEL}). Is ollama running?")


# Chunks of cookie banners, nav furniture and inlined CSS. They are embedded
# alongside real text and they are the nearest neighbours of anything off-topic
# — the semiconductor control probe's top match was a "Paid Program" strip
# inside a Crocs article. Left in, they put a floor under every similarity and
# blur the separation the metric depends on.
_BOILERPLATE = re.compile(
    r"(we use cookies|cookie polic|paid program|privacy polic|all rights reserved"
    r"|subscribe to continue|sign up for|terms of service|\.[a-zA-Z0-9_-]{4,}\s*\{"
    r"|div\.[a-z-]+|:before|:not\(|advertisement)", re.I)


def _boilerplate(text: str, title: str = "") -> bool:
    """Chunks that carry no assertion: nav furniture, and title-echo stubs.

    The stub case is the subtle one. "Crocs: Sound Company But Close To Fair
    Value" is a 442-character article whose only chunk is its own title plus a
    one-line summary. It is generically about Crocs and therefore close to any
    statement about Crocs — it vetoed four unrelated theses at 0.76-0.81,
    including two BEARISH ones about Temu dupes and off-price leakage. A chunk
    that is mostly a restatement of its headline asserts nothing and must not be
    able to rule a proposition already covered.
    """
    t = (text or "").strip()
    if len(t) < 120:
        return True
    if _BOILERPLATE.search(t[:400]):
        return True
    ttl = (title or "").strip()
    if ttl and len(t) < 700 and t[:len(ttl)].lower() == ttl.lower():
        # Title echoed at the head of a short chunk: a summary card, not content.
        return True
    return False


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


# Below this many claims about the ticker ITSELF, saturation cannot separate
# "nobody has said this" from "we cannot see what has been said". Crocs had two
# usable ones, of which the catch-all "considered fairly valued at $125" matched
# five of six generated theses at 0.69-0.79 — that is not evidence they are
# priced in, it is evidence the corpus holds one generic sentence. Under this
# floor the verdict is INCONCLUSIVE, never PRICED_IN: a data gap must not read
# as a result, the same distinction the thesis lab draws between BLOCKED and
# FAILS.
MIN_OWN_CLAIMS = 8      # retained for the claim-level secondary read
MIN_CHUNKS = 40         # below this the article corpus cannot answer either way
MIN_TITLED_ARTICLES = 40  # chunks; below this the title filter is too aggressive


@dataclass
class Neighbour:
    text: str
    similarity: float
    source: str                    # "chunk" | "claim"
    title: str = ""
    published: str = ""


@dataclass
class SaturationScore:
    thesis: str
    ticker: str
    topicality: float              # mean sim to the ticker's nearest article chunks
    saturation: float              # EXCESS max sim over a size-matched background
    verdict: str                   # PRICED_IN | NOT_FOUND | OFF_TOPIC
                                   # | INCONCLUSIVE | NO_CORPUS
    saturation_raw: float = 0.0    # the raw max vs OWN claims, for interpretation
    sector_saturation: float = 0.0     # raw max vs PEER claims — reported only
    nearest_peer: str = ""
    entity_hit: str | None = None
    topicality_bar: float = float("nan")
    saturation_bar: float = float("nan")
    nearest_claims: list[Neighbour] = field(default_factory=list)
    nearest_chunks: list[Neighbour] = field(default_factory=list)
    n_chunks: int = 0
    n_claims: int = 0
    caveat: str = ""

    def to_dict(self) -> dict:
        return {"thesis": self.thesis, "ticker": self.ticker,
                "topicality": round(self.topicality, 4),
                "topicality_bar": round(self.topicality_bar, 4),
                "saturation": round(self.saturation, 4),
                "saturation_raw": round(self.saturation_raw, 4),
                "sector_saturation": round(self.sector_saturation, 4),
                "nearest_peer": self.nearest_peer,
                "saturation_bar": round(self.saturation_bar, 4),
                "verdict": self.verdict, "entity_hit": self.entity_hit,
                "n_chunks": self.n_chunks, "n_claims": self.n_claims,
                "nearest_claim": (self.nearest_claims[0].text[:160]
                                  if self.nearest_claims else None),
                "caveat": self.caveat}


def _unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=float)
    n = np.linalg.norm(a)
    return a / (n if n else 1.0)


class NarrativeSpace:
    """A ticker's corpus, embedded once, with its thresholds calibrated to it.

    Two reasons this is an object rather than a function.

    **Speed.** Scoring one thesis needs its similarity to every chunk and every
    claim. Doing that with a pgvector query per probe makes calibration — which
    needs ~60 null probes — cost 60 round trips. Pulling the ticker's chunk
    vectors once (a few hundred rows) turns all of it into one matrix multiply.

    **Calibration.** Fixed similarity thresholds do not survive contact with a
    different embedding model, a different ticker, or a thinner corpus. The
    first version of this used TOPICALITY_FLOOR = 0.42, chosen by guess, and the
    control immediately showed both a semiconductor claim (0.510) and literal
    word salad (0.451) clearing it and being reported as narrative GAPS.

    So the bar is measured, not chosen. `calibrate()` scores claims drawn from
    OTHER companies against this ticker's corpus: coherent, well-formed
    financial prose that is definitionally not about this company. Their
    topicality distribution is what "off-topic" looks like *here*, and the bar
    is its upper percentile. Same idea as the pairs study scoring a rolling
    anchor against random walks pushed through the same anchor — a
    transformation is only meaningful against a null that went through it too.
    """

    def __init__(self, ticker: str, claims: list[str], lookback_days: int = 180,
                 extra_tickers: list[str] | None = None, max_chunks: int = 600,
                 entities: list[str] | None = None,
                 own_claims: list[str] | None = None,
                 max_articles: int = 600):
        self.ticker = ticker
        self.claims = list(claims)
        self.lookback_days = lookback_days
        self.scope = [ticker] + list(extra_tickers or [])
        since = (date.today() - timedelta(days=lookback_days)).isoformat()

        with _connect() as conn, conn.cursor() as cur:
            # Articles are discovered by BOTH paths and unioned. They disagree:
            # over 180 days SBUX has 109 articles via `news_article_tickers` and
            # 86 via `search_tags`, of which 18 appear only in the tags array —
            # the same array the public /articles?tag=SBUX search reads. Using
            # either alone silently drops part of the coverage, and coverage is
            # the baseline this whole module is trying to measure.
            # Resolve article IDs FIRST, then filter the embeddings by id.
            # Expressing the union as an OR inside the join over 1.8M embedding
            # rows defeats every index and the query times out; `news_articles`
            # is 218k rows with indexes on both paths, so the id set is cheap
            # and the second query becomes a straight lookup. Same shape as the
            # Wikidata fix — bind the expensive scan to a small known set.
            # Bounded and ordered. Unbounded, this returns every article in the
            # window — 14,392 for AAPL — and the follow-up chunk query with that
            # many ids in an ANY() times out. The chunk pull is already capped,
            # so all the extra ids buy is a query that fails on exactly the
            # best-covered names.
            cur.execute(f"""
                SELECT a.id FROM {SCHEMA}.news_articles a
                WHERE COALESCE(a.published_at, a.created_at) >= %s
                  AND (a.search_tags && %s
                       OR EXISTS (SELECT 1 FROM {SCHEMA}.news_article_tickers nat
                                  WHERE nat.article_id = a.id
                                    AND nat.ticker = ANY(%s)))
                ORDER BY COALESCE(a.published_at, a.created_at) DESC
                LIMIT %s
            """, (since, self.scope, self.scope, max_articles))
            art_ids = [r[0] for r in cur.fetchall()]
            self.n_articles = len(art_ids)
            rows = []
            if art_ids:
                cur.execute(f"""
                    SELECT e.chunk_text, e.embedding::text, a.title,
                           e.published_at::date,
                           (a.search_tags && %s
                            OR EXISTS (SELECT 1 FROM {SCHEMA}.news_article_tickers n2
                                       WHERE n2.article_id = a.id
                                         AND n2.ticker = %s)) AS is_own
                    FROM {SCHEMA}.news_article_embeddings e
                    JOIN {SCHEMA}.news_articles a ON a.id = e.article_id
                    WHERE e.article_id = ANY(%s)
                    ORDER BY e.published_at DESC
                    LIMIT %s
                """, ([ticker], ticker, art_ids, max_chunks * 3))
                rows = [r for r in cur.fetchall()
                        if not _boilerplate(r[0], r[2])][:max_chunks]

            # A BACKGROUND corpus of everyone else's chunks, over the same
            # period. Absolute cosine similarity is close to useless here:
            # mxbai puts all financial prose in a narrow band, so a claim taken
            # VERBATIM from Crocs' own coverage scored 0.615 against Crocs
            # chunks while random other-company claims averaged 0.599. A 0.016
            # separation cannot support a threshold, and the first calibration
            # duly classified that verbatim claim as OFF_TOPIC.
            #
            # Subtracting the background cancels the compression. What matters
            # is not "how similar is this to Crocs" but "how much MORE similar
            # is it to Crocs than to companies at large" — a contrast, which is
            # the same reason every other study in this project scores against a
            # matched null rather than against zero.
            # SIZE-MATCHED to the target pool. Both sides are compared by
            # mean-of-top-k, and the top k of a larger pool is systematically
            # higher whatever the pool means — with 3,000 background chunks
            # against 600 target chunks the background won on sample size alone,
            # and a claim lifted verbatim from Starbucks' own coverage came back
            # OFF_TOPIC. This is the third place the same order-statistic bias
            # appeared in this metric (topicality pool, claim count, and here);
            # any max- or top-k comparison in it must be matched on N.
            cur.execute(f"""
                SELECT e.embedding::text
                FROM {SCHEMA}.news_article_embeddings e
                WHERE e.published_at >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM {SCHEMA}.news_article_tickers nat
                      WHERE nat.article_id = e.article_id AND nat.ticker = ANY(%s))
                ORDER BY e.id DESC
                LIMIT %s
            """, (since, self.scope, max(1, len(rows))))
            bg = cur.fetchall()

        self.chunk_meta = [(r[0] or "", r[2] or "", str(r[3])) for r in rows]
        # Which chunks are about THIS company rather than a peer.
        #
        # Being TAGGED with the ticker is not enough, which is the same
        # many-to-many trap as the claims. "Columbia Sportswear's ACCELERATE
        # Strategy" and "Billionaire Investor David Einhorn Just Bought These
        # Beaten-Down Consumer Stocks" are both tagged CROX because they mention
        # it, and both were retrieved as evidence about Crocs' price drivers.
        # Requiring the company or one of its brands in the TITLE is what
        # separates "an article about this company" from "an article that
        # mentions it".
        names = [n.lower() for n in ([ticker] + list(entities or [])) if n and len(n) > 2]
        titled, tagged_only = [], []
        for r in rows:
            tagged = bool(r[4]) if len(r) > 4 else True
            title = (r[2] or "").lower()
            titled.append(tagged and any(n in title for n in names))
            tagged_only.append(tagged)

        # Degrade gracefully. The title test depends on the entity list being
        # complete, and it is not always: Nike's entities came back as
        # 'Air Jordan', 'Converse', 'Jumpman' and so on without the plain
        # company name, which collapsed 48 tagged articles to 2. A filter that
        # silently discards 96% of the evidence is worse than a loose one, so
        # fall back when it leaves too little and record which mode was used.
        n_titled = sum(titled)
        if n_titled >= MIN_TITLED_ARTICLES:
            self.is_own = titled
            self.own_mode = "title"
        else:
            self.is_own = tagged_only
            self.own_mode = "tagged"
            log.info("%s: only %d chunks survive the title filter (entity list is "
                     "probably missing the company name); falling back to "
                     "tag-scoped retrieval", ticker, n_titled)
        self.chunks = (np.vstack([_unit(json.loads(r[1])) for r in rows])
                       if rows else np.zeros((0, 1)))
        self.background = (np.vstack([_unit(json.loads(r[0])) for r in bg])
                           if bg else np.zeros((0, 1)))
        # OWN claims and PEER claims are kept apart, because they answer
        # different questions and pooling them answered neither.
        #
        # Scored against the pooled corpus, a Jibbitz thesis matched
        # "Birkenstock's cost of sales rose 18% YoY" at 0.64 and was ruled
        # priced in. The two sentences share nothing but the footwear industry;
        # the metric was measuring sector membership. Meanwhile the one thesis
        # that genuinely WAS in the coverage — the HEYDUDE wholesale reset —
        # matched its real claim at 0.82 and scored barely higher.
        #
        #   saturation      = vs the ticker's OWN claims. "Has anyone asserted
        #                     this ABOUT THIS COMPANY?" This gates the verdict.
        #   sector_saturation = vs PEER claims. "Is this a known sector story?"
        #                     Reported, not gating: a story circulating about
        #                     Nike is context for a Crocs thesis, not a
        #                     statement that the Crocs version is priced.
        self.own_claims = list(own_claims if own_claims is not None else claims)
        self.peer_claims = [c for c in self.claims if c not in set(self.own_claims)]
        self.claim_vecs = (np.vstack([_unit(embed(c)) for c in self.own_claims])
                           if self.own_claims else np.zeros((0, 1)))
        self.peer_vecs = (np.vstack([_unit(embed(c)) for c in self.peer_claims])
                          if self.peer_claims else np.zeros((0, 1)))
        # A background claim set of the SAME SIZE as the target's. Saturation is
        # a max over N claims, and the max of N draws grows with N whatever the
        # draws mean — random other-company claims scored 0.63 max-similarity
        # against Crocs' 60 claims purely as an order statistic, which put the
        # bar above what a genuine paraphrase (0.667) could reach. Matching the
        # count cancels that exactly; it is the same reason the discovery loop
        # compares against sqrt(2 ln N) rather than a constant.
        # Named entities that make a thesis unambiguously about this company:
        # the ticker, the company name, and its brands (Wikidata + the
        # relationship graph's `subsidiary`/`acquirer` edges — CROX -> HEYDUDE).
        self.entities = [e.lower() for e in (entities or []) if e and len(e) > 2]
        self.bg_claims: list[str] = []
        self.bg_claim_vecs = np.zeros((0, 1))
        self.topicality_bar = float("nan")
        self.saturation_bar = float("nan")

    # ------------------------------------------------------------------
    @staticmethod
    def _mean_top(mat: np.ndarray, qv: np.ndarray, top_k: int) -> float:
        if not len(mat):
            return 0.0
        sims = mat @ qv
        k = min(top_k, len(sims))
        return float(np.mean(np.sort(sims)[-k:]))

    def mentions_entity(self, text: str) -> str | None:
        """Does the text name this company or one of its brands?

        Embedding similarity turned out to be the wrong instrument for the
        topicality question. A one-sentence claim and a multi-paragraph article
        chunk are different registers, and their cosine similarity is dominated
        by that difference rather than by subject: claims taken VERBATIM from
        Crocs' and Starbucks' own coverage scored +0.04 and +0.05 excess
        topicality, against +0.16 and +0.25 for Nike and Monster. The axis was
        measuring how chunk-like a sentence reads, not what it is about.

        Naming is a better instrument for this specific question, and we already
        have the entities: the ticker, the company name, and its brands from the
        Wikidata dictionary and the relationship graph. "Crocs' Jibbitz charms
        are becoming recurring revenue" is on-topic; word salad and a
        semiconductor claim are not, and no threshold is needed to tell.
        """
        low = (text or "").lower()
        for e in self.entities:
            # Length and word-boundary checks live here rather than in
            # __init__ so they hold however `entities` was populated, and so a
            # short or substring-prone name cannot slip through: "ADS" would
            # otherwise match inside "adsorption", and a two-letter brand
            # matches almost everything.
            if len(e) <= 2:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(e)}(?![a-z0-9])", low):
                return e
        return None

    def _topicality(self, qv: np.ndarray, top_k: int = 8) -> tuple[float, np.ndarray]:
        """Excess chunk similarity — reported as a covariate, not a gate.

        Kept because it is informative about how close a thesis sits to the
        company's subject matter, but it no longer decides OFF_TOPIC. See
        `mentions_entity`.
        """
        if not len(self.chunks):
            return 0.0, np.zeros(0)
        sims = self.chunks @ qv
        idx = np.argsort(-sims)[:top_k]
        mine = float(np.mean(sims[idx]))
        return mine - self._mean_top(self.background, qv, top_k), idx

    def _saturation(self, qv: np.ndarray, top_k: int = 8) -> tuple[float, np.ndarray]:
        """Excess max-similarity to the ticker's ARTICLE TEXT over a
        size-matched background of other companies' article text.

        Scored against article chunks, not against extracted claims, and the
        difference is not marginal. Crocs' 26 articles over 180 days carry
        235,000 characters of body text; the STORY_KEY_POINTS extraction of them
        is 6 one-line claims totalling 639 characters, of which three are about
        David Einhorn's positions rather than the business. Scored on the claims
        alone, four generated theses came back unmatched and looked novel.
        Scored on the bodies, the "India / international expansion" thesis
        matches "Crocs Bets Big On Sandals As It Eyes $500 Million Milestone" at
        0.816 — a chunk that reads "International markets, particularly India,
        are crucial due to year-round warm climates" — and the HEYDUDE thesis
        matches an article titled "Crocs: The HEYDUDE Turnaround Is Finally
        Taking Shape". All of it was already in the database.

        The register concern that pushed claims to the fore earlier does not
        apply in this direction: a thesis is a long multi-clause statement, and
        so is a chunk. The control confirms the separation — real theses land at
        0.70-0.82, an off-topic probe at 0.57.
        """
        if not len(self.chunks):
            return 0.0, np.zeros(0)
        sims = self.chunks @ qv
        idx = np.argsort(-sims)[:top_k]
        # Mean of the top THREE, not the single max. "Already written up" should
        # mean there is substantive coverage of the proposition, not that one
        # sentence somewhere is vaguely close to it. A max over hundreds of
        # chunks is an order statistic and will always find something; requiring
        # three passages to be near forces the match to come from real article
        # body rather than from one generic line. The sandals article matched a
        # thesis on three separate chunks (0.82/0.80/0.77); the stub matched on
        # exactly one.
        k = min(3, len(sims))
        raw = float(np.mean(np.sort(sims)[-k:]))
        bg = 0.0
        if len(self.background):
            bsims = self.background @ qv
            bk = min(3, len(bsims))
            bg = float(np.mean(np.sort(bsims)[-bk:]))
        return raw - bg, idx

    # ------------------------------------------------------------------
    def calibrate(self, n_null: int = 60, pct: float = 95.0,
                  saturation_pct: float = 75.0, seed: int = 11) -> dict:
        """Measure what off-topic looks like against THIS corpus.

        The null is other companies' claims: coherent financial prose that is
        not about this ticker. Claims from the ticker's own peer group are
        excluded — a Birkenstock claim is genuinely on-topic for Crocs, and
        including it would inflate the bar until real theses failed it.
        """
        rng = np.random.default_rng(seed)
        since = (date.today() - timedelta(days=self.lookback_days)).isoformat()
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(f"""
                SELECT h.reasoning_json
                FROM {SCHEMA}.news_impact_heads h
                JOIN {SCHEMA}.news_article_tickers nat ON nat.article_id = h.article_id
                JOIN {SCHEMA}.news_articles a ON a.id = h.article_id
                WHERE h.cluster = 'STORY_KEY_POINTS'
                  AND NOT (nat.ticker = ANY(%s))
                  AND COALESCE(a.published_at, a.created_at) >= %s
                  AND h.reasoning_json::text <> '{{}}'
                ORDER BY h.id DESC
                LIMIT 4000
            """, (self.scope, since))
            pool = []
            for (reasoning,) in cur.fetchall():
                if isinstance(reasoning, dict):
                    for t in reasoning.values():
                        head = str(t or "").split(" — ")[0].strip()
                        if len(head) >= 40:
                            pool.append(head)
        if len(pool) < 10:
            log.warning("null pool too small (%d); thresholds left uncalibrated", len(pool))
            return {"n_null": len(pool)}

        # Matched background claim set, drawn disjointly from the null probes so
        # a probe is never scored against itself.
        # Size-matched to the OWN-claim set, which is what saturation scores
        # against — matching the pooled corpus would reintroduce the
        # order-statistic bias this whole metric keeps tripping over.
        n_bg = min(max(len(self.own_claims), 1), max(0, len(pool) - n_null))
        perm = rng.permutation(len(pool))
        bg_idx, probe_idx = perm[:n_bg], perm[n_bg:n_bg + min(n_null, len(pool) - n_bg)]
        self.bg_claims = [pool[int(i)] for i in bg_idx]
        self.bg_claim_vecs = (np.vstack([_unit(embed(c)) for c in self.bg_claims])
                              if self.bg_claims else np.zeros((0, 1)))

        pick = probe_idx
        tops, sats = [], []
        for i in pick:
            qv = _unit(embed(pool[int(i)]))
            t, _ = self._topicality(qv)
            s, _ = self._saturation(qv)
            tops.append(t)
            sats.append(s)
        self.topicality_bar = float(np.percentile(tops, pct))
        # The two bars use DIFFERENT percentiles on purpose, because their errors
        # are not symmetric. PRICED_IN is a conclusion; NOT_FOUND is a
        # non-answer that sends the thesis on to be tested against non-news
        # data. Being too eager to say PRICED_IN costs an idea; being too
        # reluctant lets a proposition the market has plainly digested travel
        # further down the pipeline dressed as new. The second is worse, so the
        # saturation bar sits low — more propositions are ruled priced in —
        # while the topicality gate stays strict.
        self.saturation_bar = float(np.percentile(sats, saturation_pct))
        return {"n_null": len(tops), "pct": pct, "saturation_pct": saturation_pct,
                "topicality_bar": self.topicality_bar,
                "topicality_null_median": float(np.median(tops)),
                "saturation_bar": self.saturation_bar,
                "saturation_null_median": float(np.median(sats)),
                "n_chunks": int(len(self.chunks)), "n_claims": int(len(self.claims))}

    def retrieve(self, thesis: str, k: int = 10,
                 own_only: bool = False) -> list[tuple[str, str]]:
        """The k most related passages, as (title, text), for a reader.

        This is what embeddings are actually good for. Deciding whether a
        proposition is asserted is left to a reader; narrowing hundreds of
        thousands of chunks to the dozen worth reading is not.

        `own_only` restricts to articles about this ticker. Use it for anything
        reconstructing THIS company's drivers; leave it off for the narrative,
        where the peer frame is the point.
        """
        if not len(self.chunks):
            return []
        sims = self.chunks @ _unit(embed(thesis))
        own = getattr(self, "is_own", [True] * len(self.chunks))
        out, seen = [], set()
        for i in np.argsort(-sims):
            if own_only and not own[i]:
                continue
            title, text = self.chunk_meta[i][1], self.chunk_meta[i][0]
            key = (title, text[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append((title, text))
            if len(out) >= k:
                break
        return out

    def retrieval_discrimination(self, k: int, own_only: bool = False) -> dict:
        """How much of the corpus a top-k pull actually leaves behind.

        When k approaches the number of distinct articles available, retrieval
        is not selecting — it is returning everything, and any apparent
        driver-matching is happening in the reader rather than in the search.
        Crocs' bull and bear cases shared 60% of their sources for exactly this
        reason. Reported so a thin-corpus result is not mistaken for a targeted
        one.
        """
        own = getattr(self, "is_own", [True] * len(self.chunks))
        pool = [i for i in range(len(self.chunks)) if not own_only or own[i]]
        titles = {self.chunk_meta[i][1] for i in pool}
        return {"chunks_available": len(pool), "distinct_articles": len(titles),
                "k": k, "selective": len(titles) > k * 2,
                "scope_mode": getattr(self, "own_mode", "tagged"),
                "note": ("retrieval is selecting" if len(titles) > k * 2 else
                         "corpus too thin for retrieval to discriminate — a top-k "
                         "pull returns most of what exists")}

    # ------------------------------------------------------------------
    def score(self, thesis: str, top_k: int = 8) -> SaturationScore:
        caveat = ("If it is in this corpus it is priced in. PRICED_IN is a strong "
                  "read; NOT_FOUND is not evidence of anything, because the corpus "
                  "is only a sample of what the market has heard.")
        tbar, sbar = self.topicality_bar, self.saturation_bar
        if not np.isfinite(sbar):
            # Checked before anything else, including the embedding call: an
            # uncalibrated threshold is the configuration that reported literal
            # word salad as a narrative gap, and it must not be reachable.
            raise RuntimeError("call calibrate() before score(): an uncalibrated "
                               "threshold reported word salad as a narrative gap")
        if not len(self.chunks):
            return SaturationScore(thesis=thesis, ticker=self.ticker, topicality=0.0,
                                   saturation=0.0, verdict="NO_CORPUS", caveat=caveat)
        qv = _unit(embed(thesis))
        top, tidx = self._topicality(qv, top_k)
        sat, sidx = self._saturation(qv, top_k)
        raw_sat = 0.0
        if len(self.chunks):
            _cs = np.sort(self.chunks @ qv)
            raw_sat = float(np.mean(_cs[-min(3, len(_cs)):]))
        sec_raw, near_peer = 0.0, ""
        if len(self.peer_vecs):
            psims = self.peer_vecs @ qv
            j = int(np.argmax(psims))
            sec_raw, near_peer = float(psims[j]), self.peer_claims[j]

        # Gate on naming, rank on saturation. A thesis that never names the
        # company or any of its brands is not a thesis about the company,
        # whatever it scores.
        hit = self.mentions_entity(thesis)
        if hit is not None and len(self.chunks) < MIN_CHUNKS:
            # A data problem, not a result — the same distinction the thesis
            # lab draws between BLOCKED and FAILS. Reporting PRICED_IN here
            # would retire a thesis on the strength of missing coverage.
            return SaturationScore(
                thesis=thesis, ticker=self.ticker, topicality=0.0, saturation=0.0,
                verdict="INCONCLUSIVE", entity_hit=hit,
                n_chunks=int(len(self.chunks)), n_claims=len(self.claims),
                caveat=(f"only {len(self.chunks)} article chunks for "
                        f"{self.ticker} (need {MIN_CHUNKS}); the corpus cannot "
                        f"say whether this has been written up."))
        if hit is None:
            # A GENERATION CONTRACT, not a filter on the world. Stage 2 authors
            # these theses, so it can be required to name the subject — and must
            # be, because an unnamed thesis is genuinely ambiguous ("margins will
            # expand" is about nobody). Note the asymmetry with claims EXTRACTED
            # from articles, which routinely omit the company because the
            # surrounding article supplies it; those are not theses and are not
            # scored through this path.
            verdict = "OFF_TOPIC"
        elif sat >= sbar:
            verdict = "PRICED_IN"
        else:
            # NOT_FOUND, never "GAP". The corpus is a sample of the press, so
            # absence from it is not evidence the proposition is unpriced — it
            # is only a reason to go and look somewhere that is not news.
            verdict = "NOT_FOUND"

        chunk_sims = self.chunks @ qv
        near_chunks = [Neighbour(text=self.chunk_meta[i][0][:400],
                                 similarity=float(chunk_sims[i]), source="chunk",
                                 title=self.chunk_meta[i][1],
                                 published=self.chunk_meta[i][2]) for i in tidx]
        near_claims = [Neighbour(text=self.chunk_meta[i][0][:300].strip(),
                                 similarity=float(chunk_sims[i]), source="article",
                                 title=self.chunk_meta[i][1],
                                 published=self.chunk_meta[i][2])
                       for i in sidx if i < len(self.chunk_meta)]
        return SaturationScore(thesis=thesis, ticker=self.ticker, topicality=top,
                               saturation=sat, saturation_raw=raw_sat,
                               sector_saturation=sec_raw, nearest_peer=near_peer[:200],
                               verdict=verdict,
                               topicality_bar=tbar, saturation_bar=sbar,
                               entity_hit=hit,
                               nearest_claims=near_claims, nearest_chunks=near_chunks,
                               n_chunks=int(len(self.chunks)),
                               n_claims=len(self.claims), caveat=caveat)
