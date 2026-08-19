-- ---------------------------------------------------------------------------
-- Intrinsic pixel dimensions for chart images.
--
-- Not cosmetic. The figures are lazy-loaded, and a lazy <img> with no width or
-- height collapses to zero height until it loads — so it never enters the
-- viewport, so it never loads. Seven figures rendered as a 0px-tall region and
-- the whole article measured 966px.
--
-- Storing the real dimensions lets the page reserve the right box up front,
-- which both fixes the deadlock and removes the layout shift when each plot
-- arrives.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.research_charts
    ADD COLUMN IF NOT EXISTS width  int,
    ADD COLUMN IF NOT EXISTS height int;

DROP VIEW IF EXISTS swingtrader.research_charts_public_v;
CREATE VIEW swingtrader.research_charts_public_v AS
SELECT c.slug, c.title, c.caption, c.kind, c.sample_window, c.public_url,
       c.width, c.height,
       c.campaign_run_id, c.genome_hash, c.note_slug, c.trials_considered,
       c.sort_order, c.created_at,
       (c.sample_window = 'dev') AS is_in_sample
FROM swingtrader.research_charts c
WHERE c.published
ORDER BY c.note_slug, c.sort_order, c.created_at;
