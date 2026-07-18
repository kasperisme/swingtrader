---
name: nis-ad-launch
description: >-
  Launch rendered ads into Meta (Facebook/Instagram) Ads Manager as PAUSED, non-spending
  campaign drafts — the paid last mile after nis-ad-image produces the creative. Runs a
  one-command preflight that checks every account/permission gate, then creates one
  campaign → one ad set per feature → one single-image ad per feature via the Marketing
  API, all PAUSED (cannot spend until you flip them Active by hand). Also the measurement
  half: per-ad insights + reconcile Meta spend against REAL Supabase leads → cost per
  actual lead. Use when the user wants to "launch/run/create the Meta ads", "push the ad
  to Ads Manager", "create the ad drafts", or set up the feature A/B. NOT for producing
  the creative (that's nis-ad-image) and NOT for organic posting (that's social_publishing).
---

# NIS Ad Launch

The **paid last mile**. `nis-ad-image` renders the creative; this skill uploads it into
Meta Ads Manager as **PAUSED drafts** and measures the result. It does *no creative work* —
it reads the rendered image + `ad.json` off disk and calls the Marketing API.

Everything it creates is **PAUSED and cannot spend a krone** until you manually set it Active
in Ads Manager. There is no auto-launch — that's deliberate.

Backed by `code/analytics/services/meta_ads/` (see its README). The launch is a **write**
path (`ads_management`); the measurement is read-only.

---

## The pipeline

```
nis-ad-image     →  output/ads/<date>-<short-name>/<lead-magnet>/1x1/ad.png + ad.json
 (or build_ad_reel)  …/<lead-magnet>/9x16/ad_reel.mp4 (+poster)   → launches as a VIDEO ad
                    <lead-magnet> ∈ { briefing, market-screening }        (the creative)
        │
        ▼
   preflight      →  check every account/permission gate (green/red)
        │
        ▼
   draft (dry-run)→  print the exact campaign/ad-set/ad plan, nothing created
        │
        ▼
   draft --go     →  1 campaign (the folder) → 1 ad set per lead-magnet → 1 ad each, PAUSED
                    (single image, or a reel auto-uploaded to Meta — no manual upload)
        │
        ▼
   YOU in Ads Mgr →  review creative/targeting/budget, then flip Active to launch
        │
        ▼
   insights /     →  per-ad CTR/CPC/spend + cost-per-REAL-lead by feature
   reconcile
```

The two features are the **A/B**: `feat-screening-v1` (market screening → `/marketscreenings`)
vs `feat-news-v1` (custom news screener → `/briefings`). Budgets are **isolated per ad set**
(`is_adset_budget_sharing_enabled=false`) so the test stays unbiased — Meta can't shift
spend to the early leader. Each ad's `utm_content` (`market_screening` / `news_briefing`) is
what `reconcile` groups by, so the loop closes on **real leads**, not just clicks.

---

## Step 0 — One-time setup (`code/analytics/.env`)

```
META_ADS_TOKEN=<System User token — ads_management + pages_read_engagement + pages_manage_ads>
META_AD_ACCOUNT_ID=2046577425934056        # act_ prefix optional
META_PAGE_ID=<Facebook Page id ads run from>
META_PIXEL_ID=891355590685260              # web Pixel id — REQUIRED for lead optimization (the default)
META_IG_ACCOUNT_ID=<IG business account id> # optional — explicit @handle byline on IG placements
META_DSA_BENEFICIARY=News Impact Screener   # optional — EU DSA payor/beneficiary (required if EU in geo)
META_SPECIAL_AD_CATEGORY=                    # optional — e.g. FINANCIAL_PRODUCTS_SERVICES if Meta demands it
META_API_VERSION=v21.0                        # optional
# ── audience + objective defaults (override to change targeting) ──
META_TARGET_COUNTRIES=US,GB,CA,AU           # default geo (English-speaking, matches a US-stock product)
META_AGE_MIN=18
META_AGE_MAX=65
META_OBJECTIVE=OUTCOME_LEADS                # default: optimize for sign-ups, not just clicks
META_OPTIMIZATION_GOAL=OFFSITE_CONVERSIONS  # LEAD conversions via the pixel; set LINK_CLICKS for a cold-start
META_CONVERSION_EVENT=LEAD                  # the pixel event to optimize toward
```

