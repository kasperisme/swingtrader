# performance

The unified cross-platform performance foundation. Pulls every wired platform,
joins them along the funnel, and derives **routed action flags**. Paired with the
`nis-performance` skill (the analyst layer).

```bash
cd code/analytics
.venv/bin/python -m services.performance.cli status               # platform wiring
.venv/bin/python -m services.performance.cli snapshot --days 28   # build + write foundation
.venv/bin/python -m services.performance.cli snapshot --json      # raw JSON to stdout
```

Writes `output/performance/<date>/snapshot.{json,md}`:
- **JSON** = the machine-readable foundation (funnel, per-feature cost-per-real-lead,
  raw platform blocks, `health_flags[]` each with a `route_to`). Action skills consume this.
- **MD** = the analyst digest.

Sources (each degrades gracefully — a dead platform doesn't sink the snapshot):

| Source | Module | Contributes |
|---|---|---|
| GA4 Data API | `services/google_analytics` | channels, landing engagement, key events |
| Search Console | `services/google_analytics` | organic queries, CTR/position, SEO opportunities |
| Meta Ads | `services/meta_ads` | paid spend/clicks/impressions by feature |
| Supabase leads | `shared/db` | real sign-ups — the conversion truth |
| PostHog | `services/posthog_analytics` | behavioural funnel + heatmaps (dashboard link) |

Join spine = the funnel keyed on `utm_content` / feature, with Supabase leads as truth.

**Add a platform:** add a `<name>_block()` adapter to `sources.py`
(`{"available": True, ...}` / graceful error), include it in `snapshot.build_snapshot()`,
and add a `_flags()` rule with a `route_to` if it implies an action.
