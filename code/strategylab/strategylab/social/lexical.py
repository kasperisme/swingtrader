"""Full-text vectors over article bodies — the replacement for stored embeddings.

Until Nov 2026 the narrative space read pre-computed `mxbai-embed-large` chunk
vectors from `swingtrader.news_article_embeddings`. That table was 32 GB of a
38 GB database, and the platform retired it: every news read now goes through
the same tag-overlap / Postgres full-text cascade (`search_news_by_tags`,
`search_news_fulltext`). This module is the priced-in pipeline's half of that
move.

**What a vector is now.** Text is tokenised by Postgres itself —
`to_tsvector('english', text)`, the exact parser, stop-word list and Snowball
stemmer behind `search_news_fulltext` — so "expansion" and "expanding" meet
at `expans`, exactly as they do in a search. Each document becomes a sublinear
TF-IDF vector over the lexemes of the corpus it was fitted on, L2-normalised,
so `matrix @ query` is a cosine similarity just as it was with embeddings, and
every caller that did that arithmetic keeps working unchanged.

**What that gives up.** Lexical similarity only sees shared words. A thesis
that paraphrases coverage without reusing its vocabulary scores lower than it
did under embeddings. Nothing in the saturation metric relies on absolute
similarity values — every bar is measured against a matched null drawn
through the same transformation (see `NarrativeSpace.calibrate`) — so the
verdict logic survives the change, but the bars must be re-measured (run
`cli control <TICKER>`), and no number recorded under the embedding era is
comparable with one recorded under this.

**IDF is per-corpus, on purpose.** A space is fitted on the documents it will
score against (a ticker's chunks plus its size-matched background). "Crocs"
is rare in the market at large and common in Crocs' coverage; fitting on the
local corpus is what keeps the company's own name from dominating every match
inside it, the same reason the embedding version subtracted a background.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from functools import lru_cache

import numpy as np

from ..data.news import _connect

log = logging.getLogger(__name__)

SCHEMA = "swingtrader"

#: Vocabulary cap. Keeps the dense matrices small (600 own + 600 background
#: chunks x 8,000 float32 is ~38 MB) while covering every lexeme that appears
#: in more than one document of a typical ticker's corpus.
MAX_FEATURES = 8000
#: A lexeme seen in a single document cannot connect two texts in the corpus;
#: it only adds a dimension. Dropped unless the corpus is too small to afford it.
MIN_DF = 2

# ── Body text → chunks ───────────────────────────────────────────────────────
# Ported from the retired embedding pipeline so a chunk means the same span of
# text it did before: title + stripped body, ~900 chars, 120 overlap, split on
# sentence ends.

_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s{2,}")
_CSS_AT_RE = re.compile(r"@[\w-]+[^{;]*\{(?:[^{}]|\{[^}]*\})*\}", re.DOTALL)
_CSS_RULE_RE = re.compile(
    r"(?<!\w)[.#:_\[][\w\-\[\]().#:,\s>~+*=\"'@^\$|]{0,300}?\{[^{}]{0,5000}?\}",
    re.DOTALL,
)
_CSS_ORPHAN_RE = re.compile(r"^.*?\}(?=\s*[A-Z])", re.DOTALL)


def strip_html(html: str) -> str:
    """Strip tags, style/script blocks and raw CSS rule blocks."""
    text = _STYLE_RE.sub(" ", html or "")
    text = _SCRIPT_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _CSS_AT_RE.sub(" ", text)
    text = _CSS_RULE_RE.sub(" ", text)
    text = _CSS_ORPHAN_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip()).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        j = min(n, i + max_chars)
        if j < n:
            split = text.rfind(". ", i + max_chars // 2, j)
            if split > i:
                j = split + 1
        chunk = text[i:j].strip()
        if chunk:
            out.append(chunk)
        if j >= n:
            break
        i = max(j - overlap_chars, i + 1)
    return out


def article_chunks(title: str, body: str) -> list[str]:
    """The chunks one article contributes, exactly as the old pipeline cut them."""
    return chunk_text(f"{title or ''}\n\n{strip_html(body or '')}".strip())


# ── Tokenisation (Postgres) ──────────────────────────────────────────────────


def lexemes(texts: list[str]) -> list[Counter]:
    """`to_tsvector('english', t)` for every text, as lexeme -> count.

    One round trip for the whole batch. The count is the number of positions
    Postgres recorded for the lexeme (it caps positions at 256 per lexeme, far
    above anything a 900-character chunk reaches).
    """
    out = [Counter() for _ in texts]
    if not texts:
        return out
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.ord, (v).lexeme, COALESCE(array_length((v).positions, 1), 1)
            FROM unnest(%s::text[]) WITH ORDINALITY AS t(txt, ord),
                 LATERAL unnest(to_tsvector('english', t.txt)) AS v
            """,
            ([t or "" for t in texts],),
        )
        for ord_, lex, n in cur.fetchall():
            out[int(ord_) - 1][lex] = int(n)
    return out


@lru_cache(maxsize=4096)
def _lexemes_one(text: str) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(lexemes([text])[0].items()))


# ── The vector space ─────────────────────────────────────────────────────────


class LexicalSpace:
    """Sublinear TF-IDF over Postgres lexemes, fitted on one corpus."""

    def __init__(self, docs: list[Counter], max_features: int = MAX_FEATURES,
                 min_df: int = MIN_DF):
        n = len(docs)
        df: Counter = Counter()
        for d in docs:
            df.update(d.keys())
        floor = min_df if n >= 20 else 1
        vocab = [t for t, c in df.items() if c >= floor]
        vocab.sort(key=lambda t: (-df[t], t))
        vocab = vocab[:max_features]
        self.index = {t: i for i, t in enumerate(vocab)}
        # sklearn's smooth IDF, so a lexeme in every document still counts a little.
        self.idf = np.array([math.log((1 + n) / (1 + df[t])) + 1.0 for t in vocab],
                            dtype=np.float32)
        self.dim = max(1, len(vocab))

    def vectorize(self, docs: list[Counter]) -> np.ndarray:
        """Rows of L2-normalised TF-IDF. Lexemes outside the vocabulary drop out;
        a text that shares no lexeme with the corpus is the zero vector, whose
        similarity to everything is 0 — the honest answer."""
        mat = np.zeros((len(docs), self.dim), dtype=np.float32)
        for r, d in enumerate(docs):
            for t, c in d.items():
                j = self.index.get(t)
                if j is not None:
                    mat[r, j] = (1.0 + math.log(c)) * self.idf[j]
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return mat / norms

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return self.vectorize(lexemes(texts))

    def embed(self, text: str) -> np.ndarray:
        """One unit vector — the drop-in for `_unit(embed(text))`."""
        return self.vectorize([Counter(dict(_lexemes_one(text or "")))])[0]


def fetch_bodies(article_ids: list[int]) -> dict[int, tuple[str, str]]:
    """id -> (title, body) for the given articles, in one query."""
    if not article_ids:
        return {}
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id, title, body FROM {SCHEMA}.news_articles WHERE id = ANY(%s)",
            (list(article_ids),),
        )
        return {int(r[0]): (r[1] or "", r[2] or "") for r in cur.fetchall()}