**The default audience + goal:** `US, GB, CA, AU · 18–65 · broad` (Advantage+ expands it),
campaign objective **`OUTCOME_LEADS`**, ad sets optimizing for the **LEAD pixel conversion** —
i.e. Meta optimizes for *sign-ups*, not cheap clicks. All of it is env-overridable (e.g.
`META_TARGET_COUNTRIES=US` to narrow, or `META_OPTIMIZATION_GOAL=LINK_CLICKS` to fall back to
clicks). **Cold-start caveat:** conversion optimization needs pixel Lead volume (~50/week) to
exit Meta's learning phase — with a fresh pixel it may under-deliver at first. If the pixel has
near-zero Lead history, start on `LINK_CLICKS` (or `LANDING_PAGE_VIEWS`) and switch to
conversions once leads accrue.

The token is a **System User** token (Business Settings → System Users). It's a secret even
though half its use is read-only — never print or commit it (`.env` is gitignored).

---

## Step 1 — Preflight (do this before every first launch)

```bash
cd code/analytics
.venv/bin/python -m services.meta_ads.cli preflight
```

It checks — in one pass — every gate that has actually blocked a launch: token scopes, ad
account status, **Page assigned to the token** with CREATE_CONTENT, and **IG advertisability**.
Green means safe to create. Two gates can't be checked via API and are printed as reminders
(App must be **Live**; EU/DSA — handled in code). Fix everything red before `--go`; the
"Gate reference" table below maps each failure to its exact fix.

## Step 2 — Dry-run the plan

```bash
# a trend campaign (the dated folder → the campaign; its magnet subfolders → the ad sets):
.venv/bin/python -m services.meta_ads.cli draft --campaign 2026-07-14-geopolitics
# or the legacy flat product A/B (campaigns.FEATURES):
.venv/bin/python -m services.meta_ads.cli draft
```

`--campaign <date>-<short-name>` discovers the `briefing/` + `market-screening/` subfolders
under `output/ads/<date>-<short-name>/` and prints the campaign → ad-set → ad tree with
budgets, CTAs, and destinations. **Each magnet's 1:1 image must exist** — render it first with
`nis-ad-image` (writes `<magnet>/1x1/ad.png`). Creates NOTHING.

## Step 3 — Create the PAUSED drafts

```bash
.venv/bin/python -m services.meta_ads.cli draft --campaign 2026-07-14-geopolitics --go --budget 70
```

Creates the campaign (named after the folder, `OUTCOME_LEADS`, PAUSED) → one ad set per
lead-magnet (US/GB/CA/AU 18–65, optimize **LEAD conversions** via the pixel, isolated daily
budget) → one single-image ad
per magnet (uploads `<magnet>/1x1/ad.png`,
builds the `object_story_spec` link ad with the headline/description, attaches the CTA + UTM'd
destination). If **any** step fails it **rolls back the whole campaign** — no orphans. On
success it prints every id and writes **`output/ads/<campaign>/launch_manifest.json`** — one
row per ad joining the Meta `ad_id` to that ad's `design.json` (the creative genome), so you
can later correlate design choices with engagement (see Step 5).

