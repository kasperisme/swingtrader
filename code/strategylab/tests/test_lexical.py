"""The full-text vector space that replaced stored embeddings (Nov 2026).

Tokenisation is Postgres's (`to_tsvector('english')`) and is not exercised here;
these pin the arithmetic on top of it, which is what every similarity in the
saturation metric now rests on.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from strategylab.social.lexical import LexicalSpace, article_chunks, chunk_text, strip_html


def _docs():
    return [
        Counter({"croc": 3, "sandal": 2, "india": 1}),
        Counter({"croc": 2, "heydud": 3, "wholesal": 2}),
        Counter({"nvidia": 2, "gpu": 3, "foundri": 1}),
        Counter({"croc": 1, "sandal": 1, "intern": 2, "india": 2}),
    ]


def test_rows_are_unit_length_and_cosine_is_a_dot_product():
    sp = LexicalSpace(_docs(), min_df=1)
    m = sp.vectorize(_docs())
    assert np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-5)
    assert np.all(m @ m[0] <= 1.0 + 1e-5)


def test_shared_vocabulary_scores_higher_than_disjoint():
    sp = LexicalSpace(_docs(), min_df=1)
    m = sp.vectorize(_docs())
    q = sp.vectorize([Counter({"sandal": 1, "india": 1})])[0]
    sims = m @ q
    assert sims[0] > sims[2] and sims[3] > sims[2]
    assert sims[2] == 0.0


def test_out_of_vocabulary_text_is_the_zero_vector_not_a_crash():
    """Word salad shares no lexeme with the corpus: similarity 0 to everything,
    which the calibrated bar then reads as NOT_FOUND / OFF_TOPIC."""
    sp = LexicalSpace(_docs(), min_df=1)
    q = sp.vectorize([Counter({"purpl": 1, "umbrella": 1})])[0]
    assert not q.any()


def test_idf_downweights_a_lexeme_in_every_document():
    docs = [Counter({"croc": 1, f"w{i}": 1}) for i in range(5)]
    sp = LexicalSpace(docs, min_df=1)
    assert sp.idf[sp.index["croc"]] < sp.idf[sp.index["w0"]]


def test_min_df_drops_singletons_on_a_real_sized_corpus():
    docs = [Counter({"common": 1, f"only{i}": 1}) for i in range(30)]
    sp = LexicalSpace(docs)
    assert "common" in sp.index and "only0" not in sp.index


def test_chunking_matches_the_retired_pipeline():
    assert strip_html("<p>Hi <b>there</b></p><style>.x{a:b}</style>") == "Hi there"
    long = ("Sentence one is here. " * 80).strip()
    chunks = chunk_text(long)
    assert len(chunks) > 1 and all(len(c) <= 900 for c in chunks)
    assert article_chunks("Title", "<p>Body</p>") == ["Title Body"]
