"""Which of the 5,810 NYSE + NASDAQ names this analysis can actually be run on.

The reconstruction is not a screen that returns a score for anything you point
it at. It needs a **spread of published analyst models** — that is the grounded
tier, the only part of the output that is arithmetic on other people's numbers
rather than a judgement — and it needs **news coverage**, because the corpus is
what tells it which arguments are already circulating. A name with neither
produces a row that looks like the others and means nothing.

So eligibility is a real gate with a measured cost, and it is applied in two
stages because the two stages cost different amounts:

**Stage 1 — free, from Supabase.** `swingtrader.tickers` already holds the
actively-traded NYSE + NASDAQ universe (it is seeded from the same FMP
company-screener endpoint), and `ticker_coverage_daily` already holds the daily
mention rollup that the /quote directory reads. Joining them costs one query and
eliminates most of the universe: of 5,810 names, ~3,400 clear a $300m / $5
floor, and only ~630 of those also carry enough news to retrieve against.

**Stage 2 — one FMP call each.** Whether five or more analysts have published a
target in the last 120 days. This is the gate the UI itself applies before it
will draw the distribution, so a name that fails it can never produce a visible
row, and the cheapest place to find that out is here rather than four LLM calls
later.

The verdict is cached WITH its evidence. `n_targets` next to `eligible=false` is
what distinguishes a name that will never qualify from one that is two targets
short and worth re-checking after the next results season — and re-checking
everything every pass would spend the whole FMP budget on names that will never
produce a row.

**Priority** orders the queue and is deliberately dull: news mentions first,
size second. Mentions rather than size because the corpus is the binding
constraint on quality — a mega-cap nobody wrote about reconstructs worse than a
mid-cap that is in the news every week — and both are logged, so neither runs
away with the ordering.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

# The floor the UI itself applies before it will draw the model distribution
# (`code/ui/lib/quote/priced-in.ts`). Below it there is no vote to read, only a
# handful of stale numbers, so there is no point spending four LLM calls to
# find out. Changing this without changing the UI produces rows nothing renders.
MIN_TARGETS = 5

# Stage-1 floor. Not a view on what is investable — a statement about what the
# corpus and the sell-side actually cover, and that is now the ONLY thing the
# floor measures.
#
# There were two size floors here as well: a $300m market cap and a $5 share
# price. Both are gone, and the reason is that they answered a different
# question from the one this programme asks. The whole construction reads a
# price as a VOTE among published analyst models, checked against what the news
# corpus says. A name qualifies for that if the sell-side has published enough
# models to make a distribution and the press writes about it enough to check
# them against — whether it is worth $200m or $2tn says nothing about either.
#
# The floors also cost more than they looked like they cost. They rejected 78
# names that clear the coverage floor, among them CS Disco at 332 mentions over
# 180 days, Amtech at 265 and Embecta at 126 — small companies the news demonstrably
# cares about, which is the exact population this analysis is for. Dropping both
# admits 1,110 stage-1 candidates where 1,032 got through before: 78 further FMP
# calls, once, against a rate-limited stage that already budgets 250 a pass.
#
# Market cap is still recorded on the row. It is context for a reader, not a gate.
MIN_MARKET_CAP = 0
MIN_PRICE = 0.0

# Calibrated against the fifteen names the programme was developed on, not
# chosen. At 20 the floor excluded CROX — which has 19 mentions over 180 days
# and is the single ticker every stage of this pipeline was built and debugged
# against, and whose reconstruction is the worked example in
# research/PRICED-IN-FINDINGS.md. A floor that rejects the development set is
# measuring the wrong thing, so it sits below the set's minimum with room for a
# name whose coverage dips between passes.
#
# The cost is real and is the reason this is written down: 12 admits ~1,040
# candidates where 20 admitted ~630, and stage 2 is one FMP call each.
DEVELOPMENT_SET_MIN_MENTIONS = 19        # CROX, the sparsest known-good name
MIN_MENTIONS_180D = 12

# How long an eligibility verdict is trusted. Analyst coverage changes on the
# earnings cycle, so a quarter is the natural period; a near-miss is re-checked
# sooner because it is the one most likely to have flipped.
RECHECK_DAYS = 90
NEAR_MISS_RECHECK_DAYS = 30

# A name that keeps failing is not retried nightly. The backoff is per
# consecutive failure and capped, because most repeat failures are structural
# (no transcript, a thin corpus) and will still be structural tomorrow.
COOLDOWN_DAYS = (1, 3, 7, 21, 60)


def cooldown_for(consecutive_failures: int) -> int:
    i = min(max(consecutive_failures, 1), len(COOLDOWN_DAYS)) - 1
    return COOLDOWN_DAYS[i]


def priority_of(mentions_180d: int | None, n_targets: int | None = None) -> float:
    """Rank the queue by who is paying attention: the press, then the sell-side.

    Size used to be the second term, at 0.5 x log10(market cap). Dropping it from
    eligibility and leaving it in the ordering would have moved the same bias
    rather than removed it — a queue drained a few dozen names a night puts a
    small company behind every large one, which is a floor with extra steps.

    Both terms are logged. Mention counts span three orders of magnitude across
    the universe, so on raw values a single heavily-covered name would outrank
    every other consideration. Analyst coverage is the lighter term because it
    is close to binary in effect: the run needs MIN_TARGETS models and a name
    with thirty is not three times more worth running than one with ten.

    `n_targets` is unknown until stage 2 has made its FMP call, and None
    contributes nothing — a name is ordered on its coverage until the sell-side
    count is actually known, never on a guess at it.
    """
    m = math.log10(max(mentions_180d or 0, 1) + 1)
    t = math.log10(max(n_targets or 0, 1) + 1)
    return round(2.0 * m + 0.5 * t, 4)


# ----------------------------------------------------------------------
SEED_SQL = """
WITH cov AS (
    SELECT ticker, sum(mention_count) AS mentions
    FROM {schema}.ticker_coverage_daily
    WHERE bucket_day >= CURRENT_DATE - %s
    GROUP BY ticker
)
SELECT t.symbol, t.exchange, t.company_name, t.market_cap, t.price,
       COALESCE(c.mentions, 0) AS mentions
