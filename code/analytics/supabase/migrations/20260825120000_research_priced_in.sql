-- ---------------------------------------------------------------------------
-- The priced-in programme: decompositions, and the forward predictions that
-- test them.
--
-- Extends the research_* family rather than starting a new one. The existing
-- tables already cover the write-up (research_notes), the claim and its
-- evidence (research_findings), the strategy (research_strategies) and the
-- campaign (research_campaigns). Two things in this programme fit none of them:
--
--   * a per-ticker, per-date reconstruction of what a price already contains,
--     which is an analysis OUTPUT rather than a claim, and
--   * a forward prediction that was SEALED before its outcome existed.
--
-- Why the prediction table is shaped the way it is:
--
-- Tiers 1 and 2 of this programme both failed retrospectively — the measurement
-- was designed after the data existed, so every degree of freedom in it could be
-- turned until something appeared, and three believable numbers were reported
-- before the bugs behind them were found. Tier 3 fixes the claim first, which
-- moves the engineering problem from statistics to record-keeping.
--
-- So `lock` is the primary key and it is a hash over the prediction's own
-- content. A row whose content no longer hashes to its lock was edited after the
-- fact, and `research_predictions_integrity_v` will show it. That is the single
-- property the whole tier rests on: without it, a forward prediction is just a
-- retrospective one with better manners.
--
-- The only legitimate mutation is resolution, and it happens once. The trigger
-- below enforces both halves — the sealed fields can never change, and an
-- outcome can never be overwritten. Re-running a resolver until it agrees is the
-- same failure mode in a new costume.
-- ---------------------------------------------------------------------------

-- 1) What a price already contains, reconstructed at a point in time.
CREATE TABLE IF NOT EXISTS swingtrader.research_priced_in (
    id                bigserial PRIMARY KEY,
    ticker            text NOT NULL,
    as_of             date NOT NULL,
    price             double precision,
    -- The reverse-DCF path. Correct arithmetic, fragile inputs: Crocs' implied
    -- CAGR moved nine points across three dates purely on which year's FCF
    -- margin anchored it, which is why the assumptions are stored beside it.
    implied_revenue_cagr  double precision,
    discount_rate     double precision,
    terminal_growth   double precision,
    fcf_margin        double precision,
    -- Where the price sits among published analyst models. This is the grounded
    -- tier: arithmetic on other people's numbers, no model judgement in it.
    n_targets         integer,
    target_low        double precision,
    target_high       double precision,
    target_median     double precision,
    median_gap        double precision,
    n_rejected_bull   integer,
    n_rejected_bear   integer,
    n_endorsed        integer,
    -- drivers[]: {driver, segment, priced_in_pct, value_if_true_pct, basis,
    -- testable, observable}. priced_in_pct is the JUDGED tier and is
    -- UNVALIDATED — see research/PRICED-IN-FINDINGS.md before using it.
    drivers_json      jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- The reconstructed analyst cases, endorsed and rejected.
    cases_json        jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary           text,
    -- Provenance, so a reader can tell a live run from a point-in-time one.
    pipeline_version  text,
    model             text,
    generation_is_pit boolean NOT NULL DEFAULT false,
    note_slug         text,
    published         boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_priced_in_unique UNIQUE (ticker, as_of, pipeline_version)
);

CREATE INDEX IF NOT EXISTS ix_research_priced_in_ticker
    ON swingtrader.research_priced_in (ticker, as_of DESC);
CREATE INDEX IF NOT EXISTS ix_research_priced_in_published
    ON swingtrader.research_priced_in (published, as_of DESC);

-- 2) Forward predictions. Sealed at creation; resolved once.
CREATE TABLE IF NOT EXISTS swingtrader.research_predictions (
    lock              text PRIMARY KEY,     -- sha256 over the sealed fields
    ticker            text NOT NULL,
    driver            text NOT NULL,
    priced_in_pct     double precision,
    p_resolves        double precision NOT NULL
                      CHECK (p_resolves >= 0 AND p_resolves <= 1),
    move_if_true      double precision,
    move_if_false     double precision,
    -- A prediction must name a resolver that already exists and whose inputs
    -- are wired. Resolution by post-hoc judgement is not resolution: the judge
    -- knows the outcome.
    resolver          text NOT NULL,
    spec_json         jsonb NOT NULL,
    made_on           date NOT NULL,
    resolve_on        date NOT NULL,
    price_at_prediction double precision,
    rationale         text,
    priced_in_id      bigint REFERENCES swingtrader.research_priced_in(id)
                      ON DELETE SET NULL,
    -- Resolution. UNRESOLVED means we could not observe it, and must never be
    -- scored as a miss.
    outcome           text CHECK (outcome IN ('TRUE','FALSE','UNRESOLVED')),
    outcome_detail    jsonb,
    resolved_at       date,
    price_at_resolution double precision,
    realised_move     double precision,
    published         boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_predictions_future CHECK (resolve_on > made_on)
);

