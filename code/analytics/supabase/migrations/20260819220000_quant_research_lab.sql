-- ---------------------------------------------------------------------------
-- Autonomous quant research lab — the published record.
--
-- Written by strategylab's research daemon, read by the public site. The whole
-- point is that a reader can REPLICATE, so every row carries the exact inputs
-- (genome, protocol, data window, universe) alongside the result.
--
-- The schema encodes one hard-won lesson: a single good backtest is not a
-- finding. Everything the lab produced that looked good on first sight failed
-- its first honest replication —
--
--     a pre-filter worth +0.156 Sharpe on one genome ... p = 0.53 across seven
--     an "impact law" with R2 = 0.83 ................... p = 0.92 out of sample
--     a search worth 5.5x in-sample .................... +0.03 out of sample
--
-- So `status` is not decoration and the site must not render OBSERVED the same
-- way it renders CONFIRMED. `trials_considered` and `deflated_sharpe` are NOT
-- NULL because a Sharpe ratio without the number of configurations it was
-- selected from is not a result, it is an anecdote.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.research_campaigns (
    id                  bigserial PRIMARY KEY,
    run_id              text NOT NULL UNIQUE,
    started_at          timestamptz NOT NULL,
    ended_at            timestamptz,
    -- Reproduction inputs. Without these a published number cannot be checked.
    protocol_version    text NOT NULL,
    universe_size       int  NOT NULL,
    prefilter           text NOT NULL DEFAULT 'none',
    dev_start           date NOT NULL,
    dev_end             date NOT NULL,
    costs_json          jsonb NOT NULL,
    -- What happened.
    iterations          int  NOT NULL DEFAULT 0,
    trials_own          int  NOT NULL DEFAULT 0,
    trials_inherited    int  NOT NULL DEFAULT 0,
    best_genome_hash    text,
    best_reward         double precision,
    best_sharpe         double precision,
    pbo                 double precision,
    stop_reason         text NOT NULL,
    stop_detail         text,
    models_used         jsonb,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_research_campaigns_started
    ON swingtrader.research_campaigns (started_at DESC);

-- The strategies themselves: everything needed to re-run one exactly.
CREATE TABLE IF NOT EXISTS swingtrader.research_strategies (
    id                  bigserial PRIMARY KEY,
    genome_hash         text NOT NULL,
    campaign_run_id     text NOT NULL REFERENCES swingtrader.research_campaigns(run_id)
                            ON DELETE CASCADE,
    genome_json         jsonb NOT NULL,
    changes_vs_incumbent text,
    -- In-sample. Always shown WITH the out-of-sample columns beside it, never
    -- alone: the gap between them is the finding.
    dev_metrics         jsonb NOT NULL,
    fold_metrics        jsonb,
    -- Out-of-sample, on windows the search never touched. NULL means untested,
    -- which the site must render as "untested", not as "passed".
    holdout_metrics     jsonb,
    vault_metrics       jsonb,
    -- Selection-bias accounting. NOT NULL on purpose.
    trials_considered   int NOT NULL,
    deflated_sharpe     double precision NOT NULL,
    pbo                 double precision,
    gate_passed         boolean NOT NULL DEFAULT false,
    gate_failures       text[],
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (genome_hash, campaign_run_id)
);

CREATE INDEX IF NOT EXISTS ix_research_strategies_hash
    ON swingtrader.research_strategies (genome_hash);
CREATE INDEX IF NOT EXISTS ix_research_strategies_sharpe
    ON swingtrader.research_strategies ((dev_metrics->>'sharpe'));

-- Findings: claims, and how much evidence stands behind each one.
CREATE TABLE IF NOT EXISTS swingtrader.research_findings (
    id                  bigserial PRIMARY KEY,
    slug                text NOT NULL UNIQUE,
    claim               text NOT NULL,
    -- observed | replicating | confirmed | refuted | vacuous
    status              text NOT NULL,
    replications        int NOT NULL DEFAULT 0,
    refutations         int NOT NULL DEFAULT 0,
    evidence_json       jsonb,
    -- The honest counterweight, stored next to the claim so it cannot be
    -- dropped in rendering: what would have to be true for this to be wrong.
    caveats             text,
    -- Copy-pasteable command that regenerates the result.
    reproduce_command   text,
    source_campaign     text,
    published           boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_research_findings_status
    ON swingtrader.research_findings (status, updated_at DESC);

-- Long-form write-ups (the markdown in research/), versioned by slug.
CREATE TABLE IF NOT EXISTS swingtrader.research_notes (
    id                  bigserial PRIMARY KEY,
    slug                text NOT NULL UNIQUE,
    title               text NOT NULL,
    summary             text,
    body_md             text NOT NULL,
    -- 'negative' results are first-class here. Most of what this lab produces
    -- is a refutation, and a lab that only publishes wins is not a lab.
    result_kind         text NOT NULL DEFAULT 'negative',
    tags                text[],
    charts              jsonb,
    published           boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_research_notes_published
    ON swingtrader.research_notes (published, updated_at DESC);

-- ---------------------------------------------------------------------------
-- Public read access. Only PUBLISHED rows, and only through a view, so a
-- half-finished campaign cannot leak onto the site mid-run.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW swingtrader.research_public_v AS
SELECT n.slug, n.title, n.summary, n.body_md, n.result_kind, n.tags, n.charts,
       n.created_at, n.updated_at
FROM swingtrader.research_notes n
WHERE n.published;

CREATE OR REPLACE VIEW swingtrader.research_leaderboard_v AS
SELECT s.genome_hash,
       s.campaign_run_id,
       (s.dev_metrics->>'sharpe')::float8      AS dev_sharpe,
       (s.holdout_metrics->>'sharpe')::float8  AS holdout_sharpe,
       s.trials_considered,
       s.deflated_sharpe,
       s.pbo,
       s.gate_passed,
       c.prefilter,
       c.dev_start,
       c.dev_end,
       s.created_at
FROM swingtrader.research_strategies s
JOIN swingtrader.research_campaigns c ON c.run_id = s.campaign_run_id
-- Ordered by the OUT-OF-SAMPLE number where one exists. Ranking a public
-- leaderboard by in-sample Sharpe would put the most overfitted strategy on top.
ORDER BY COALESCE((s.holdout_metrics->>'sharpe')::float8, -99) DESC,
         s.deflated_sharpe DESC;

ALTER TABLE swingtrader.research_campaigns  ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.research_strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.research_findings   ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.research_notes      ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS research_notes_public_read ON swingtrader.research_notes;
CREATE POLICY research_notes_public_read ON swingtrader.research_notes
    FOR SELECT USING (published);

DROP POLICY IF EXISTS research_findings_public_read ON swingtrader.research_findings;
CREATE POLICY research_findings_public_read ON swingtrader.research_findings
    FOR SELECT USING (published);
