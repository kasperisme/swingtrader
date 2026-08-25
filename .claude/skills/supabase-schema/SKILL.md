---
name: supabase-schema
description: >-
  Check what already exists in the swingtrader Supabase schema BEFORE writing any query,
  building any data structure, or computing any relationship/aggregate over its data.
  84 tables and views, 851 columns and 51 RPC functions already cover the full
  inter-company relationship graph (suppliers, customers, partners, competitors,
  subsidiaries, acquirers), news scoring and claims, ticker sentiment, embeddings and
  semantic search,
  trend aggregates, coverage, pair/cointegration stats, screening and attribution — and
  the intent behind each is generated from the migration headers so it says what an
  object is FOR, not just its columns. Use whenever a task touches swingtrader data:
  writing SQL or PostgREST calls, adding a migration, joining anything to news or
  tickers, or building a peer set, similarity, ranking, aggregate or graph traversal
  that the schema may already provide. Also use before concluding that something "does
  not exist yet". NOT for the strategylab parquet/CSV caches (those are local files).
---

# Supabase schema — look before you build

## Why this skill exists

An agent that cannot see what is already in the database rebuilds it, badly.

In one session a peer-relationship finder was written from scratch and iterated
through four failed designs — raw news co-occurrence, then lift over base rate,
then a Poisson excess test, then a share threshold. Each failed differently and
the best of them still returned *NVDA, AAPL, MU* as Crocs' peer group, because
raw co-occurrence measures fame rather than connection.

Meanwhile `swingtrader.ticker_relationship_edges` already held **38,493 typed,
directional, strength-weighted, evidence-backed edges**, refreshed daily, with a
`get_relationship_neighborhood()` RPC that did the traversal. Asking it for CROX
returns `LULU, NKE, DECK` and `HEYDUDE (subsidiary)`. One query, correct answer.

The cost was a day of work and four wrong answers. The cause was not carelessness
about SQL — it was never asking the question. **So ask it first, every time.**

## Step 1 — read the index (always, before writing anything)

```bash
cd code/analytics && cat docs/supabase_index.md
```

~155 lines, one per object, grouped by domain, each with the intent extracted
from its migration header and its row count and freshness. Read it. It is
cheaper than one wrong design.

Search it when you know the capability you want but not the name:

```bash
cd code/analytics && .venv/bin/python -m services.catalog.build find "relationship"
cd code/analytics && .venv/bin/python -m services.catalog.build find "sentiment"
```

`find` searches four things — object names, the migration's rationale, column
names, and **the distinct values of enum-ish columns** — and ranks a rationale
hit above a column hit, because you are looking for a capability, not a string.

Searching values is what makes it usable. `find "competitor"` returns nothing on
names alone, because `competitor` is a *value* in `rel_type`, not a table or a
column — and that is exactly the word you would type. It now answers:

```
ticker_relationship_edges   ...   [rel_type = competitor]
news_impact_heads           ...   [cluster = supply_chain]
```

A short alias table covers words that appear nowhere in the schema at all —
`peer`, `rival`, `related`, `network`, `narrative`, `consensus`, `semantic`,
`cointegration`, `pairs`. If you search a term and get nothing, try a synonym
before concluding the capability is missing; `cat docs/supabase_index.md` is the
authoritative answer, `find` is the shortcut.

Full detail — every column, type, row estimate and freshness date:

```bash
cd code/analytics && less docs/SUPABASE-CATALOG.md
```

## Step 2 — regenerate when the schema changes

```bash
cd code/analytics && .venv/bin/python -m services.catalog.build
```

Generated from the **live database** plus the **migration files**, so it cannot
drift from the truth. Run it after adding a migration. Never hand-edit
`SUPABASE-CATALOG.md`, `supabase_index.md` or `supabase_catalog.json`.

## The things most likely to be reinvented

Read the index anyway — this list is a safety net, not a substitute.

