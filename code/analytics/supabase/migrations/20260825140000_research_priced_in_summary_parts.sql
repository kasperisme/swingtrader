-- ---------------------------------------------------------------------------
-- Structured summary for research_priced_in.
--
-- `summary` held the whole reconstruction as one ~1,500-character paragraph.
-- The content was right — where the price sits, what it pays for, what it
-- declines, and the one investigable question — but all four ran together, and
-- on a quote page that is a wall nobody reads.
--
-- Splitting it at GENERATION rather than parsing it out afterwards: the model
-- already knows which sentence is doing which job, so asking for the parts is
-- both more reliable than a regex and better prose, because each part is now
-- written to stand alone.
--
-- `summary` is kept and still populated with a flat join, so anything reading
-- it keeps working.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.research_priced_in
    ADD COLUMN IF NOT EXISTS summary_json jsonb;

COMMENT ON COLUMN swingtrader.research_priced_in.summary_json IS
    'Structured reconstruction: {position: text, pays_for: text[], '
    'declines: text[], crux: text}. `summary` remains a flat join of the same '
    'content for readers that want one string.';

CREATE OR REPLACE VIEW swingtrader.research_priced_in_public_v AS
-- summary_json is APPENDED, not inserted. CREATE OR REPLACE VIEW matches
-- columns positionally, so slotting a new one before `created_at` reads as a
-- rename and is refused.
SELECT ticker, as_of, price, implied_revenue_cagr, n_targets, target_low,
       target_high, target_median, median_gap, drivers_json, summary,
       created_at, summary_json
FROM swingtrader.research_priced_in
WHERE published;

GRANT SELECT ON swingtrader.research_priced_in_public_v
    TO anon, authenticated, service_role;