If `META_IG_ACCOUNT_ID` is set and valid, ads carry the explicit `@handle` (via
`instagram_user_id`); if that identity is rejected (e.g. the IG account's "less personalized
ads" setting), the run **falls back to Page-only** automatically — still eligible for IG
placements, just without the byline.

## Step 4 — You launch (manual, on purpose)

Open **Ads Manager → the "Feature A/B — screener vs news" campaign**. Review the creative,
targeting, and budgets. Flip each **ad set to Active** to start delivery. Nothing spends until
you do this.

## Step 5 — Measure the A/B

```bash
.venv/bin/python -m services.meta_ads.cli insights   [--since YYYY-MM-DD]   # per-ad CTR/CPC/spend/leads, rolled up by feature
.venv/bin/python -m services.meta_ads.cli reconcile  [--since YYYY-MM-DD]   # Meta spend/clicks vs REAL Supabase leads → $/lead
```

`reconcile` is the source of truth: it puts Meta spend next to the **actual email leads**
captured on the subscribe forms (pixel-independent), by feature. Scale the feature with the
lower cost-per-real-lead; feed the winner back into the next `nis-ad-image` spec.

**What drives engagement (design × performance).**

```bash
.venv/bin/python -m services.meta_ads.cli design                       # per-ad: performance + its design
.venv/bin/python -m services.meta_ads.cli design --by hook_type        # roll up by one design field
.venv/bin/python -m services.meta_ads.cli design --leaderboard --min-impr 500   # rank every lever, best first
.venv/bin/python -m services.meta_ads.cli design --json --min-impr 500          # machine-readable → next ad
```

Traceability runs on the Meta **`ad_id`**: `create_ad()` returns it, `launch_manifest.json`
stores it next to that ad's `design` genome, and `insights` is reported by the same `ad_id`.
`design` performs the join — so you see which *creative choices* lift CTR/CPL (dark vs light,
proof vs none, `hook_type` question vs number-drop, bullet count, copy length). It works even
before delivery (metrics show 0), so you can confirm the loop is wired the moment you create
the drafts. `--leaderboard` ranks every lever best-first (low-sample rows flagged); `--json`
is what `nis-ad-image` Step 0 reads to bias the next ad. Vary one lever per `variant` so the
lift is attributable, respect `--min-impr` (ignore noise), and bake winners into the next spec.

---

## Gate reference — every real blocker, and its fix

These are the errors this flow has hit, in the order Meta surfaces them. `preflight` catches
the API-checkable ones; the last two it can only remind you about.

| Symptom (Meta error) | Root cause | Fix |
|---|---|---|
| `is_adset_budget_sharing_enabled` must be true/false | campaign field required | handled in code (`false` = isolated A/B budgets) |
| App is in **development mode** … must be public | Meta App not Live | developers.facebook.com → your App → **App Mode → Live** (needs a Privacy Policy URL) |
| **No permission to access this profile** (code 10) | Page not assigned to the System User | Business Settings → System Users → assign the **Page** with `ADVERTISE` + `CREATE_CONTENT` |
| Ad account does **not have access to Instagram** (1815199) | IG not linked to the ad account | Business Settings → Instagram accounts → assign the ad account |
| **No advertiser indicated** (DSA, 3858081) | EU targeting needs beneficiary/payor | handled in code via `META_DSA_BENEFICIARY` (default "News Impact Screener") |
| `instagram_actor_id must be a valid Instagram account id` | field renamed in v21+ | handled in code — uses `instagram_user_id` |
| **less-personalized ads** … cannot create ads (3858412) | that IG account opted out of ad personalization | IG → Accounts Center → Ad preferences → turn **off** "less personalized ads" — or accept the Page-only fallback |
| requires a **special ad category** | financial audience | set `META_SPECIAL_AD_CATEGORY=FINANCIAL_PRODUCTS_SERVICES` in `.env` |

---

## SIEP — keep trend ads out of the "social issues, elections or politics" bucket

Our trend ads routinely hook on **social-issue-adjacent** topics — geopolitics/war, inflation
and the economy, energy/climate, immigration, health. Meta classifies ads that are *about*
such issues as **SIEP** ([Social Issues, Elections or Politics](https://transparency.meta.com/policies/ad-standards/SIEP-advertising/SIEP/)),
and SIEP ads require the advertiser to complete **SIEP authorization** (identity + government-ID
verification) and carry a verified **"Paid for by" disclaimer**. **This flow sets up neither.**
An ad detected as SIEP without them is **disapproved at review** (and repeat hits risk the ad
account), and **SIEP ads cannot run in the EU at all**.

**The way through is the product exemption, not authorization.** Meta exempts an ad from SIEP
authorization + disclaimer when the **product/service is prominently named or shown and the ad's
primary purpose is to sell/promote it — even if it references a social issue.** Our lead-magnet
ads already qualify by design; the job here is to *keep* them qualifying. Before `draft --go`,
check the creative (`ad.json` + the rendered image/reel) against these rules:

- **Product-first, never advocacy.** The briefing / the screener must be the visible subject and
  the CTA, and the ad's purpose must be *get the signup*. Report the topic as **market/trading
  news the product tracks** ("inflation cooled — follow it here"); never argue a **position** on a
  policy, party, candidate, election, or legislation ("tell the Fed to cut rates" would be SIEP).
- **No elections/candidates/legislation, ever, through this flow.** If a week's trend is a vote, a
  candidate, a ballot measure, or a named bill, **stop** — that's core SIEP, not exemptible; it
  needs full authorization + a disclaimer this flow doesn't create. Pick a different angle or skip.
- **Don't take the issue's side in copy or art.** Headline, `primary_text`, bullets, and the reel
  scene must stay neutral-informational (the *market* read), not persuasive on the issue itself.
- **Never target the EU with a social-issue hook.** SIEP ads are banned in the EU — keep
  `META_TARGET_COUNTRIES` on the `US,GB,CA,AU` default (no EU) for topic-driven campaigns. (The
  DKK ad **account** is fine; only the **audience geo** triggers the EU ban.)
- **If you're unsure it clears the exemption, treat it as SIEP:** either reframe the creative to be
  unambiguously product-first, or get the business SIEP-authorized with a "Paid for by" disclaimer
  first. Don't gamble a disapproval or an account flag on a borderline hook.

`preflight` can't detect SIEP (Meta decides at review) — it's a **human check on the creative**
before `--go`, same as the App-Live / DSA reminders.

---

## Notes & guardrails

- **PAUSED is the contract.** Campaign, ad sets, and ads are all created PAUSED. This skill
  never sets anything Active — launching is always a deliberate human click in Ads Manager.
- **SIEP check before `--go`.** Trend hooks (geopolitics, the economy, energy, immigration) can
  trip Meta's social-issues policy — verify the creative stays product-first and EU is out of the
  geo. See the **SIEP** section above; it's a mandatory human review, not an API gate.
- **One campaign, two ad sets = the A/B.** Don't collapse the features into one ad set; the
  isolated-budget split is the whole point of the test.
- **Creative is upstream.** This skill assumes `nis-ad-image` already wrote each
  `output/ads/<date>-<short-name>/<lead-magnet>/1x1/ad.png` + `ad.json` (or `build_ad_reel`
  wrote `9x16/ad_reel.mp4` + poster). If they're missing, render them first.
- **Reels launch automatically.** If `9x16/ad_reel.mp4` exists it's launched as a **video
  ad** (preferred over the static image): the reel is uploaded to Meta (`/advideos`,
  Meta-hosted — no manual upload, no Supabase), processing is awaited, the poster becomes the
  thumbnail, and a `video_data` creative is built — all inside `draft --go`. Force the static
  with `"launch_as": "image"` in `ad.json`. The design/manifest traceability is identical
  (the reel writes its own `design.json` with `format: reel`).
- **Saving convention.** A campaign is the `<date>-<short-name>` folder; its `briefing/` and
  `market-screening/` subfolders are the ad sets. Add a magnet by adding a subfolder with an
  `ad.json` + `1x1/ad.png`. (The legacy flat product A/B still runs via `campaigns.FEATURES`
  when `--campaign` is omitted.)
- **Budget** is per ad set per day, in DKK, via `--budget` (default 70). Start small; scale the
  winner after `reconcile`, not before.
- **Never echo the token.** All diagnostics here read via the API; none print `META_ADS_TOKEN`.
```
