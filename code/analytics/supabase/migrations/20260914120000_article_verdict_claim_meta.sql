-- ---------------------------------------------------------------------------
-- Article verdict: per-claim metadata + this week's score distribution
--
-- The article page printed every number bare. "−0.40" next to a claim cannot
-- be acted on: the reader has no scale (is −0.40 a lot?) and no idea whether
-- the market already knows it. Two additions back the page's Tier-1 fixes:
--
-- 1. news_impact_heads.meta_json — per-key extras a head produces that are not
--    a score and not the display text. First user: STORY_KEY_POINTS writes
--      {"kp_1": {"novelty": "new" | "priced_in", "novelty_basis": "..."}}
--    so each claim can carry a "Priced in / New" tag. It is a separate column,
--    not more keys in reasoning_json, because three readers explode
--    reasoning_json as the claim list (head_carries_analysis, topic claims,
--    strategylab narrative) and would turn a tag into a phantom claim.
--    Nullable, no default: every row written before this migration reads as
--    "unknown" and the page shows no tag, never a guessed one.
--
-- 2. impact_score_distribution(p_days) — histogram of every claim, ticker and
--    relationship score scored in the last p_days, at 0.01 resolution (the
--    model emits ~20 distinct values, so ~60 rows). The page turns a score into
--    "more negative than 85% of claims this week". Measured 2026-09-14: 10,410
--    claims over 3,949 key-point heads in 7 days, ~1s through the pooler — so
--    the UI caches it for hours rather than calling it per view.
-- ---------------------------------------------------------------------------

SET lock_timeout = '5s';

ALTER TABLE swingtrader.news_impact_heads
  ADD COLUMN IF NOT EXISTS meta_json jsonb;

COMMENT ON COLUMN swingtrader.news_impact_heads.meta_json IS
  'Per-key extras keyed like scores_json. STORY_KEY_POINTS: {kp_N: {novelty: '
  '"new"|"priced_in", novelty_basis}}. NULL = written before the field existed.';

RESET lock_timeout;

CREATE OR REPLACE FUNCTION swingtrader.impact_score_distribution(
  p_days integer DEFAULT 7
)
RETURNS TABLE (kind text, score numeric, n bigint)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO 'swingtrader', 'pg_temp'
AS $$
  SELECT
    CASE h.cluster
      WHEN 'STORY_KEY_POINTS'     THEN 'claim'
      WHEN 'TICKER_SENTIMENT'     THEN 'ticker'
      WHEN 'TICKER_RELATIONSHIPS' THEN 'relationship'
    END                                   AS kind,
    round(v.value::numeric, 2)            AS score,
    count(*)                              AS n
  FROM swingtrader.news_impact_heads h
  CROSS JOIN LATERAL jsonb_each_text(
    CASE WHEN jsonb_typeof(h.scores_json) = 'object' THEN h.scores_json ELSE '{}'::jsonb END
  ) v
  -- (created_at, cluster) is indexed; the window keeps this an index range scan.
  WHERE h.created_at > now() - make_interval(days => greatest(1, least(p_days, 60)))
    AND h.cluster IN ('STORY_KEY_POINTS', 'TICKER_SENTIMENT', 'TICKER_RELATIONSHIPS')
    AND v.value ~ '^-?[0-9]+(\.[0-9]+)?([eE]-?[0-9]+)?$'
  GROUP BY 1, 2
$$;

COMMENT ON FUNCTION swingtrader.impact_score_distribution(integer) IS
  'Histogram (kind, score@0.01, n) of claim / ticker / relationship scores '
  'scored in the last p_days. Percentile anchors on /articles/[slug].';

GRANT EXECUTE ON FUNCTION swingtrader.impact_score_distribution(integer)
  TO anon, authenticated, service_role;
