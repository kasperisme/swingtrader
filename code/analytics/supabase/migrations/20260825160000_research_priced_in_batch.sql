-- ---------------------------------------------------------------------------
-- Running the priced-in programme on a schedule, across NYSE + NASDAQ.
--
-- The programme was built as a hand-run pipeline over fifteen chosen tickers.
-- Everything it needs to run unattended over the whole universe is bookkeeping,
-- and bookkeeping has to live where the run can be resumed from — which is not
-- the machine that happened to start it.
--
-- Three tables, and each exists because of something a scheduled run does that
-- a hand-run one does not:
--
--   1. research_priced_in_universe — WHICH tickers, and when each is next due.
--      The universe is 5,810 names and most of them cannot be analysed at all:
--      the reconstruction needs at least five published analyst models, and
--      finding that out costs an FMP call. Re-discovering it every pass would
--      spend the entire rate limit on names that will never produce a row, so
--      eligibility is cached with the evidence for the verdict and re-checked
--      on a slow cycle.
--
--   2. research_priced_in_runs — what one batch pass did. A scheduled job that
--      reports only success or failure is unauditable; when a pass produces
--      forty rows instead of four hundred, the question is always which names
--      it skipped and why, and that has to have been written down at the time.
--
--   3. research_prediction_events — the ledger's append-only log, which moves
--      here with the ledger itself.
--
-- Why the ledger moves at all: `predictions.db` was a local SQLite file
-- declared as the source of truth, with Supabase as a mirror. That is a
-- defensible arrangement for a researcher at one desk and an untenable one for
-- a scheduled job — the first run on another machine starts from an empty
-- ledger and re-registers predictions that already exist, which is exactly the
-- record-keeping failure Tier 3 was built to make impossible. Supabase already
-- holds the immutability trigger, so it is the stricter home as well as the
-- durable one. The lock is a content hash, so the move is a no-op for any row
-- that was already mirrored: it re-derives to the same primary key.
-- ---------------------------------------------------------------------------

-- 1) The working universe and its schedule.
CREATE TABLE IF NOT EXISTS swingtrader.research_priced_in_universe (
    symbol            text PRIMARY KEY,
    exchange          text,
    company_name      text,
    market_cap        bigint,
    -- Eligibility, cached WITH its evidence. `reason` is not decoration: the
    -- most common outcome by far is "not enough published models", and without
    -- the count recorded next to it there is no way to tell a name that will
    -- never qualify from one that is two targets short.
    eligible          boolean,
    reason            text,
    n_targets         integer,
    mentions_180d     bigint,
    checked_at        timestamptz,
    -- Scheduling. `priority` orders the queue; `cooldown_until` is what keeps a
    -- name that fails for a structural reason from being retried every night.
    priority          double precision NOT NULL DEFAULT 0,
    last_run_at       timestamptz,
    last_run_status   text CHECK (last_run_status IN
                                  ('ok','failed','skipped','ineligible')),
    last_error        text,
    consecutive_failures integer NOT NULL DEFAULT 0,
    cooldown_until    date,
    runs              integer NOT NULL DEFAULT 0,
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- The queue query: eligible, off cooldown, highest priority first.
CREATE INDEX IF NOT EXISTS ix_priced_in_universe_queue
    ON swingtrader.research_priced_in_universe (priority DESC, last_run_at ASC)
    WHERE eligible;
CREATE INDEX IF NOT EXISTS ix_priced_in_universe_recheck
    ON swingtrader.research_priced_in_universe (checked_at);

-- 2) One row per batch pass.
CREATE TABLE IF NOT EXISTS swingtrader.research_priced_in_runs (
    id                bigserial PRIMARY KEY,
    started_at        timestamptz NOT NULL DEFAULT now(),
    ended_at          timestamptz,
    backend           text,
    models            text,
    pipeline_version  text,
    attempted         integer NOT NULL DEFAULT 0,
    succeeded         integer NOT NULL DEFAULT 0,
    failed            integer NOT NULL DEFAULT 0,
    published         integer NOT NULL DEFAULT 0,
    held              integer NOT NULL DEFAULT 0,
    predictions_registered integer NOT NULL DEFAULT 0,
    -- Per-model call counts, failures and latency. The chain exists so that a
    -- degraded model is survivable, which means a run summary that does not say
    -- which model answered hides the degradation it was designed to absorb.
    usage_json        jsonb NOT NULL DEFAULT '{}'::jsonb,
    stop_reason       text,
    detail            text
);

CREATE INDEX IF NOT EXISTS ix_priced_in_runs_started
    ON swingtrader.research_priced_in_runs (started_at DESC);

-- 3) The ledger's log, moved with the ledger.
CREATE TABLE IF NOT EXISTS swingtrader.research_prediction_events (
    id                bigserial PRIMARY KEY,
    at                timestamptz NOT NULL DEFAULT now(),
    kind              text NOT NULL,
    lock              text,
    payload           jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_prediction_events_at
    ON swingtrader.research_prediction_events (at DESC);

-- 4) What the batch runner asks for: the next names due.
--
--    Kept as a view so the ordering rule is stated once, in the database,
--    rather than reimplemented in whichever process happens to be draining the
--    queue. `due_days` is a parameter of the caller, so the view exposes the
--    age and lets the caller threshold it.
CREATE OR REPLACE VIEW swingtrader.research_priced_in_queue_v AS
SELECT u.symbol, u.exchange, u.company_name, u.market_cap, u.n_targets,
       u.mentions_180d, u.priority, u.last_run_at, u.last_run_status,
       u.consecutive_failures, u.cooldown_until,
       p.as_of              AS last_as_of,
       p.published          AS last_published,
       EXTRACT(day FROM now() - COALESCE(u.last_run_at,
                                         '2000-01-01'::timestamptz))::int
                            AS days_since_run
FROM swingtrader.research_priced_in_universe u
LEFT JOIN LATERAL (
    SELECT r.as_of, r.published
    FROM swingtrader.research_priced_in r
    WHERE r.ticker = u.symbol
    ORDER BY r.as_of DESC, r.created_at DESC
    LIMIT 1
) p ON true
WHERE u.eligible
  AND (u.cooldown_until IS NULL OR u.cooldown_until <= CURRENT_DATE);

-- 5) Access. The universe and the run log are operational, not editorial —
--    nothing here is public, matching the rest of the research_* family.
ALTER TABLE swingtrader.research_priced_in_universe ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.research_priced_in_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.research_prediction_events ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON
    swingtrader.research_priced_in_universe,
    swingtrader.research_priced_in_runs,
    swingtrader.research_prediction_events
    TO service_role;
GRANT SELECT ON swingtrader.research_priced_in_queue_v TO service_role;
GRANT USAGE, SELECT ON SEQUENCE
    swingtrader.research_priced_in_runs_id_seq,
    swingtrader.research_prediction_events_id_seq
    TO service_role;

-- 6) The publish gate needs to find the currently-published row for a ticker
--    cheaply, and the existing index is on (published, as_of) across all
--    tickers. At fifteen rows that was free; across the universe it is the
--    query the gate runs once per ticker per pass.
CREATE INDEX IF NOT EXISTS ix_research_priced_in_ticker_published
    ON swingtrader.research_priced_in (ticker, as_of DESC, created_at DESC)
    WHERE published;
