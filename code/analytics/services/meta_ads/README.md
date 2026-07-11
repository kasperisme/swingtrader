# meta_ads

Read-only Meta Marketing API access — pull ad performance and tie it to the
feature A/B. **No writes**: it never creates or edits a campaign (launch ads by
hand in Ads Manager). This is the measurement half of the self-improving loop.

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli verify                 # confirm token + account
.venv/bin/python -m services.meta_ads.cli insights [--since YYYY-MM-DD]
.venv/bin/python -m services.meta_ads.cli reconcile [--since YYYY-MM-DD]
```

- **verify** — confirms the token reaches the ad account (name, status, currency).
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

The token is a System User token (Business Settings → System Users) with `ads_read`
on the one ad account. Keep it in `.env` (gitignored); it's read-only but still a
secret. To ever automate campaign *creation*, that's a separate `ads_management`
scope + a deliberate write module with a dry-run/confirm gate — not built here.
