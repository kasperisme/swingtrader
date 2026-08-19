-- ---------------------------------------------------------------------------
-- Charts for the research lab.
--
-- Companion to 20260819220000_quant_research_lab.sql. Images live in Supabase
-- Storage; this table is the catalogue that gives each one its meaning.
--
-- Two columns are NOT NULL for a reason that is specific to quant research.
--
-- `sample_window` — an equity curve drawn on the window the search optimised
-- over is the single most misleading artifact this lab produces. It always
-- slopes up and to the right, because it was selected to. The same strategy's
-- out-of-sample curve went from 5.5x the incumbent to +0.03. So no chart can be
-- stored without declaring which window it is drawn on, and the site is
-- expected to render 'dev' with a visible in-sample warning.
--
-- `caption` — a chart with no caption gets its meaning from whoever embeds it.
-- The caption is written at publish time by the code that knows what the axes
-- are, and it travels with the image.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.research_charts (
    id              bigserial PRIMARY KEY,
    slug            text NOT NULL UNIQUE,
    title           text NOT NULL,
    caption         text NOT NULL,
    -- what the picture is: equity | folds | trades | sides | exposure |
    -- search_reward | search_sources | search_operators | diagnostic
    kind            text NOT NULL,
    -- 'dev'      = the window the search optimised on. IN-SAMPLE.
    -- 'holdout'  = never seen by the search.
    -- 'vault'    = sealed window, opened once.
    -- 'full'     = spans both; read the caption.
    -- 'n/a'      = not a return series at all (search diagnostics, panel fits).
    sample_window   text NOT NULL,
    storage_path    text NOT NULL,
    public_url      text NOT NULL,
    bytes           int,
    sha256          text,
    -- provenance: which run, which strategy, which write-up
    campaign_run_id text REFERENCES swingtrader.research_campaigns(run_id)
                        ON DELETE SET NULL,
    genome_hash     text,
    note_slug       text REFERENCES swingtrader.research_notes(slug)
                        ON DELETE SET NULL,
    -- The trial count that produced the thing being drawn. An equity curve
    -- selected from 743 configurations is a different object from one that
    -- came from a single pre-registered specification, and the picture cannot
    -- show the difference — so it is carried here.
    trials_considered int,
    sort_order      int NOT NULL DEFAULT 0,
    published       boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_charts_window_ck
        CHECK (sample_window IN ('dev','holdout','vault','full','n/a'))
);

CREATE INDEX IF NOT EXISTS ix_research_charts_campaign
    ON swingtrader.research_charts (campaign_run_id, sort_order);
CREATE INDEX IF NOT EXISTS ix_research_charts_note
    ON swingtrader.research_charts (note_slug, sort_order);
CREATE INDEX IF NOT EXISTS ix_research_charts_published
    ON swingtrader.research_charts (published, created_at DESC);

ALTER TABLE swingtrader.research_charts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS research_charts_public_read ON swingtrader.research_charts;
CREATE POLICY research_charts_public_read ON swingtrader.research_charts
    FOR SELECT USING (published);

-- Charts for a published note, in display order, with the in-sample flag
-- pre-computed so a template cannot forget to check it.
CREATE OR REPLACE VIEW swingtrader.research_charts_public_v AS
SELECT c.slug, c.title, c.caption, c.kind, c.sample_window, c.public_url,
       c.campaign_run_id, c.genome_hash, c.note_slug, c.trials_considered,
       c.sort_order, c.created_at,
       (c.sample_window = 'dev') AS is_in_sample
FROM swingtrader.research_charts c
WHERE c.published
ORDER BY c.note_slug, c.sort_order, c.created_at;
