# meta_ads

Meta Marketing API — **create the ad drafts** and **measure** them. Two halves:

- **Write (drafts):** `preflight` + `draft` create the feature A/B as **PAUSED**,
  non-spending campaign drafts (see `nis-ad-launch` skill). Needs `ads_management`.
- **Read (measurement):** `verify` / `insights` / `reconcile` pull performance and
  reconcile it against real Supabase leads. Needs `ads_read`.

Nothing this module creates can spend — everything is PAUSED until you flip it Active
by hand in Ads Manager.

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli verify                 # confirm token + account
.venv/bin/python -m services.meta_ads.cli preflight              # check every gate before creating
.venv/bin/python -m services.meta_ads.cli draft                  # dry-run: print the plan
.venv/bin/python -m services.meta_ads.cli draft --go             # create the PAUSED drafts
.venv/bin/python -m services.meta_ads.cli insights [--since YYYY-MM-DD]
.venv/bin/python -m services.meta_ads.cli reconcile [--since YYYY-MM-DD]
```

- **verify** — confirms the token reaches the ad account (name, status, currency).
- **preflight** — one-pass green/red check of every gate that blocks `draft --go`:
  token scopes, ad-account status, Page assignment (CREATE_CONTENT), IG advertisability.
  Run it before the first launch; it maps each failure to its fix.
- **insights** — per-ad CTR / CPC / spend / Meta-attributed Leads, then a rollup by
  `utm_content` (the feature: `market_screening` vs `news_briefing`). The feature is
  read from each ad's creative `url_tags`, so name/UTM your ads and it groups itself.
- **reconcile** — Meta spend + clicks next to the REAL email leads in Supabase, by
  feature → **cost per actual lead**. The DB leads are pixel-independent (captured on
  the subscribe), so they're the source of truth when the pixel loses signal.

## Create the A/B as PAUSED drafts (write)

```bash
.venv/bin/python -m services.meta_ads.cli draft            # dry-run: validate + print plan
.venv/bin/python -m services.meta_ads.cli draft --go       # create the PAUSED drafts
```

Builds **1 campaign → 1 ad set per feature → 1 carousel ad per feature** from the ad
specs + their 1:1 slides (`output/ads/<slug>/1x1/`). Everything is created **PAUSED** —
it appears in Ads Manager, fully reviewable, and **cannot spend until you set it Active**.
Objective is Traffic (LINK_CLICKS), targeting DK 18–65, `--budget` DKK/day per ad set
(default 70). Needs `ads_management` scope + a Page.

## Setup (`code/analytics/.env`)
```
META_ADS_TOKEN=<System User token — ads_read to read, ads_management to create drafts>
META_AD_ACCOUNT_ID=2046577425934056        # act_ prefix optional
META_PAGE_ID=<Facebook Page id ads run from> # required for `draft --go`
META_IG_ACCOUNT_ID=                          # optional — Instagram placements
META_SPECIAL_AD_CATEGORY=                    # optional — e.g. FINANCIAL_PRODUCTS_SERVICES if Meta requires it
META_API_VERSION=v21.0                        # optional; bump if a call reports a version error
```

The token is a System User token (Business Settings → System Users). For measurement
only, `ads_read` suffices; to create drafts it needs `ads_management` +
`pages_read_engagement` + `pages_manage_ads`, the Page assigned to the System User
(CREATE_CONTENT), and — for an explicit IG byline — the IG account assigned to the ad
account. `preflight` verifies all of this. Keep the token in `.env` (gitignored); it's a
secret. See the `nis-ad-launch` skill for the full launch + gate-troubleshooting flow.

For EU targeting (e.g. DK), Meta requires a DSA beneficiary/payor on each ad set — set
`META_DSA_BENEFICIARY` (default "News Impact Screener"). The App must also be in **Live**
mode (developers.facebook.com → App Mode) for creative creation to succeed.