| If you are about to build… | It already exists |
|---|---|
| **any** relation between two companies — suppliers, customers, partners, competitors, subsidiaries, acquirers, investors | `ticker_relationship_edges`. See the scope note below — this is one table, not several |
| why two tickers are linked | `ticker_relationship_edge_evidence` — traceable back to source articles |
| brand → parent company | the same graph, `rel_type IN ('subsidiary','acquirer')`. `CROX → HEYDUDE` |
| cointegration, hedge ratio, spread z-score | `ticker_pair_stats`; joined to the news graph in `ticker_relationship_network_pairs_v` |
| per-article claims / "what is being said" | `news_impact_heads`, `cluster='STORY_KEY_POINTS'` — `reasoning_json` is claim text, `scores_json` the signed impact, zipped on the same `kp_N` key |
| what the market thinks about growth/valuation | `news_impact_heads` clusters `GROWTH_PROFILE`, `VALUATION_POSITIONING`, `BUSINESS_MODEL`, `MACRO_SENSITIVITY`, `GEOGRAPHY_TRADE`, `FINANCIAL_STRUCTURE`. `scores_json` holds **sub-dimensions**, not one number |
| per-ticker sentiment | `ticker_sentiment_heads` (pre-exploded, indexed) — not a re-parse of the JSONB heads |
| semantic search over news | `news_article_embeddings` + the `search_news_embeddings()` RPC (HNSW, oversample/post-filter) |
| trending tags or tickers | `news_trends_tag_daily_v`, `news_trends_ticker_daily_v` — **bounded to a rolling 120 days** |
| company factor exposures | `company_vectors` (`dimensions_json`, `raw_json`) — powers `/protected/relations` and `/protected/vectors` |

## `ticker_relationship_edges` is the whole company graph, not a peer table

Worth stating plainly because it was got wrong twice — once by building a peer
finder from scratch, and again by describing this table as "peers and
competitors" and routing supply-chain questions somewhere else. **The value
chain is the majority of it**, measured over 38,497 edges across 9,382 tickers,
all refreshed daily:

| `rel_type` | edges | share |
|---|---|---|
| `competitor` | 16,206 | 42.1% |
| `partner` | 8,652 | 22.5% |
| `customer` | 4,654 | 12.1% |
| `supplier` | 4,376 | 11.4% |
| `acquirer` | 3,037 | 7.9% |
| `subsidiary` | 1,396 | 3.6% |

Plus a long tail (`investor`, `service_provider`, `potential_acquirer`, …) under
0.5% combined, and a few junk values (`n/a`, `none`, `other`, one pipe-delimited
row) worth filtering out.

Edges are **directional** and both directions occur — "NKE competes with CROX"
and "CROX competes with NKE" are two rows recorded from two articles — so read
both and deduplicate. Rank by `strength_avg * ln(1 + mention_count)`, not by
either alone: a confidently-asserted edge seen once should not outrank a slightly
weaker one seen thirty times. `last_seen_at` lets you drop stale links.

**Do not confuse it with the news scoring dimension of a similar name.** They
answer different questions and the catalog will offer you both:

| question | object |
|---|---|
| who supplies whom — *structure* | `ticker_relationship_edges`, `rel_type='supplier'` |
| how much is this article about supply-chain risk — *scoring* | `news_impact_heads`, `cluster='SUPPLY_CHAIN_EXPOSURE'` |

## Two traps the catalog will not save you from

**Article-level facts are many-to-many with tickers.** `news_impact_heads` rows
attach to an *article*, and `news_article_tickers` links that article to every
ticker it names. Join them naively and a market wrap tagged with eight companies
donates all its claims to all eight — Crocs' "narrative" came back containing the
Iran deal and WTI crude. Restrict to focused articles when you need attribution:

```sql
GROUP BY nat.article_id HAVING COUNT(*) <= 4
```

The same applies to co-occurrence of any kind: an article naming fifteen tickers
asserts nothing about any pair of them but contributes 105 co-occurrences.

**Never OR-filter straight into `news_article_embeddings`.** The shape
`JOIN news_article_embeddings e ... WHERE (a.search_tags && ... OR EXISTS(...))`
times out — 1.8M rows, and the OR defeats every index. It has caused three
separate outages in one project. Resolve article ids against `news_articles`
first (218k rows, indexed on both the tag array and the ticker link), then look
up chunks with `WHERE e.article_id = ANY(%s)`. Bound the id list too: an
unfiltered window returns 14,392 ids for AAPL and the follow-up `ANY()` dies on
exactly the best-covered names.

**Row counts in the catalog are planner estimates**, and views show no count at
all because `reltuples` does not apply to them. Check `fresh to <date>` before
trusting an object — several tables exist, are empty, and were abandoned.
