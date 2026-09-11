-- ---------------------------------------------------------------------------
-- company_ceos — who runs each company, and what they are paid
--
-- The quote page has always printed a CEO name (FMP's `profile.ceo`) as dead
-- text. This is the index that lets that name become a link: one row per
-- symbol, holding the CEO as FMP names them plus the two things a CEO page is
-- actually worth visiting for — the SEC proxy compensation history
-- (`governance-executive-compensation`) and the rest of the leadership team
-- (`key-executives`).
--
-- WHY A TABLE AND NOT A LIVE FMP CALL. A CEO page is addressed by the PERSON
-- (`/ceos/jensen-huang`), and nothing at FMP resolves a name back to a symbol.
-- Something has to hold that reverse index, and the bulk profile endpoint that
-- could build it on the fly is not on our plan. Filled by
-- `services/ceos` (`cli refresh`), which walks `swingtrader.tickers`.
--
-- ONE ROW PER SYMBOL, NOT PER PERSON. People are derived: `ceo_directory_v`
-- groups rows by `ceo_slug`. That is what makes dual-class listings come out
-- right for free — GOOG and GOOGL are two rows and one Sundar Pichai.
--
-- `ceo_slug` is assigned by the refresher, not here, because it needs the
-- whole table: two rows with the same name are the same person unless their
-- birth years disagree, in which case both get a `-<symbol>` suffix rather
-- than being merged. Claiming a person runs a company they do not is worse
-- than an uglier URL.
--
-- `ceo_name_raw` is FMP's string verbatim ("Mr. Jen-Hsun Huang") and is what
-- the quote page compares against the live profile: when they differ the CEO
-- has changed since the last refresh, and the page shows plain text rather
-- than linking to the predecessor.
--
-- `content_changed_at` is the page's honest lastmod. `fetched_at` moves on
-- every refresh; this only moves when something a reader would see changed,
-- so the sitemap never claims a re-fetch as an update.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.company_ceos (
  symbol              text PRIMARY KEY,
  company_name        text,
  exchange            text,
  sector              text,
  industry            text,
  country             text,
  market_cap          bigint,

  ceo_name_raw        text NOT NULL,
  ceo_name            text NOT NULL,
  ceo_slug            text NOT NULL,
  ceo_title           text,
  year_born           integer,
  -- FMP's value verbatim (a year or a date, inconsistently); text so a bare
  -- year is never promoted to a fabricated 1 January.
  title_since         text,
  pay                 bigint,
  currency_pay        text,

  -- [{year, salary, bonus, stock_award, option_award, incentive, other, total,
  --   filing_date, link, name_and_position}], newest year first.
  compensation        jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- [{name, title, pay, currency_pay, year_born}], FMP's order.
  executives          jsonb NOT NULL DEFAULT '[]'::jsonb,

  content_hash        text,
  fetched_at          timestamptz NOT NULL DEFAULT now(),
  content_changed_at  timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_company_ceos_slug ON swingtrader.company_ceos (ceo_slug);
CREATE INDEX IF NOT EXISTS idx_company_ceos_fetched ON swingtrader.company_ceos (fetched_at);

CREATE OR REPLACE FUNCTION swingtrader.touch_company_ceos_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_company_ceos_updated_at ON swingtrader.company_ceos;
CREATE TRIGGER trg_company_ceos_updated_at
  BEFORE UPDATE ON swingtrader.company_ceos
  FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_company_ceos_updated_at();

-- ── The directory: one row per person ──────────────────────────────────────
-- Ranked by the largest company they run, which is the order a reader expects
-- ("the CEO of Apple" before "the CEO of a $40M biotech"). `latest_pay` is the
-- newest proxy-year total across their companies.
CREATE OR REPLACE VIEW swingtrader.ceo_directory_v AS
SELECT
  c.ceo_slug,
  (array_agg(c.ceo_name ORDER BY c.market_cap DESC NULLS LAST))[1]      AS ceo_name,
  (array_agg(c.ceo_title ORDER BY c.market_cap DESC NULLS LAST))[1]     AS ceo_title,
  array_agg(c.symbol ORDER BY c.market_cap DESC NULLS LAST)             AS symbols,
  array_agg(DISTINCT c.company_name) FILTER (WHERE c.company_name IS NOT NULL) AS companies,
  (array_agg(c.company_name ORDER BY c.market_cap DESC NULLS LAST))[1]  AS primary_company,
  (array_agg(c.sector ORDER BY c.market_cap DESC NULLS LAST))[1]        AS sector,
  max(c.market_cap)                                                     AS market_cap,
  max(c.year_born)                                                      AS year_born,
  max(NULLIF(c.compensation -> 0 ->> 'total', '')::numeric)::bigint     AS latest_pay,
  max((c.compensation -> 0 ->> 'year')::int)                            AS latest_pay_year,
  bool_or(jsonb_array_length(c.compensation) > 0)                       AS has_compensation,
  max(c.content_changed_at)                                             AS content_changed_at
FROM swingtrader.company_ceos c
GROUP BY c.ceo_slug;

-- ── Grants + RLS ───────────────────────────────────────────────────────────
-- Public reference data, read by the site through the service client; writes
-- are the refresher's alone.
GRANT SELECT ON swingtrader.company_ceos    TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.ceo_directory_v TO anon, authenticated, service_role;
GRANT INSERT, UPDATE, DELETE ON swingtrader.company_ceos TO service_role;

ALTER TABLE swingtrader.company_ceos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public read company_ceos" ON swingtrader.company_ceos;
CREATE POLICY "Public read company_ceos" ON swingtrader.company_ceos
  FOR SELECT USING (true);