CREATE INDEX IF NOT EXISTS ix_research_predictions_due
    ON swingtrader.research_predictions (resolve_on)
    WHERE outcome IS NULL;
CREATE INDEX IF NOT EXISTS ix_research_predictions_ticker
    ON swingtrader.research_predictions (ticker, made_on DESC);

-- 3) Immutability. The sealed fields are the prediction; changing any of them
--    after the fact is the failure this tier exists to prevent, so the database
--    refuses it rather than trusting the client to behave.
CREATE OR REPLACE FUNCTION swingtrader.research_predictions_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.lock IS DISTINCT FROM OLD.lock
       OR NEW.ticker IS DISTINCT FROM OLD.ticker
       OR NEW.driver IS DISTINCT FROM OLD.driver
       OR NEW.priced_in_pct IS DISTINCT FROM OLD.priced_in_pct
       OR NEW.p_resolves IS DISTINCT FROM OLD.p_resolves
       OR NEW.move_if_true IS DISTINCT FROM OLD.move_if_true
       OR NEW.move_if_false IS DISTINCT FROM OLD.move_if_false
       OR NEW.resolver IS DISTINCT FROM OLD.resolver
       OR NEW.spec_json IS DISTINCT FROM OLD.spec_json
       OR NEW.made_on IS DISTINCT FROM OLD.made_on
       OR NEW.resolve_on IS DISTINCT FROM OLD.resolve_on
       OR NEW.price_at_prediction IS DISTINCT FROM OLD.price_at_prediction
    THEN
        RAISE EXCEPTION 'research_predictions: sealed fields are immutable '
            '(lock %). A prediction edited after registration is not a '
            'prediction.', OLD.lock;
    END IF;
    IF OLD.outcome IS NOT NULL AND NEW.outcome IS DISTINCT FROM OLD.outcome THEN
        RAISE EXCEPTION 'research_predictions: % is already resolved as %. '
            'Re-resolving until the answer agrees is the retrospective failure '
            'mode this table exists to prevent.', OLD.lock, OLD.outcome;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_research_predictions_immutable
    ON swingtrader.research_predictions;
CREATE TRIGGER trg_research_predictions_immutable
    BEFORE UPDATE ON swingtrader.research_predictions
    FOR EACH ROW EXECUTE FUNCTION swingtrader.research_predictions_immutable();

-- 4) Scoring view. Brier is reported per row; the base-rate comparison has to be
--    done over a set, because a Brier score in absolute means nothing — a 75%
--    "beat" call against a 75% base rate is not skill.
CREATE OR REPLACE VIEW swingtrader.research_predictions_scored_v AS
SELECT lock, ticker, driver, priced_in_pct, resolver,
       p_resolves, move_if_true, move_if_false,
       made_on, resolve_on, resolved_at, outcome,
       price_at_prediction, price_at_resolution, realised_move,
       CASE WHEN outcome = 'TRUE'  THEN power(p_resolves - 1, 2)
            WHEN outcome = 'FALSE' THEN power(p_resolves, 2) END AS brier,
       CASE WHEN priced_in_pct <= 30 THEN 'unpriced'
            WHEN priced_in_pct >= 70 THEN 'priced'
            ELSE 'middle' END AS cell
FROM swingtrader.research_predictions
WHERE outcome IN ('TRUE','FALSE');

-- 5) Integrity. Anything listed here means the ledger was edited outside the
--    intended path; the client recomputes the hash and compares.
CREATE OR REPLACE VIEW swingtrader.research_predictions_integrity_v AS
SELECT lock, ticker, driver, made_on, resolve_on, outcome,
       (outcome IS NOT NULL AND resolved_at IS NULL)   AS resolved_without_date,
       (outcome IS NULL AND resolve_on < CURRENT_DATE) AS overdue
FROM swingtrader.research_predictions;

-- 6) Public read, gated like everything else in this family: nothing is visible
--    until someone decides it is.
ALTER TABLE swingtrader.research_priced_in ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.research_predictions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS research_priced_in_public_read ON swingtrader.research_priced_in;
CREATE POLICY research_priced_in_public_read ON swingtrader.research_priced_in
    FOR SELECT USING (published);

DROP POLICY IF EXISTS research_predictions_public_read ON swingtrader.research_predictions;
CREATE POLICY research_predictions_public_read ON swingtrader.research_predictions
    FOR SELECT USING (published);

CREATE OR REPLACE VIEW swingtrader.research_priced_in_public_v AS
SELECT ticker, as_of, price, implied_revenue_cagr, n_targets, target_low,
       target_high, target_median, median_gap, drivers_json, summary, created_at
FROM swingtrader.research_priced_in
WHERE published;

GRANT SELECT ON swingtrader.research_priced_in_public_v,
                swingtrader.research_predictions_scored_v,
                swingtrader.research_predictions_integrity_v
    TO anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON swingtrader.research_priced_in,
                                swingtrader.research_predictions
    TO service_role;
GRANT USAGE, SELECT ON SEQUENCE swingtrader.research_priced_in_id_seq TO service_role;
