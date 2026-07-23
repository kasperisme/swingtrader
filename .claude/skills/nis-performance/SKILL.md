---
name: nis-performance
description: >-
  The unified performance foundation — wire every connected platform (GA4, Google Search
  Console, Meta Ads, Supabase leads, PostHog) into ONE cross-platform snapshot joined along
  the funnel, then turn it into a prioritised, ROUTED action list. Runs
  `services.performance` to pull each source (degrading gracefully if one is down), joins
  paid + organic + conversion on utm_content/feature with Supabase leads as the truth,
  computes cost-per-real-lead, and derives deterministic health flags each tagged with the
  skill/action that fixes it. Writes output/performance/<date>/snapshot.{json,md} — the
  JSON is the data foundation the action skills consume (nis-ad-image Step 0, SEO, CRO,
  conversion instrumentation); the MD is the analyst digest. Use when you want a whole-funnel
  read of the site's performance, to find the biggest leak/opportunity, or before authoring
  ads/content so decisions are grounded in real numbers.
---

# NIS Performance — the whole-funnel foundation

One place that answers *"how is the platform actually doing, and what should I do next?"*
by joining every wired data source along the funnel and routing each finding to the action
that fixes it. It does **no creative work** and takes **no actions** — it builds the
**data foundation** and the **prioritised, routed action list**; the action skills execute.

## What it wires together

| Platform | Module | What it contributes |
|---|---|---|
| **GA4** (Data API) | `services/google_analytics` | acquisition channels, landing-page engagement, key events |
| **Search Console** | `services/google_analytics` | organic queries, CTR/position, striking-distance SEO wins |
| **Meta Ads** | `services/meta_ads` | paid spend / clicks / impressions per feature (utm_content) |
| **Supabase leads** | `shared/db` | the **conversion truth** — real email/Telegram sign-ups |
| **PostHog** (on-site) | `services/posthog_analytics` | **on-site/CRO funnel** — pageviews → form viewed → submitted → subscribed, abandonment reasons, confirmed subscribes (server truth), download signal |
| *Vercel Analytics* | — | dashboard-only (no pull API); read it in the Vercel UI |

The join spine is the **funnel keyed on `utm_content` / feature**:
`paid impressions → clicks → (landing) → REAL leads → cost/lead` (Meta ⋈ Supabase),
alongside organic search (GSC) and channel mix + engagement (GA4).

## Step 1 — Build the foundation

```bash
cd code/analytics
.venv/bin/python -m services.performance.cli status               # which platforms are reachable
.venv/bin/python -m services.performance.cli snapshot --days 28   # build + write the foundation
```

`snapshot` writes **`output/performance/<date>/snapshot.{json,md}`** and prints the digest.
`status` shows wiring (the snapshot still runs if a platform is down — it uses what's live).

## Step 2 — Read the foundation (`snapshot.json`)

The JSON is the machine-readable contract. Top-level keys:
- `platforms` — availability/error per source.
- `funnel` — `paid` (impr/clicks/ctr/spend), `organic_search`, `ga4_sessions`, `real_leads`,
  `blended_cost_per_lead`.
- `efficiency[]` — per feature: `spend, clicks, ctr, real_leads, cost_per_lead, landing_cvr`
  (Meta ⋈ Supabase — the real cost per actual lead).
- `onsite` — the CRO funnel: `pageviews`, `form_funnel` (viewed→submitted→subscribed),
  `form_errors`, `confirmed_subscribes` (server truth), `downloads`,
  `client_funnel_instrumented` (false = you're blind on drop-off).
- `ga4` / `search_console` / `meta_ads` / `leads` / `onsite` — the raw normalized blocks
  (`ga4.form_funnel` = GA4's form_start/form_submit/sign_up).
- **`health_flags[]`** — the routed findings: `{severity, area, finding, action, route_to}`.

## Step 3 — Interpret as the growth analyst

Read the snapshot and produce a **short, ranked action list**. The discipline:
1. **Data-health first.** If a flag says GA4 is bot-inflated or conversions aren't tracked,
   say so *before* quoting any GA4 aggregate — untrusted numbers poison every downstream call.
2. **Follow the funnel to the biggest leak.** Compare `paid.clicks` → `real_leads`: a big
   drop with healthy CTR = a post-click (landing/form/message-match) problem, not a targeting one.
3. **Rank by leverage, not severity alone.** A fix that makes *other* numbers measurable
   (conversion instrumentation) outranks a local optimisation.
4. **Route every recommendation.** Each `health_flag.route_to` maps to where the work happens:

| `route_to` | Hand off to |
|---|---|
| `instrument-conversion` | Wire a `sign_up` event on the forms + mark it a GA4 Key event |
| `instrument-funnel` | Fix the client `lead_form_viewed/submitted/error` events so on-site drop-off is visible |
| `CRO` | Reduce form friction / message-match / earlier lead capture on high-traffic pages |
| `ga4-config` | Add a GA4 bot/data filter; identify the invalid-traffic source |
| `nis-ad-image` / CRO | Creative levers (curiosity gap, impact_list) + ad→landing message-match |
| `seo-content` | Title/meta rewrites on original-angle pages ranking p1-2 (`gsc.opportunities`) |
| `meta_ads` | Shift budget toward the cheaper cost-per-lead feature; new variant on the worse one |

Keep it to the few actions that matter; name the expected effect and the metric that proves it.

## Step 4 — It's the foundation other skills consume

- **`nis-ad-image` Step 0** already reads `meta_ads design --json`; point it at
  `snapshot.json → efficiency` for the cost-per-lead-by-feature picture too.
- SEO / CRO / conversion-instrumentation work starts from the routed flags here.
- Re-run it **weekly**, and **before** a content/ad push so decisions are grounded.

## Extending it — add a new platform

Coverage grows by adding one adapter — no rearchitecting:
1. Add a `<platform>_block(...)` to `services/performance/sources.py` returning
   `{"available": True, ...normalized data...}` (wrap the body so failures degrade to
   `{"available": False, "error": ...}`).
2. Include it in `snapshot.build_snapshot()` `blocks` + surface it in `to_markdown`.
3. If it implies an action, add a rule to `snapshot._flags()` with a `route_to`.

## Guardrails

- **Supabase leads are the conversion truth** — pixel/GA4 conversions can be missing or
  inflated; reconcile against real sign-ups.
- **Never quote a bot-inflated GA4 aggregate** without the caveat (the flag will tell you).
- **Meta figures are ACTIVE-only (live).** Paused/retired campaigns in the window are excluded
  from `efficiency`/`funnel` and reported separately (`meta_ads.paused_spend`), so a retired
  underperformer can't drag cost-per-lead (it once did — and misled the analysis). A
  `WITH_ISSUES` flag surfaces live disapproved/limited ads.
- The snapshot **reads only** — it never changes campaigns, spend, or content.
