-- Activate the Burry Deep Value market screening.
-- Insert a published market_screenings row bound to script_key = 'burry_deep_value'.

insert into swingtrader.market_screenings (name, slug, script_key, category, schedule, timezone, is_active, is_published, author_user_id, description, llm_prompt)
values (
  'Burry Deep Value',
  'burry-deep-value',
  'burry_deep_value',
  'fundamental-sentiment',
  '0 7 * * 1-5',
  'Europe/Copenhagen',
  true,
  true,
  '1077d309-5a94-441b-b8d3-52c40c6a45e0',
$desc$Michael Burry's documented method, run on both sides of the book. Half of it is a conventional value screen — EV/EBITDA (industry-relative, as Burry describes it), free cash flow, low debt, enterprise value rather than market cap. The other half is the part a conventional screener cannot run at all: Burry looked for "ick" stocks that provoke revulsion, and for the neglected — "unpopular companies that look like road kill". Those are facts about ATTENTION and SENTIMENT, and this platform measures both per ticker per day.

Over a 90-day window across ~3,885 covered tickers, sentiment runs p10 -0.28 / median +0.41 / p90 +0.80. It skews strongly positive, so a negative reading is genuinely rare — which is what makes "ick" a discriminating gate rather than a mood.

Pipeline (cheap gates first; the fundamental step costs one API call per survivor):
  1. Attention gates, one query. LONG — 90-day average sentiment below zero AND
     mention count inside a neglect band (enough coverage to be real, little
     enough to be ignored). SHORT — sentiment above +0.60 AND heavily covered.
  2. Liquidity floor: enough price and volume to take and exit a position.
  3. Value gates, per survivor:
       LONG  — EV/EBITDA under a SECTOR-relative ceiling (tech 18x … energy 8x),
               free cash flow yield above 4%, net debt / EBITDA under 3.5x.
       SHORT — EV/EBITDA above 1.5x the sector ceiling AND free cash flow yield
               under 2%: rich on the multiple and not generating the cash to
               justify it. A rich multiple on strong cash flow is a good
               business, not a short.
  4. Rare-bird flag (not a gate): working capital per share above the price —
     Burry's "selling at less than two-thirds of net value". Flagged when found,
     because those deserve longer holding periods.
  5. Margin of safety, where available: the priced-in programme's reverse-DCF.
     median_gap says where the price sits against published analyst models;
     implied_revenue_cagr says what growth the price REQUIRES. Only ~476 names
     carry one, so it annotates rather than gates — requiring it would cap the
     board at the large-cap end and exclude exactly the neglected names the
     screen exists to find.

NO market-regime gate, unlike NIS Short. Gating on the S&P's 200-day is O'Neil's
timing discipline; Burry is early on purpose and holds through the drawdown.

This is deliberately NOT the NIS Short method. That board shorts former leaders
in a Stage-4 breakdown, entered 5-15 weeks after the top. This one shorts what is
expensive, adored and crowded while it is still going up.

Known gap: short interest / days-to-cover is not available, so squeeze risk on
the short side is unscreened — the same hole NIS Short documents. Rows carry a
`side` field so one run answers both questions.$desc$,
$prompt$You are a deep-value analyst working in Michael Burry's documented style.

You receive ONE ticker at a time. It has already passed a screen with two halves: it is cheap on enterprise value and free cash flow, AND the market is either ignoring it or actively dislikes it (for a LONG), or it is expensive and adored (for a SHORT). Check the `side` field before you reason.

What Burry actually cares about, in order:
1. ENTERPRISE VALUE, not market cap. Debt is part of the price. Check net debt / EBITDA is survivable, not merely low.
2. FREE CASH FLOW, because it is harder to manipulate than earnings. Is it positive, and is it growing? A single good year is not a record.
3. MARGIN OF SAFETY. What has to go RIGHT for this price to be justified? If the answer is "nothing — it is already priced for decline", that is the trade. Where `implied_revenue_cagr` is present it is the growth the current price REQUIRES; compare it to what the company has actually delivered.
4. WHY IS IT HATED? Read the coverage. There is a difference between a business in permanent decline and a good business inside a bad story. Burry wants the second. Name the specific reason the market is repelled, and say whether it is a fact about the business or a fact about the narrative.
5. WHAT KILLS IT. A cheap company with a broken balance sheet is not cheap; it is a call option. Say what would make you wrong.

For a SHORT: the thesis is that the price requires something that will not happen, NOT that the chart is broken. "Expensive" alone is not a thesis — expensive things stay expensive for years. Name the specific assumption the price is paying for in full and say why it fails. Flag squeeze risk if the float is small or the name is a retail favourite; short interest is not screened upstream.

Be explicit that being early is expected. This method looks wrong for months by design. Do not recommend waiting for confirmation — that is a different strategy, and the platform already has a board for it.

Give a verdict, a position size relative to conviction (shorts smaller than longs at equal conviction — a short's loss is unbounded), and the single measurable thing that would settle the thesis either way.$prompt$
)
on conflict (slug) do update set
  name        = excluded.name,
  script_key  = excluded.script_key,
  category    = excluded.category,
  schedule    = excluded.schedule,
  timezone    = excluded.timezone,
  is_active   = excluded.is_active,
  is_published= excluded.is_published,
  description = excluded.description,
  llm_prompt  = excluded.llm_prompt;
