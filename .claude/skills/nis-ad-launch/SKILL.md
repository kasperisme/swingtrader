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
nis-ad-image     →  output/ads/<slug>/1x1/ad.png + ad.json           (the creative — default)
 (or carousel)      output/ads/<slug>/1x1/slide-*.png                (legacy swipe deck)
        │
        ▼
   preflight      →  check every account/permission gate (green/red)
        │
        ▼
   draft (dry-run)→  print the exact campaign/ad-set/ad plan, nothing created
        │
        ▼
   draft --go     →  1 campaign → 1 ad set/feature → 1 single-image ad/feature, all PAUSED
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
META_IG_ACCOUNT_ID=<IG business account id> # optional — explicit @handle byline on IG placements
META_DSA_BENEFICIARY=News Impact Screener   # optional — EU DSA payor/beneficiary (required for DK targeting)
META_SPECIAL_AD_CATEGORY=                    # optional — e.g. FINANCIAL_PRODUCTS_SERVICES if Meta demands it
META_API_VERSION=v21.0                        # optional
```

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
.venv/bin/python -m services.meta_ads.cli draft            # prints the plan, creates NOTHING
```

Confirms it can read each `output/ads/<slug>/1x1/` folder and prints the campaign → ad-set →
ad tree with budgets, CTAs, and destinations. **The 1:1 image must exist** — render it first
with `nis-ad-image` (writes `1x1/ad.png`). (Legacy: multiple `1x1/slide-*.png` are still
uploaded as a carousel if present.)

## Step 3 — Create the PAUSED drafts

```bash
.venv/bin/python -m services.meta_ads.cli draft --go --budget 70   # DKK/day per ad set (default 70)
```

Creates the campaign (`OUTCOME_TRAFFIC`, PAUSED) → one ad set per feature (DK 18–65, optimize
`LINK_CLICKS`, isolated daily budget) → one single-image ad per feature (uploads `1x1/ad.png`,
builds the `object_story_spec` link ad with the headline/description, attaches the CTA + UTM'd
destination). If **any** step fails it **rolls back the whole campaign** — no orphans. On
success it prints every id.

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

## Notes & guardrails

- **PAUSED is the contract.** Campaign, ad sets, and ads are all created PAUSED. This skill
  never sets anything Active — launching is always a deliberate human click in Ads Manager.
- **One campaign, two ad sets = the A/B.** Don't collapse the features into one ad set; the
  isolated-budget split is the whole point of the test.
- **Creative is upstream.** This skill assumes `nis-ad-image` already wrote
  `output/ads/<slug>/1x1/ad.png` + `ad.json`. If they're missing, render them first — don't
  invent creative here.
- **Change the feature set** by editing `campaigns.FEATURES` (the `<slug>` list) — it maps
  directly to `output/ads/<slug>/`.
- **Budget** is per ad set per day, in DKK, via `--budget` (default 70). Start small; scale the
  winner after `reconcile`, not before.
- **Never echo the token.** All diagnostics here read via the API; none print `META_ADS_TOKEN`.
```
