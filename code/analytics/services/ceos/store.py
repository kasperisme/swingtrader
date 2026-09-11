"""Reading the universe and writing `swingtrader.company_ceos`."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from psycopg2.extras import Json, execute_values

from services.ceos import names

# The fields a reader sees on the CEO page. market_cap is deliberately absent:
# it moves every session, and a lastmod that flips daily on a number drift is a
# lastmod search engines learn to ignore.
_HASHED = (
    "company_name", "sector", "industry", "country", "ceo_name", "ceo_title",
    "year_born", "title_since", "pay", "compensation", "executives",
)

_COLUMNS = (
    "symbol", "company_name", "exchange", "sector", "industry", "country", "market_cap",
    "ceo_name_raw", "ceo_name", "ceo_slug", "ceo_title", "year_born", "title_since",
    "pay", "currency_pay", "compensation", "executives", "content_hash",
)


def content_hash(row: dict) -> str:
    payload = json.dumps({k: row.get(k) for k in _HASHED}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def universe(conn, *, symbols: list[str] | None = None, limit: int | None = None,
             stale_days: float = 30) -> list[str]:
    """Actively-traded symbols, largest first, skipping rows fetched recently.

    Largest first because a partial run should cover the CEOs people search
    for; a 4,000th-by-market-cap micro-cap can wait for the next pass.
    """
    with conn.cursor() as cur:
        if symbols:
            return [s.upper() for s in symbols]
        cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
        cur.execute(
            """
            SELECT t.symbol
            FROM swingtrader.tickers t
            LEFT JOIN swingtrader.company_ceos c ON c.symbol = t.symbol
            WHERE COALESCE(t.is_actively_trading, true)
              AND (c.fetched_at IS NULL OR c.fetched_at < %s)
            GROUP BY t.symbol
            ORDER BY max(t.market_cap) DESC NULLS LAST
            LIMIT %s
            """,
            (cutoff, limit or 100_000),
        )
        return [r[0] for r in cur.fetchall()]


def upsert(conn, rows: list[dict]) -> int:
    """Write fetched rows. `ceo_slug` is provisional until `assign_slugs`."""
    if not rows:
        return 0
    values = []
    for r in rows:
        r = {**r, "ceo_slug": names.slugify(r["ceo_name"]), "content_hash": content_hash(r)}
        values.append(tuple(
            Json(r[c]) if c in ("compensation", "executives") else r.get(c) for c in _COLUMNS
        ))
    cols = ", ".join(_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO swingtrader.company_ceos ({cols}) VALUES %s
            ON CONFLICT (symbol) DO UPDATE SET
              company_name = EXCLUDED.company_name,
              exchange     = EXCLUDED.exchange,
              sector       = EXCLUDED.sector,
              industry     = EXCLUDED.industry,
              country      = EXCLUDED.country,
              market_cap   = EXCLUDED.market_cap,
              ceo_name_raw = EXCLUDED.ceo_name_raw,
              ceo_name     = EXCLUDED.ceo_name,
              -- keep an assigned (possibly suffixed) slug while the person is
              -- unchanged; assign_slugs reconciles the rest
              ceo_slug     = CASE WHEN company_ceos.ceo_name = EXCLUDED.ceo_name
                                  THEN company_ceos.ceo_slug ELSE EXCLUDED.ceo_slug END,
              ceo_title    = EXCLUDED.ceo_title,
              year_born    = EXCLUDED.year_born,
              title_since  = EXCLUDED.title_since,
              pay          = EXCLUDED.pay,
              currency_pay = EXCLUDED.currency_pay,
              compensation = EXCLUDED.compensation,
              executives   = EXCLUDED.executives,
              fetched_at   = now(),
              content_changed_at = CASE
                WHEN company_ceos.content_hash IS DISTINCT FROM EXCLUDED.content_hash
                THEN now() ELSE company_ceos.content_changed_at END,
              content_hash = EXCLUDED.content_hash
            """,
            values,
        )
    conn.commit()
    return len(rows)


def delete(conn, symbols: list[str]) -> int:
    """Drop rows for symbols FMP now names no CEO for — a dead link beats a wrong one."""
    if not symbols:
        return 0
    with conn.cursor() as cur:
        cur.execute("DELETE FROM swingtrader.company_ceos WHERE symbol = ANY(%s)", (symbols,))
        n = cur.rowcount
    conn.commit()
    return n


def assign_slugs(conn) -> int:
    """Reconcile `ceo_slug` across the whole table. Returns rows changed.

    Rows sharing a cleaned name are one person (GOOG + GOOGL) UNLESS their
    known birth years disagree; then every row in that name group gets a
    `-<symbol>` suffix. Merging two strangers would claim one runs the
    other's company — an uglier URL is the cheaper mistake.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, ceo_name, year_born, ceo_slug FROM swingtrader.company_ceos")
        rows = cur.fetchall()

    groups: dict[str, list[tuple]] = defaultdict(list)
    for sym, name, born, slug in rows:
        groups[names.slugify(name)].append((sym, born, slug))

    updates = []
    for base, members in groups.items():
        years = {b for _, b, _ in members if b}
        split = len(years) > 1
        for sym, _, current in members:
            want = f"{base}-{sym.lower().replace('.', '-')}" if split else base
            if want != current:
                updates.append((want, sym))

    if updates:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                UPDATE swingtrader.company_ceos c SET ceo_slug = v.slug
                FROM (VALUES %s) AS v(slug, symbol) WHERE c.symbol = v.symbol
                """,
                updates,
            )
        conn.commit()
    return len(updates)
