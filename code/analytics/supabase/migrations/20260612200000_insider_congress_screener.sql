-- Insider & Congress Activity — publish the market screening row backed by the
-- `insider_congress` script_key (services/market_screenings/scripts/insider_congress.py).
--
-- A standalone "smart money" activity board: it aggregates recently disclosed
-- SEC Form 4 (executives/directors) and STOCK Act (Senate/House) trades, then
-- ranks tickers by significance (distinct buyers / dollar size / recency).
--
-- author_user_id is NOT NULL and references auth.users, so we derive the author
-- from an existing screening rather than hardcoding a UUID. Idempotent on slug.

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
    'insider-congress',
    'insider_congress',
    'Insider & Congress Activity',
    'Where the "smart money" is trading. Aggregates recently disclosed SEC '
        || 'Form 4 insider trades (executives & directors) and STOCK Act '
        || 'disclosures from the Senate & House, then ranks tickers by how '
        || 'significant the activity is — distinct buyers (a 3+ buyer cluster is '
        || 'the headline signal), dollar size, and recency. Shows net buy/sell '
        || 'tilt with C-level, director and Congress flags. Open-market trades '
        || 'only (option exercises, grants and gifts are filtered out).',
    'Insider',
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
