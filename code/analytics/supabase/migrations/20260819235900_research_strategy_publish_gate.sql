-- ---------------------------------------------------------------------------
-- Close the publish gate on research_strategies.
--
-- research_notes and research_charts each carry `published` and their public
-- views filter on it. research_strategies did not, so research_leaderboard_v
-- would have exposed every backfilled strategy the moment a page read it —
-- including rows whose gate was never evaluated.
--
-- Same rule as everywhere else in this schema: nothing is visible until someone
-- decides it is.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.research_strategies
    ADD COLUMN IF NOT EXISTS published boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS ix_research_strategies_published
    ON swingtrader.research_strategies (published, deflated_sharpe DESC);

DROP POLICY IF EXISTS research_strategies_public_read ON swingtrader.research_strategies;
CREATE POLICY research_strategies_public_read ON swingtrader.research_strategies
    FOR SELECT USING (published);

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
WHERE s.published
-- Ordered by the OUT-OF-SAMPLE number where one exists. Ranking a public
-- leaderboard by in-sample Sharpe would put the most overfitted strategy on top.
ORDER BY COALESCE((s.holdout_metrics->>'sharpe')::float8, -99) DESC,
         s.deflated_sharpe DESC;
