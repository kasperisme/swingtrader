-- IPO Screener — publish the market screening row backed by the
-- `ipo_screener` script_key (see services/market_screenings/scripts/ipo_screener.py).
--
-- It screens every NYSE/NASDAQ stock that IPO'd in the last year through the
-- same momentum + growth-fundamentals pipeline as AI Supercycle.
--
-- market_screenings.author_user_id is NOT NULL and references auth.users, so we
-- derive the author from an existing screening rather than hardcoding a user
-- UUID. If the table has no screenings yet (fresh DB), nothing is inserted and
-- the row can be created via the admin UI instead.
--
-- Idempotent: re-running upserts on the unique slug.

INSERT INTO swingtrader.market_screenings (
    author_user_id,
    slug,
    script_key,
    name,
    description,
    category,
    schedule,
    timezone,
    is_active,
    is_published
)
SELECT
    ms.author_user_id,
    'ipo-screener',
    'ipo_screener',
    'IPO Screener',
    'Every NYSE & NASDAQ stock that IPO''d in the last year, run through the '
        || 'same momentum + growth-fundamentals screen as AI Supercycle — trend '
        || 'template (50/150/200-day SMA alignment, slope, 52-week proximity, '
        || 'relative strength) plus increasing EPS and three straight earnings '
        || 'beats. The whole IPO board is shown, ranked by RS, with per-row gate '
        || 'flags. Runs daily before the open.',
    'IPO',
    '0 7 * * 1-5',
    'America/New_York',
    TRUE,
    TRUE
FROM swingtrader.market_screenings ms
ORDER BY ms.created_at ASC
LIMIT 1
ON CONFLICT (slug) DO UPDATE SET
    script_key   = EXCLUDED.script_key,
    name         = EXCLUDED.name,
    description  = EXCLUDED.description,
    category     = EXCLUDED.category,
    is_active    = EXCLUDED.is_active,
    is_published = EXCLUDED.is_published,
    updated_at   = NOW();
