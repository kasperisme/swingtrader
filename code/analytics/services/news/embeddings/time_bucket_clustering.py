"""
Build hourly / daily K-means clusters over `news_article_embeddings` (UTC buckets).

Vectors are mean-pooled per article (all chunks in the bucket), L2-normalised, then
MiniBatchKMeans (cosine-friendly). Writes to separate hourly vs daily table families:

  swingtrader.news_embedding_hourly_cluster_{runs,centroids,articles}
  swingtrader.news_embedding_daily_cluster_{runs,centroids,articles}

Each centroid row stores ``centroid`` (float8[]) and ``reverse_embedding_text``: a short
theme label produced by **Ollama** from the member chunks in that cluster (same time
bucket). ``reverse_embedding_article_id`` / ``reverse_embedding_chunk_index`` identify
the chunk nearest the centroid within the cluster (provenance anchor).
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

import httpx
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.preprocessing import normalize

from shared.db import get_pg_connection

logger = logging.getLogger(__name__)

_SCHEMA = os.environ.get("SUPABASE_SCHEMA", "swingtrader")
_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
_MAX_REVERSE_TEXT_LEN = 12000
_DEFAULT_CLUSTER_LABEL_MODEL = "llama3.2"


@dataclass(frozen=True)
class Bucket:
    granularity: str  # "hour" | "day"
    start: datetime  # UTC inclusive
    end: datetime  # UTC exclusive


@dataclass(frozen=True)
class ChunkRow:
    article_id: int
    chunk_index: int
    embedding: np.ndarray
    chunk_text: str


def utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def floor_hour_utc(dt: datetime) -> datetime:
    d = utc(dt)
    return d.replace(minute=0, second=0, microsecond=0)


def floor_day_utc(dt: datetime) -> datetime:
    d = utc(dt)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _cluster_tables(granularity: str) -> tuple[str, str, str]:
    g = granularity.lower().strip()
    if g == "hour":
        return (
            "news_embedding_hourly_cluster_runs",
            "news_embedding_hourly_cluster_centroids",
            "news_embedding_hourly_cluster_articles",
        )
    if g == "day":
        return (
            "news_embedding_daily_cluster_runs",
            "news_embedding_daily_cluster_centroids",
            "news_embedding_daily_cluster_articles",
        )
    raise ValueError("granularity must be 'hour' or 'day'")


def iter_buckets(granularity: str, since: datetime, until: datetime) -> Iterator[Bucket]:
    """Yield [start, end) UTC buckets. First bucket starts at UTC hour/day floor of ``since``."""
    g = granularity.lower().strip()
    if g not in ("hour", "day"):
        raise ValueError("granularity must be 'hour' or 'day'")
    a = utc(since)
    b = utc(until)
    if b <= a:
        return
    if g == "hour":
        cur = floor_hour_utc(a)
        while cur < b:
            nxt = cur + timedelta(hours=1)
            yield Bucket("hour", cur, nxt)
            cur = nxt
    else:
        cur = floor_day_utc(a)
        while cur < b:
            nxt = cur + timedelta(days=1)
            yield Bucket("day", cur, nxt)
            cur = nxt


def pick_n_clusters(n_articles: int, *, max_k: int, min_per_cluster: int) -> int:
    if n_articles <= 0:
        return 0
    if n_articles == 1:
        return 1
    k = n_articles // max(1, min_per_cluster)
    k = min(max_k, max(k, 2))
    return max(1, min(k, n_articles))


def _parse_vector_text(s: str) -> np.ndarray:
    s = (s or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    if not s:
        return np.zeros(0, dtype=np.float64)
    parts = [p for p in re.split(r"\s*,\s*", s) if p]
    return np.array([float(x) for x in parts], dtype=np.float64)


def _safe_reverse_text(s: str) -> str:
    return (s or "").replace("\x00", "")[:_MAX_REVERSE_TEXT_LEN]


def _clean_llm_label(raw: str) -> str:
    t = (raw or "").strip()
    # Reasoning / thinking blocks (strip before visible answer)
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<thinking>.*?</thinking>", "", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"```[a-z]*\s*|\s*```", "", t, flags=re.IGNORECASE)
    t = t.strip().strip("\"'“”")
    t = re.sub(r"\s+", " ", t).strip()
    return _safe_reverse_text(t)


def _extract_ollama_chat_content(body: object) -> str:
    """Parse non-streaming /api/chat JSON body."""
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if err:
        raise RuntimeError(str(err))
    msg = body.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, str):
            return c
    r = body.get("response")
    if isinstance(r, str):
        return r
    return ""


def _is_usable_cluster_label(s: str) -> bool:
    t = (s or "").strip()
    if len(t) < 4:
        return False
    collapsed = re.sub(r"\s+", " ", t.lower())
    # Exact placeholders and common LLM refusals / typos ("unlabbelled", etc.)
    if re.search(r"unlabe+l+ed\s+cluster", collapsed):
        return False
    bad = {
        "no excerpts in cluster",
        "empty cluster",
        "n/a",
        "unknown",
        "unable to label",
        "unable to summarize",
        "unable to summarise",
    }
    if collapsed.rstrip(".") in bad or collapsed in bad:
        return False
    return True


def default_label_model() -> str:
    return (
        os.environ.get("OLLAMA_CLUSTER_LABEL_MODEL")
        or os.environ.get("OLLAMA_IMPACT_MODEL")
        or os.environ.get("OLLAMA_NARRATIVE_MODEL")
        or _DEFAULT_CLUSTER_LABEL_MODEL
    ).strip()


def _ollama_chat_label(
    excerpts: str,
    *,
    model: str,
    base_url: str,
    timeout: float,
) -> str:
    """One non-streaming /api/chat call; returns cleaned label text or "" if unusable."""
    if not excerpts.strip():
        return ""
    system = (
        "You read numbered news excerpts from the same semantic cluster (similar embeddings). "
        "Write ONE short neutral label: 8–18 words, wire-service tone, naming the shared theme "
        "(sectors, companies, policy, or story thread). No quotes, bullets, preamble, or markdown. "
        "Output only the label sentence, nothing else."
    )
    user = f"EXCERPTS:\n\n{excerpts}\n\nLabel only:"
    url = f"{base_url.rstrip('/')}/api/chat"
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # Enough tokens for models that spend budget on internal reasoning before the label.
        "options": {"temperature": 0.25, "num_predict": 512},
    }
    # Ollama 0.6+: disable extended thinking when supported (ignored on older servers).
    payload["think"] = False

    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        body = r.json()
    raw = _extract_ollama_chat_content(body)
    cleaned = _clean_llm_label(raw)
    if not cleaned.strip() and (raw or "").strip():
        logger.warning(
            "[embedding_clusters] Ollama label cleaned to empty model=%s keys=%s raw_head=%r",
            model,
            list(body.keys()) if isinstance(body, dict) else type(body),
            (raw or "")[:400],
        )
    elif not cleaned.strip():
        logger.warning(
            "[embedding_clusters] Ollama returned empty content model=%s keys=%s",
            model,
            list(body.keys()) if isinstance(body, dict) else type(body),
        )
    return cleaned


def _build_cluster_excerpts(cluster_chunks: list[ChunkRow], max_chars: int) -> str:
    blocks: list[str] = []
    used = 0
    for i, c in enumerate(cluster_chunks):
        t = _safe_reverse_text(c.chunk_text).strip()
        if not t:
            continue
        line = f"[{i + 1}] (article {c.article_id}) {t}"
        if used + len(line) + 1 > max_chars:
            break
        blocks.append(line)
        used += len(line) + 1
    return "\n".join(blocks)


def _nearest_chunk_in_subcluster(
    centroid: np.ndarray,
    cluster_chunks: list[ChunkRow],
) -> tuple[int | None, int | None]:
    if not cluster_chunks:
        return None, None
    cen = normalize(np.asarray(centroid, dtype=np.float64).reshape(1, -1), norm="l2", axis=1)[0]
    C = np.stack([c.embedding for c in cluster_chunks], axis=0)
    Cn = normalize(C, norm="l2", axis=1)
    i = int(np.argmax(cen @ Cn.T))
    ch = cluster_chunks[i]
    return ch.article_id, ch.chunk_index


def _fallback_chunk_text(
    cluster_chunks: list[ChunkRow],
    centroid: np.ndarray,
    *,
    cluster_index: int,
) -> str:
    if not cluster_chunks:
        return f"empty cluster (index {cluster_index})"
    try:
        ra, rc = _nearest_chunk_in_subcluster(centroid, cluster_chunks)
        for c in cluster_chunks:
            if c.article_id == ra and c.chunk_index == rc:
                t = _safe_reverse_text(c.chunk_text).strip()
                if t:
                    return t[:2000]
    except Exception:
        pass
    for c in cluster_chunks:
        t = _safe_reverse_text(c.chunk_text).strip()
        if t:
            return t[:2000]
    return (
        f"Cluster {cluster_index}: {len(cluster_chunks)} chunks in DB "
        f"(chunk_text empty — check news_article_embeddings.chunk_text)"
    )


def ollama_labels_per_cluster(
    chunks: list[ChunkRow],
    article_ids: list[int],
    labels: np.ndarray,
    centroids: np.ndarray,
    *,
    label_model: str,
    ollama_base_url: str,
    ollama_timeout: float,
    max_cluster_prompt_chars: int,
) -> list[tuple[str, int | None, int | None]]:
    """
    For each cluster index: Ollama label from member chunks; provenance = nearest chunk
    to centroid within that cluster.
    """
    aid_to_cluster = {int(a): int(l) for a, l in zip(article_ids, labels)}
    by_cluster: dict[int, list[ChunkRow]] = defaultdict(list)
    for c in chunks:
        cl = aid_to_cluster.get(c.article_id)
        if cl is None:
            continue
        by_cluster[cl].append(c)

    k = int(centroids.shape[0])
    out: list[tuple[str, int | None, int | None]] = []
    for j in range(k):
        cluster_chunks = by_cluster.get(j, [])
        excerpts = _build_cluster_excerpts(cluster_chunks, max_cluster_prompt_chars)
        cen_j = np.asarray(centroids[j], dtype=np.float64).flatten()
        rep_a, rep_c = _nearest_chunk_in_subcluster(cen_j, cluster_chunks)
        text = ""
        if excerpts.strip():
            try:
                text = _ollama_chat_label(
                    excerpts,
                    model=label_model,
                    base_url=ollama_base_url,
                    timeout=ollama_timeout,
                )
            except Exception as exc:
                logger.warning(
                    "[embedding_clusters] Ollama label failed cluster_index=%s model=%s: %s",
                    j,
                    label_model,
                    exc,
                )
                text = ""
        if not _is_usable_cluster_label(text):
            fb = _fallback_chunk_text(cluster_chunks, cen_j, cluster_index=j)
            if (text or "").strip():
                logger.info(
                    "[embedding_clusters] cluster_index=%s replacing weak LLM label %r with chunk fallback",
                    j,
                    (text or "")[:160],
                )
            text = fb
        out.append((_safe_reverse_text(text), rep_a, rep_c))
    return out


def fetch_bucket_chunks(
    schema: str,
    embedding_model: str,
    bucket_start: datetime,
    bucket_end: datetime,
) -> list[ChunkRow]:
    conn = get_pg_connection()
    out: list[ChunkRow] = []
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT article_id, chunk_index, embedding::text, chunk_text
            FROM {schema}.news_article_embeddings
            WHERE embedding_model = %s
              AND published_at IS NOT NULL
              AND published_at >= %s
              AND published_at < %s
            """,
            (embedding_model, bucket_start, bucket_end),
        )
        for aid, cidx, etxt, ctext in cur.fetchall() or []:
            arr = _parse_vector_text(str(etxt or ""))
            if arr.size == 0:
                continue
            out.append(
                ChunkRow(
                    article_id=int(aid),
                    chunk_index=int(cidx),
                    embedding=arr,
                    chunk_text=str(ctext or ""),
                ),
            )
    finally:
        conn.close()
    return out