FROM {schema}.tickers t
LEFT JOIN cov c ON c.ticker = t.symbol
WHERE t.is_actively_trading
  AND t.exchange IS NOT NULL
  AND (t.exchange ILIKE '%%NEW YORK STOCK EXCHANGE%%'
       OR t.exchange ILIKE '%%NASDAQ%%')
"""


def seed(publisher, *, lookback_days: int = 180,
         min_market_cap: int = MIN_MARKET_CAP, min_price: float = MIN_PRICE,
         min_mentions: int = MIN_MENTIONS_180D) -> dict:
    """Stage 1. Refresh the universe table from what Supabase already knows.

    Coverage is the only thing this stage judges. `min_market_cap` and
    `min_price` default to nothing and are kept as parameters so a caller can
    still bound an exploratory pass by hand; the scheduled path passes neither.

    Names below the floor are written as `eligible = false` rather than left
    out, so the table is a complete account of the universe and its verdicts.
    A name that later crosses the floor is picked up on the next seed, because
    the coverage figures are refreshed on every pass — which is also how the
    2,211 names currently carrying a market-cap rejection get their verdict
    cleared: stage 1 re-seeds them with no reason, `checked_at IS NULL` sends
    them back to NULL rather than a stale false, and stage 2 decides on targets.
    """
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        cur.execute(SEED_SQL.format(schema=schema), (lookback_days,))
        rows = cur.fetchall()

    stats = {"scanned": len(rows), "candidates": 0, "below_floor": 0,
             "nyse": 0, "nasdaq": 0}
    payload = []
    for symbol, exchange, name, mcap, price, mentions in rows:
        ex = (exchange or "").upper()
        if "NASDAQ" in ex:
            stats["nasdaq"] += 1
        else:
            stats["nyse"] += 1
        below = []
        # Both size tests are inert at their defaults and stay only for a
        # hand-bounded pass. Nothing scheduled passes them.
        if min_market_cap and (mcap or 0) < min_market_cap:
            below.append(f"market cap ${(mcap or 0)/1e6:,.0f}m < "
                         f"${min_market_cap/1e6:,.0f}m")
        if min_price and (price or 0) < min_price:
            below.append(f"price ${price or 0:,.2f} < ${min_price:,.2f}")
        if (mentions or 0) < min_mentions:
            below.append(f"{mentions or 0} mentions in {lookback_days}d < "
                         f"{min_mentions}")
        if below:
            stats["below_floor"] += 1
            payload.append((symbol, exchange, name, mcap, mentions, False,
                            "; ".join(below), 0.0))
        else:
            stats["candidates"] += 1
            payload.append((symbol, exchange, name, mcap, mentions, None, None,
                            priority_of(mentions)))

    with c.cursor() as cur:
        for row in payload:
            cur.execute(f"""
                INSERT INTO {schema}.research_priced_in_universe
                  (symbol, exchange, company_name, market_cap, mentions_180d,
                   eligible, reason, priority, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (symbol) DO UPDATE SET
                  exchange = EXCLUDED.exchange,
                  company_name = EXCLUDED.company_name,
                  market_cap = EXCLUDED.market_cap,
                  mentions_180d = EXCLUDED.mentions_180d,
                  priority = EXCLUDED.priority,
                  updated_at = now(),
                  -- A stage-1 verdict never overwrites a stage-2 one. Only the
                  -- FMP check can say a name IS eligible, and only it can say a
                  -- name that cleared the floor is not; what stage 1 may do is
                  -- demote a name that has since fallen below the floor.
                  --
                  -- The middle case is the one that bit: a name that NOW clears
                  -- the floor but was rejected by stage 1 before — because its
                  -- coverage grew, or because the floor itself was recalibrated
                  -- — kept its stale `false` and was therefore never sent for a
                  -- stage-2 check. It could not become eligible by any path.
                  -- Lowering the coverage floor admitted 411 such names and
                  -- changed nothing, silently, which is the worst way for a
                  -- config change to fail. `checked_at IS NULL` is what makes
                  -- this safe: a verdict the FMP check produced is never reset.
                  eligible = CASE
                      WHEN EXCLUDED.eligible IS FALSE THEN FALSE
                      WHEN {schema}.research_priced_in_universe.checked_at IS NULL
                          THEN NULL
                      ELSE {schema}.research_priced_in_universe.eligible END,
                  reason = CASE
                      WHEN EXCLUDED.eligible IS FALSE THEN EXCLUDED.reason
                      WHEN {schema}.research_priced_in_universe.checked_at IS NULL
                          THEN NULL
                      ELSE {schema}.research_priced_in_universe.reason END
            """, row)
    c.commit()
    return stats


# ----------------------------------------------------------------------
def _needs_check(checked_at, eligible, n_targets, today: date) -> bool:
    if checked_at is None:
        return True
    age = (today - checked_at.date()).days if isinstance(checked_at, datetime) \
        else (today - checked_at).days
    if eligible:
        return age >= RECHECK_DAYS
    # A name two targets short is the one most likely to have flipped, so it is
    # re-checked on a shorter cycle than one with no coverage at all.
    near = n_targets is not None and n_targets >= MIN_TARGETS - 2
    return age >= (NEAR_MISS_RECHECK_DAYS if near else RECHECK_DAYS)


def check_eligibility(publisher, *, limit: int = 250,
                      symbols: list[str] | None = None,
                      min_targets: int = MIN_TARGETS) -> dict:
    """Stage 2. One FMP call per name: does the sell-side cover it enough?

    Bounded by `limit` because this is the rate-limited half. Names are taken in
    priority order, so a budget that does not cover the whole universe still
    spends itself on the names most worth having.
    """
    from .analyst import targets as fetch_targets

    schema = publisher.schema
    today = date.today()
    c = publisher._connect()
    with c.cursor() as cur:
        if symbols:
            cur.execute(f"""
                SELECT symbol, checked_at, eligible, n_targets, mentions_180d
                FROM {schema}.research_priced_in_universe
                WHERE symbol = ANY(%s)
            """, ([s.upper() for s in symbols],))
        else:
            cur.execute(f"""
                SELECT symbol, checked_at, eligible, n_targets, mentions_180d
                FROM {schema}.research_priced_in_universe
                WHERE reason IS NULL OR eligible IS NOT FALSE
                   OR checked_at IS NOT NULL
                ORDER BY priority DESC
            """)
        rows = cur.fetchall()

    # Names below the stage-1 floor carry a reason and priority 0; they are not
    # worth an FMP call. `symbols` overrides that, so a name can be checked by
    # hand regardless.
    due = [r for r in rows
           if (symbols or r[3] is not None or r[2] is not False)
           and _needs_check(r[1], r[2], r[3], today)][:limit]

    out = {"considered": len(rows), "checked": 0, "eligible": 0,
           "ineligible": 0, "errors": 0}
    for symbol, _checked, _elig, _n, _mentions in due:
        try:
            n = len(fetch_targets(symbol))
        except Exception as exc:                              # noqa: BLE001
            log.info("%s: target check failed — %s", symbol, exc)
            out["errors"] += 1
            continue
        ok = n >= min_targets
        reason = "" if ok else (f"{n} published targets in the last 120 days, "
                                f"below the {min_targets} the model "
                                f"distribution needs")
        with c.cursor() as cur:
            # Priority is recomputed here because this is the moment the
            # sell-side count stops being unknown. Leaving it at the seed's
            # coverage-only value would order the queue on half the evidence for
            # the rest of the quarter.
            cur.execute(f"""
                UPDATE {schema}.research_priced_in_universe
                SET eligible=%s, reason=%s, n_targets=%s, checked_at=now(),
                    updated_at=now(), priority=%s,
                    last_run_status = CASE WHEN %s THEN last_run_status
                                           ELSE 'ineligible' END
                WHERE symbol=%s
            """, (ok, reason or None, n,
                  priority_of(_mentions, n), ok, symbol))
        c.commit()
        out["checked"] += 1
        out["eligible" if ok else "ineligible"] += 1
    return out


# ----------------------------------------------------------------------
def queue(publisher, *, limit: int = 25, due_days: int = 7,
          symbols: list[str] | None = None) -> list[dict]:
    """The next names to run, highest priority first.

    `due_days` is what makes this a refresh cycle rather than a race: a name run
    within the window is not re-run, so a batch that is interrupted and restarted
    picks up where it left off instead of starting the list again.
    """
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        if symbols:
            cur.execute(f"""
                SELECT symbol, company_name, priority, n_targets, mentions_180d,
                       days_since_run, last_run_status, last_as_of, last_published
                FROM {schema}.research_priced_in_queue_v
                WHERE symbol = ANY(%s)
                ORDER BY priority DESC
            """, ([s.upper() for s in symbols],))
        else:
            cur.execute(f"""
                SELECT symbol, company_name, priority, n_targets, mentions_180d,
                       days_since_run, last_run_status, last_as_of, last_published
                FROM {schema}.research_priced_in_queue_v
                WHERE days_since_run >= %s
                ORDER BY priority DESC, days_since_run DESC
                LIMIT %s
            """, (due_days, limit))
        cols = ["symbol", "company_name", "priority", "n_targets",
                "mentions_180d", "days_since_run", "last_run_status",
                "last_as_of", "last_published"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def record_run(publisher, symbol: str, status: str, error: str = "") -> None:
    """Mark one attempt. Failures accumulate into a cooldown; success clears it."""
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        if status == "ok":
            cur.execute(f"""
                UPDATE {schema}.research_priced_in_universe
                SET last_run_at=now(), last_run_status='ok', last_error=NULL,
                    consecutive_failures=0, cooldown_until=NULL,
                    runs=runs+1, updated_at=now()
                WHERE symbol=%s
            """, (symbol,))
        else:
            cur.execute(f"""
                UPDATE {schema}.research_priced_in_universe
                SET last_run_at=now(), last_run_status=%s, last_error=%s,
                    consecutive_failures=consecutive_failures+1,
                    runs=runs+1, updated_at=now()
                WHERE symbol=%s
                RETURNING consecutive_failures
            """, (status, (error or "")[:500], symbol))
            row = cur.fetchone()
            n = row[0] if row else 1
            cur.execute(f"""
                UPDATE {schema}.research_priced_in_universe
                SET cooldown_until=%s WHERE symbol=%s
            """, (date.today() + timedelta(days=cooldown_for(n)), symbol))
    c.commit()


def stats(publisher) -> dict:
    schema = publisher.schema
    c = publisher._connect()
    with c.cursor() as cur:
        cur.execute(f"""
            SELECT count(*),
                   count(*) FILTER (WHERE eligible),
                   count(*) FILTER (WHERE eligible IS FALSE),
                   count(*) FILTER (WHERE eligible IS NULL),
                   count(*) FILTER (WHERE eligible AND last_run_at IS NOT NULL),
                   count(*) FILTER (WHERE cooldown_until > CURRENT_DATE)
            FROM {schema}.research_priced_in_universe
        """)
        n, elig, inelig, unknown, run, cooling = cur.fetchone()
    return {"universe": int(n), "eligible": int(elig),
            "ineligible": int(inelig), "unchecked": int(unknown),
            "ever_run": int(run), "in_cooldown": int(cooling)}
