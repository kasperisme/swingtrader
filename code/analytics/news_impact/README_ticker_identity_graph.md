# Ticker Identity Map and Relationship Graph

This document explains how ticker/company aliases and relationship edges are modeled for daily narrative graph expansion.

## Why this exists

`TICKER_RELATIONSHIPS` data is extracted per article into `news_impact_heads.scores_json` keys like:

- `NLIGHT__LUMENTUM HOLDINGS__competitor`
- `NOVO.B__NVO__mutual`

Parsing this JSON in every runtime query is expensive and inconsistent for alias handling.  
The new structure materializes edges and adds canonical identity mapping.

## Database objects

## 1) Raw materialized edge table

Table: `swingtrader.ticker_relationship_edges`

Purpose:
- Adjacency list for graph traversal (`from_ticker -> to_ticker`).
- Pre-aggregated strengths and counts for ranking.

Main columns:
- `from_ticker`, `to_ticker`, `rel_type`
- `strength_avg`, `strength_max`
- `mention_count`, `article_count`
- `first_seen_at`, `last_seen_at`

Uniqueness:
- `(from_ticker, to_ticker, rel_type)`

Refresh function:
- `swingtrader.refresh_ticker_relationship_edges(p_lookback interval default null)`

View:
- `swingtrader.ticker_relationship_network_v`

---

## 2) Unified identity/alias table

Table: `swingtrader.security_identity_map`

Purpose:
- Store aliases in one table for different identifier types.
- Resolve aliases to a canonical ticker deterministically.

Main columns:
- `alias_kind`: one of `ticker`, `company_name`, `isin`, `figi`, `cusip`, `lei`, `other`
- `alias_value` (raw alias)
- `alias_value_norm` (generated normalized form)
- `canonical_ticker`
- `canonical_company_name` (optional)
- `confidence`, `verified`, `source`, `metadata_json`

Uniqueness:
- `(alias_kind, alias_value_norm)`

Resolver function:
- `swingtrader.resolve_canonical_ticker(p_alias_value text, p_alias_kind text default 'ticker')`

Resolution behavior:
1. exact normalized alias match by `alias_kind`
2. highest `verified`, then highest `confidence`, then lowest `id`
3. fallback to uppercase input ticker if no mapping exists

---

## 3) Canonicalized graph view

View: `swingtrader.ticker_relationship_network_resolved_v`

Purpose:
- Resolve `from_ticker` and `to_ticker` through `security_identity_map` (`alias_kind='ticker'`).
- Collapse duplicate edges after canonicalization.

Effect:
- If both `NOVO.B` and `NVO` map to canonical `NVO`, edges converge into one canonical graph node.

---

## 4) Edge traceability to source articles + dimensions

Table: `swingtrader.ticker_relationship_edge_evidence`

Purpose:
- Attach each edge to concrete source rows from `news_impact_heads`.
- Persist article provenance and dimension snapshots from `news_impact_vectors`.

Stored evidence:
- `edge_id`, `article_id`, `rel_pair_key`, `rel_type`
- `pair_strength`, `head_confidence`, `reasoning_text`
- `impact_json_snapshot`, `top_dimensions_snapshot`

Refresh function:
- `swingtrader.refresh_ticker_relationship_edge_evidence(p_lookback interval default null)`

Traceability view:
- `swingtrader.ticker_relationship_edge_traceability_v`
- Join path: `ticker_relationship_edges -> edge_evidence -> news_articles (+ vector snapshots)`

## Data flow

1. Ingestion/scoring writes article relationship heads to `news_impact_heads`.
2. `refresh_ticker_relationship_edges()` parses heads and upserts `ticker_relationship_edges`.
3. `refresh_ticker_relationship_edge_evidence()` backfills edge-to-article evidence plus vector snapshots.
4. `ticker_relationship_network_resolved_v` maps aliases to canonical symbols using `security_identity_map`.
5. Narrative graph traversal can read from the resolved view for stable multi-hop expansion.
6. Audit/debug can read `ticker_relationship_edge_traceability_v` for exact source provenance.

## Operational queries

## Refresh edges

```sql
-- Full refresh from all available history
select swingtrader.refresh_ticker_relationship_edges(null);

-- Sliding refresh (recent rows only)
select swingtrader.refresh_ticker_relationship_edges(interval '7 days');

-- Refresh traceability rows (recommended after edge refresh)
select swingtrader.refresh_ticker_relationship_edge_evidence(interval '7 days');
```

## Add alias mappings

```sql
-- Ticker alias / share-class mapping
insert into swingtrader.security_identity_map
  (alias_kind, alias_value, canonical_ticker, canonical_company_name, confidence, source, verified)
values
  ('ticker', 'NOVO.B', 'NVO', 'Novo Nordisk', 0.98, 'manual', true)
on conflict (alias_kind, alias_value_norm) do update
set canonical_ticker = excluded.canonical_ticker,
    canonical_company_name = excluded.canonical_company_name,
    confidence = excluded.confidence,
    source = excluded.source,
    verified = excluded.verified;

-- Company-name alias mapping
insert into swingtrader.security_identity_map
  (alias_kind, alias_value, canonical_ticker, canonical_company_name, confidence, source, verified)
values
  ('company_name', 'Novo Nordisk', 'NVO', 'Novo Nordisk', 0.95, 'manual', true)
on conflict (alias_kind, alias_value_norm) do update
set canonical_ticker = excluded.canonical_ticker,
    canonical_company_name = excluded.canonical_company_name,
    confidence = excluded.confidence,
    source = excluded.source,
    verified = excluded.verified;
```

## Validate canonical resolution

```sql
select swingtrader.resolve_canonical_ticker('NOVO.B', 'ticker') as canonical_ticker;
select swingtrader.resolve_canonical_ticker('Novo Nordisk', 'company_name') as canonical_ticker;
```

## Inspect resolved graph neighbors

```sql
select
  to_ticker,
  rel_type,
  strength_avg,
  mention_count,
  last_seen_at
from swingtrader.ticker_relationship_network_resolved_v
where from_ticker = 'NVO'
order by strength_avg desc, mention_count desc
limit 30;
```

## Trace a specific edge back to source evidence

```sql
select
  edge_id,
  from_ticker,
  to_ticker,
  rel_type,
  article_id,
  article_title,
  article_url,
  pair_strength,
  head_confidence,
  top_dimensions_snapshot
from swingtrader.ticker_relationship_edge_traceability_v
where from_ticker = 'NVO'
  and to_ticker = 'LLY'
order by published_at desc
limit 20;
```

## Best practices

- Use `verified=true` only for high-confidence mappings.
- Keep `source` populated (`manual`, `vendor_x`, `auto_rule`, etc.) for auditability.
- Prefer resolved view (`ticker_relationship_network_resolved_v`) in graph traversal logic.
- Refresh `ticker_relationship_edges` on a schedule (or after scoring batches).

## Current limitations

- `ticker_relationship_network_resolved_v` currently resolves only by `alias_kind='ticker'`.
- Company-name mappings are available via the resolver function but are not auto-applied to edge parsing unless article extraction stores those names as ticker aliases.
- Ambiguous aliases should be stored as unverified/low confidence until validated.
