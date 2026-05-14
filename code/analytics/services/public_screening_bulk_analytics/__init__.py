"""Public-screening bulk LLM analytics.

After a public screening produces its initial ticker list, this worker enriches
each ticker's row with an LLM analysis (status, comment, analysis_markdown,
optional entry) and then triggers fan-out to subscribers — so subscribers only
see (and get notified about) results that include the analysis.

The LLM call shape mirrors `services.bulk_analysis` (same FMP snapshot, same
prompt schema). The difference is scope: enrichment writes to
`public_screening_result_rows.row_data`, not to per-user notes/workspaces.
"""