def mean_pool_by_article(chunks: list[ChunkRow]) -> tuple[np.ndarray, list[int]]:
    """Return X (n_articles, dim) and article_ids in stable sorted order."""
    if not chunks:
        return np.zeros((0, 0), dtype=np.float64), []
    by: dict[int, list[np.ndarray]] = defaultdict(list)
    dim = chunks[0].embedding.shape[0]
    for c in chunks:
        v = c.embedding
        if v.shape[0] != dim:
            logger.warning(
                "[embedding_clusters] skip article_id=%s chunk=%s dim=%s expected=%s",
                c.article_id,
                c.chunk_index,
                v.shape[0],
                dim,
            )
            continue
        by[c.article_id].append(v)
    aids = sorted(by.keys())
    mats: list[np.ndarray] = []
    for aid in aids:
        stacked = np.stack(by[aid], axis=0)
        mats.append(np.mean(stacked, axis=0))
    return np.stack(mats, axis=0), aids


def run_one_bucket(
    bucket: Bucket,
    *,
    embedding_model: str,
    max_k: int,
    min_per_cluster: int,
    random_state: int,
    dry_run: bool,
    label_model: str,
    ollama_base_url: str,
    ollama_timeout: float,
    max_cluster_prompt_chars: int,
) -> dict:
    schema = _SCHEMA
    runs_t, centroids_t, articles_t = _cluster_tables(bucket.granularity)

    chunks = fetch_bucket_chunks(schema, embedding_model, bucket.start, bucket.end)
    X_raw, article_ids = mean_pool_by_article(chunks)

    n_chunks = len(chunks)
    n_art = X_raw.shape[0]
    embedding_dim = int(X_raw.shape[1]) if n_art else 0

    if n_art == 0:
        return {
            "bucket": bucket.start.isoformat(),
            "granularity": bucket.granularity,
            "skipped": True,
            "reason": "no_embeddings",
            "chunk_rows": 0,
            "articles": 0,
        }

    k = pick_n_clusters(n_art, max_k=max_k, min_per_cluster=min_per_cluster)
    X = normalize(X_raw, norm="l2", axis=1)
    if dry_run:
        return {
            "bucket": bucket.start.isoformat(),
            "granularity": bucket.granularity,
            "dry_run": True,
            "chunk_rows": n_chunks,
            "articles": n_art,
            "n_clusters": k,
            "embedding_dim": embedding_dim,
            "label_model": label_model,
        }

    km = MiniBatchKMeans(
        n_clusters=k,
        random_state=random_state,
        batch_size=min(256, max(32, n_art)),
        n_init="auto",
    )
    labels = km.fit_predict(X)
    centers = km.cluster_centers_
    reverse_meta = ollama_labels_per_cluster(
        chunks,
        article_ids,
        np.asarray(labels, dtype=np.int32),
        np.asarray(centers, dtype=np.float64),
        label_model=label_model,
        ollama_base_url=ollama_base_url,
        ollama_timeout=ollama_timeout,
        max_cluster_prompt_chars=max_cluster_prompt_chars,
    )

    member_counts = np.bincount(labels, minlength=k).astype(int)

    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            DELETE FROM {schema}.{runs_t}
            WHERE bucket_start = %s AND embedding_model = %s
            """,
            (bucket.start, embedding_model),
        )
        cur.execute(
            f"""
            INSERT INTO {schema}.{runs_t}
              (bucket_start, embedding_model, n_clusters, article_count, chunk_rows_used,
               embedding_dim, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                bucket.start,
                embedding_model,
                int(k),
                int(n_art),
                int(n_chunks),
                int(embedding_dim),
            ),
        )

        for j in range(k):
            cen = np.asarray(centers[j], dtype=np.float64).flatten()
            rev_text, rev_aid, rev_cidx = reverse_meta[j]
            mcount = int(member_counts[j]) if j < len(member_counts) else 0
            cur.execute(
                f"""
                INSERT INTO {schema}.{centroids_t}
                  (bucket_start, embedding_model, cluster_index, centroid, reverse_embedding_text,
                   reverse_embedding_article_id, reverse_embedding_chunk_index, member_count, computed_at)
                VALUES (%s, %s, %s, %s::double precision[], %s, %s, %s, %s, NOW())
                """,
                (
                    bucket.start,
                    embedding_model,
                    int(j),
                    [float(x) for x in cen.tolist()],
                    rev_text,
                    rev_aid,
                    rev_cidx,
                    mcount,
                ),
            )

        batch = [
            (bucket.start, embedding_model, int(aid), int(lab))
            for aid, lab in zip(article_ids, labels)
        ]
        cur.executemany(
            f"""
            INSERT INTO {schema}.{articles_t}
              (bucket_start, embedding_model, article_id, cluster_index, computed_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            batch,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "bucket": bucket.start.isoformat(),
        "granularity": bucket.granularity,
        "tables": {"runs": runs_t, "centroids": centroids_t, "articles": articles_t},
        "chunk_rows": n_chunks,
        "articles": n_art,
        "n_clusters": k,
        "embedding_dim": embedding_dim,
        "written": len(article_ids),
        "label_model": label_model,
    }


def run_range(
    granularity: str,
    since: datetime,
    until: datetime,
    *,
    embedding_model: str,
    max_k: int,
    min_per_cluster: int,
    random_state: int,
    dry_run: bool,
    label_model: str,
    ollama_base_url: str,
    ollama_timeout: float,
    max_cluster_prompt_chars: int,
) -> list[dict]:
    results: list[dict] = []
    for bucket in iter_buckets(granularity, since, until):
        res = run_one_bucket(
            bucket,
            embedding_model=embedding_model,
            max_k=max_k,
            min_per_cluster=min_per_cluster,
            random_state=random_state,
            dry_run=dry_run,
            label_model=label_model,
            ollama_base_url=ollama_base_url,
            ollama_timeout=ollama_timeout,
            max_cluster_prompt_chars=max_cluster_prompt_chars,
        )
        logger.info("[embedding_clusters] %s %s %s", bucket.granularity, bucket.start.isoformat(), res)
        results.append(res)
    return results


def parse_iso_datetime(s: str) -> datetime:
    s = s.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def run_cli(
    *,
    granularity: str,
    since: str,
    until: str | None,
    embedding_model: str | None,
    max_k: int,
    min_per_cluster: int,
    random_state: int,
    dry_run: bool,
    label_model: str | None = None,
    ollama_base_url: str | None = None,
    ollama_timeout: float = 120.0,
    max_cluster_prompt_chars: int = 14_000,
) -> list[dict]:
    g = granularity.lower().strip()
    since_dt = parse_iso_datetime(since)
    until_dt = parse_iso_datetime(until) if until else datetime.now(timezone.utc)
    model = (embedding_model or os.environ.get("OLLAMA_EMBED_MODEL") or "mxbai-embed-large").strip()
    lm = (label_model or default_label_model()).strip()
    base = (ollama_base_url or os.environ.get("OLLAMA_BASE_URL") or _DEFAULT_OLLAMA_BASE).strip()
    return run_range(
        g,
        since_dt,
        until_dt,
        embedding_model=model,
        max_k=max_k,
        min_per_cluster=min_per_cluster,
        random_state=random_state,
        dry_run=dry_run,
        label_model=lm,
        ollama_base_url=base,
        ollama_timeout=float(ollama_timeout),
        max_cluster_prompt_chars=int(max_cluster_prompt_chars),
    )
