# services/ceos — the CEO directory's data

Fills `swingtrader.company_ceos` (one row per symbol) from FMP so the CEO name on
`/quote/<symbol>` can link to `/ceos/<slug>`. People are derived by
`ceo_directory_v`, which groups rows by `ceo_slug` — GOOG and GOOGL are two rows
and one person.

```bash
cd code/analytics
.venv/bin/python -m services.ceos.cli refresh --limit 500           # largest 500 not fetched in 30d
.venv/bin/python -m services.ceos.cli refresh --symbols NVDA,GOOGL   # specific tickers, always
.venv/bin/python -m services.ceos.cli refresh --dry-run --limit 5    # fetch + print, no writes
.venv/bin/python -m services.ceos.cli show NVDA                      # a row, or a slug
.venv/bin/python -m services.ceos.cli stats
```

Per symbol, three FMP calls:

| endpoint | gives |
|---|---|
| `profile` | **who** — the same `ceo` string the quote page prints |
| `key-executives` | their title, birth year, pay; the rest of the team |
| `governance-executive-compensation` | SEC proxy pay by year (salary, stock, options, …, total, filing link) |

The profile decides who the CEO is. key-executives often has several "CEO"
titles (co-CEOs, subsidiary CEOs); the link has to lead to the name the quote
page actually shows.

## Things to know

- **Slugs.** `names.clean_name` drops honorifics and credentials, keeps middle
  initials and Jr./III, and never invents a name ("Timothy D. Cook" →
  `timothy-d-cook`, not `tim-cook`). Rows with the same cleaned name are one
  person **unless their birth years disagree**, in which case every row in the
  group gets a `-<symbol>` suffix (`assign_slugs`). A wrong merge would claim
  someone runs a company they do not.
- **Stale CEOs.** The quote page links only when `ceo_name_raw` equals the live
  profile's `ceo`. After a succession it shows plain text until the next refresh.
  When FMP stops naming a CEO for a symbol the row is deleted.
- **lastmod.** `content_changed_at` moves only when a field a reader sees changes
  (`store._HASHED`, which excludes market cap). The sitemap uses it, never
  `fetched_at`.
- **Quota.** FMP's bandwidth cap answers `429 "Bandwidth Limit Reach"`. The run
  stops at the first one (`FmpQuotaError`) and writes whatever already landed;
  retrying only digs deeper. A full pass is ~5,800 symbols × 3 calls.
- **Misses** (ETFs, shells: no CEO) are remembered in `output/ceos/misses.json`
  for `--stale-days`, so a nightly pass does not re-ask about them.
