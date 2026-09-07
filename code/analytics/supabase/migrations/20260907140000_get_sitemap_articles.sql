-- ---------------------------------------------------------------------------
-- sitemap_article_urls: which article URLs are worth asking Google to index
--
-- The sitemap shipped the newest 5,000 /articles/* URLs with no filter at all,
-- which made 74% of everything offered to a crawler a wrapper around a
-- third-party headline. Sampling that set returned, verbatim: "A.C.L.
-- Construction Secures Civil Package for Linda's Friendship Center in Fort
-- Nelson BC", "ASICS Europe Expands Global Partnership with Teamwork Commerce",
-- and three separate securities-class-action notices. Search Console's verdict
-- on the whole domain was consistent with that: every hub page sat at
-- "Crawled - currently not indexed" and the /quote tree — the differentiated
-- part of the site — had never been fetched at all. Crawl budget is finite and
-- it was being spent here.
--
-- Two gates, and the split between them is deliberate:
--
-- 1. RELEVANCE — the article must name a ticker that is BOTH a real listed
--    security (swingtrader.tickers) AND actively covered
--    (ticker_coverage_daily, >= p_min_scored scored mentions in 30 days).
--    Either alone leaks: tickers-only admits 50.6k rows including symbols we
--    publish nothing about, coverage-only trusts a symbol string that may never
--    have been a listing. Together they are what makes an article page part of
--    the site rather than a stray. This is also the hub-and-spoke condition —
--    every article that reaches the sitemap links to a /quote page that is
--    itself in the sitemap.
--
-- 2. GENRE — securities-litigation wire copy is excluded by title pattern.
--    It is 10% of the corpus (10,092 of 91,746 over 180 days), it names real
--    covered tickers so gate 1 cannot see it, and it is templated PR reprinted
--    across every aggregator: the exact "scaled content" shape that costs a
--    young domain its crawl rate. Publisher is not usable as the signal —
--    Newsfile/GlobeNewswire/PRNewswire carry legitimate earnings releases too —
--    so the pattern matches the genre's own boilerplate instead.
--
-- Notably NOT a gate: |sentiment_score|. It was the obvious first choice and it
-- is wrong — it ranks how bullish a story is, not how relevant. At >= 0.4 it
-- dropped "QuantumScape Stock Is Worth a Closer Look Right Now" and "Intuitive
-- Surgical's Growth Has Cooled From Its Post-Pandemic Highs" (measured, neutral
-- analysis of covered names — exactly what should be indexed) while keeping
-- every law-firm notice, because outrage scores high. Relevance is the axis.
--
-- WHY A TABLE AND NOT A QUERY. This first shipped as get_sitemap_articles(),
-- computing the gates live. Measured against the live database it ran 0.88s
-- warm but 4.96-8.93s cold across repeated trials — and the REST role's
-- statement_timeout is 8s. The sitemap is the one endpoint guaranteed to hit
-- the cold path (Google last fetched it after a 13-day gap), and the failure is
-- SILENT: app/sitemap.ts catches, warns, and ships zero article URLs, which has
-- already happened once on this file for the /quote block. Same trade, same
-- resolution as refresh_ticker_coverage_daily, whose own comment records 7.6s
-- live vs ~70ms materialized. The gates are evaluated once per scoring run;
-- the sitemap reads an indexed 30k-row table.
-- ---------------------------------------------------------------------------

create table if not exists swingtrader.sitemap_article_urls (
  slug         text        primary key,
  published_at timestamptz not null
);

comment on table swingtrader.sitemap_article_urls is
  'Article slugs worth submitting to search engines: names a real, actively-covered '
  'ticker and is not securities-litigation wire copy. Rebuilt by '
  'refresh_sitemap_article_urls(); read by app/sitemap.ts. Never hand-edited.';

-- The only read pattern is "newest N", so the index carries published_at DESC
-- and the slug rides along to keep it an index-only scan.
create index if not exists sitemap_article_urls_published_idx
  on swingtrader.sitemap_article_urls (published_at desc) include (slug);

create or replace function swingtrader.refresh_sitemap_article_urls(
  p_days       integer default 180,
  p_min_scored integer default 5
)
returns integer
language plpgsql
security definer
set search_path to 'swingtrader', 'pg_temp'
as $$
declare
  v_count integer := 0;
  -- The litigation-PR genre names itself. Every one of these is boilerplate
  -- that appears in the headline, not the body, so a title match is enough.
  v_litigation constant text :=
    '(rosen law|rosen, |robbins llp|levi & korsinsky|pomerantz|bronstein|'
    'glancy prongay|kahn swick|schall law|faruqi|bragar eagel|lead plaintiff|'
    'class action|securities fraud|deadline alert|investor alert|'
    'deadline notice|investors with losses|encourages .* investors)';
begin
  delete from swingtrader.sitemap_article_urls where true;  -- safeupdate needs a WHERE

  insert into swingtrader.sitemap_article_urls (slug, published_at)
  with covered as (
    select d.ticker
    from swingtrader.ticker_coverage_daily d
    where d.bucket_day >= current_date - 30
    group by d.ticker
    having sum(d.scored_count) >= greatest(0, p_min_scored)
  )
  select distinct on (a.slug)
         a.slug::text,
         coalesce(a.published_at, a.created_at)
  from swingtrader.news_articles a
  where a.slug is not null
    and coalesce(a.published_at, a.created_at)
        > now() - make_interval(days => greatest(1, least(p_days, 730)))
    and a.title !~* v_litigation
    and exists (
      select 1
      from swingtrader.ticker_sentiment_heads h
      join swingtrader.tickers t on t.symbol = h.ticker
      join covered c            on c.ticker = h.ticker
      where h.article_id = a.id
    )
  order by a.slug, coalesce(a.published_at, a.created_at) desc;

  get diagnostics v_count = row_count;

  -- DELETE + INSERT of 31k rows leaves the planner with stats describing the
  -- previous generation, and the first read after a rebuild is the one the
  -- crawler is most likely to get. Cheap here, and it keeps that read on the
  -- index-only path.
  analyze swingtrader.sitemap_article_urls;

  return v_count;
end;
$$;

-- Wrapper the REST role calls, mirroring exec_ticker_coverage_refresh: the
-- rebuild scans 90k articles and must not inherit the caller's 8s timeout.
create or replace function swingtrader.exec_sitemap_article_refresh()
returns void
language plpgsql
security definer
set search_path to 'swingtrader', 'pg_temp'
set statement_timeout to '300s'
set lock_timeout to '30s'
as $$
begin
  perform swingtrader.refresh_sitemap_article_urls();
end;
$$;

grant select on swingtrader.sitemap_article_urls to anon, authenticated, service_role;
grant execute on function swingtrader.exec_sitemap_article_refresh() to service_role;

-- Superseded by the table above; it existed only between this migration's two
-- revisions, but drop it so nothing picks up the slow path by name.
drop function if exists swingtrader.get_sitemap_articles(integer, integer, integer);
