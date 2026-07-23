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
.venv/bin/python -m services.meta_ads.cli design [--by hook_type]
```

- **verify** — confirms the token reaches the ad account (name, status, currency).
- **design** — joins per-ad performance to each ad's **design genome** (via `ad_id` in the
  `launch_manifest.json`) → *which creative choices drive engagement*. `--by <field>` rolls up
  one lever; `--leaderboard` ranks every lever best-first (low-sample rows flagged); `--json`
  emits a machine-readable rollup that `nis-ad-image` Step 0 reads to bias the next ad;
  `--min-impr N` cuts noise. Comparisons use **normalized rates** (CTR, CPM, CVR, CPL) — already
  per-impression/per-spend, so budget & days-active don't need dividing out — with `frequency`
  carried as a fatigue covariate (`⚠fatigue` flag) and CPM as an audience-cost signal. Works
  before delivery too. This is the feedback half — performance → next ad's design.
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
# a dated campaign folder (its briefing/ + market-screening/ subfolders = the ad sets):
.venv/bin/python -m services.meta_ads.cli draft --campaign 2026-07-14-geopolitics        # dry-run
.venv/bin/python -m services.meta_ads.cli draft --campaign 2026-07-14-geopolitics --go   # create
# or the legacy flat product A/B (campaigns.FEATURES):
.venv/bin/python -m services.meta_ads.cli draft [--go]
```

Content is saved as `output/ads/<date>-<short-name>/<lead-magnet>/` (`<lead-magnet>` ∈
`briefing` | `market-screening`), each holding an `ad.json` + `1x1/ad.png` (from
`nis-ad-image`) and/or `9x16/ad_reel.mp4` (+poster, from `build_ad_reel`). `--campaign` makes
that folder **1 campaign → 1 ad set per lead-magnet → 1 ad each**. A rendered **reel launches
as a video ad automatically** (uploaded to Meta `/advideos`, no manual upload); otherwise a
single-image ad. Everything is created **PAUSED** — reviewable in Ads Manager,
**cannot spend until you set it Active**. Default objective **`OUTCOME_LEADS`**, ad sets
optimize the **LEAD pixel conversion** (sign-ups, not just clicks), audience **US/GB/CA/AU
18–65 broad**, `--budget` DKK/day per ad set (default 70). All audience/objective knobs are
env-overridable (see below). Needs `ads_management` scope, a Page, and `META_PIXEL_ID` for
lead optimization.

On `--go` it also writes `output/ads/<campaign>/launch_manifest.json` — one row per ad joining
the Meta `ad_id` to that ad's `design.json` (the creative genome from `nis-ad-image`). Join it
to `insights` (per-ad, keyed by `ad_id`) to see **which design choices drive engagement**.

## Push leads to Meta — Conversions API / CRM (`capi.py`)

Forwards **`early_access_signups`** leads to Meta's dataset as CRM `Lead` events
(Meta's "Qualified Leads" integration — the server-side complement to the browser
pixel). This feeds Meta real, first-party sign-ups for match + optimization; it's the
push side of the loop `reconcile` measures.

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli capi-sync --dry-run      # show a sample HASHED event, send nothing
.venv/bin/python -m services.meta_ads.cli capi-test --test TEST12345   # one synthetic event → Events Manager Test Events
.venv/bin/python -m services.meta_ads.cli capi-sync                # PRODUCTION: upload all pending leads, mark them sent
.venv/bin/python -m services.meta_ads.cli capi-sync --since 2026-07-01 --limit 200
```

Each event is the exact CRM shape Meta specifies: `action_source: system_generated`,
`custom_data.event_source: crm` + `lead_event_source`, `event_name: Lead`,
`event_time` = the signup time, `event_id` = the signup id (**dedup key**). Contact info
is **SHA-256 hashed before it leaves the server** — email (`em`, primary match) plus, when
captured, city/region/country (`ct`/`st`/`country`); user-agent / click-ids ride raw as
Meta requires. These are our own web signups, so there's no Meta `lead_id` (optional).

**Idempotent:** the sync selects `WHERE meta_capi_sent_at IS NULL`, stamps each row on a
successful upload, and Meta dedups on `event_id` — so a re-run only sends new leads.
`--test <code>` routes to Events Manager **Test Events** and does **not** mark rows sent.

**Run it at least daily** (Meta expects ≥1 upload/day; events show in Events Manager within
~1h). Schedule `capi-sync` on the same OpenClaw cron cadence as the other analytics ticks.

To improve match quality later, capture `fbclid`→`fbc` on the signup form into
`metadata` — `build_user_data` already forwards `metadata.fbc`/`fbp` automatically.

## Setup (`code/analytics/.env`)
```
META_ADS_TOKEN=<System User token — ads_read to read, ads_management to create drafts>
META_AD_ACCOUNT_ID=2046577425934056        # act_ prefix optional
META_PAGE_ID=<Facebook Page id ads run from> # required for `draft --go`
META_PIXEL_ID=891355590685260              # pixel/dataset id — lead optimization + Conversions API target
META_CAPI_TOKEN=<dataset access token>       # Conversions API (capi-sync); falls back to META_ADS_TOKEN
META_CAPI_LEAD_SOURCE=News Impact Screener   # optional — the CRM name reported as lead_event_source
META_IG_ACCOUNT_ID=                          # optional — Instagram placements
META_SPECIAL_AD_CATEGORY=                    # optional — e.g. FINANCIAL_PRODUCTS_SERVICES if Meta requires it
META_API_VERSION=v21.0                        # optional; bump if a call reports a version error
# audience + objective defaults (override to change targeting):
META_TARGET_COUNTRIES=US,GB,CA,AU            # default geo
META_AGE_MIN=18
META_AGE_MAX=65
META_OBJECTIVE=OUTCOME_LEADS                 # optimize for sign-ups, not just clicks
META_OPTIMIZATION_GOAL=OFFSITE_CONVERSIONS   # LEAD conversions via the pixel; LINK_CLICKS for a cold-start
META_CONVERSION_EVENT=LEAD
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
