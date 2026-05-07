<wizard-report>
# PostHog post-wizard report

The wizard has completed a deep integration of PostHog analytics into the newsimpactscreener Next.js app. The project already had `posthog-js` installed and a solid foundation (`lib/analytics/posthog.ts`, `lib/analytics/AnalyticsProvider.tsx`, `lib/analytics/events.ts`) with pageview tracking and user identification wired up. This run wired up all the missing `track()` call sites, added server-side event tracking via `posthog-node`, fixed the EU region proxy config, and extended the EventMap with new event types.

## Changes made

| File | Change |
|------|--------|
| `next.config.ts` | Fixed `/ingest` proxy to point to EU endpoints (`eu.i.posthog.com`, `eu-assets.i.posthog.com`); added `/array/` route |
| `lib/analytics/posthog.ts` | Changed `ui_host` from `us.posthog.com` → `eu.posthog.com` |
| `lib/analytics/server.ts` | **New file** — `posthog-node` server-side client using `POSTHOG_HOST` env var |
| `lib/analytics/events.ts` | Extended `EventMap` with `waitlist_joined`, `checkout_initiated`, `api_key_created`, `api_key_revoked`, `onboarding_completed`; updated `trade_logged` to include `ticker` + `side` |
| `.env.local` | Set `NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST`, `POSTHOG_HOST` |
| `.env.example` | Added `POSTHOG_HOST` entry |
| `components/sign-up-form.tsx` | `signup_completed` + `ph.identify()` on successful signup |
| `components/login-form.tsx` | `login` + `ph.identify()` on successful login |
| `components/pricing-checkout-button.tsx` | `upgrade_clicked` with `to_plan` and `surface` on each CTA click |
| `app/api/stripe/checkout/route.ts` | Server-side `checkout_initiated` with `plan`, `interval`, `session_id` |
| `app/api/early-access/route.ts` | Server-side `waitlist_joined` with `source` |
| `app/protected/api-keys/api-keys-ui.tsx` | `api_key_created` with `scopes`; `api_key_revoked` on revoke |
| `app/protected/trades/trades-ui.tsx` | `trade_logged` with `trade_id`, `ticker`, `side` on successful insert |
| `app/protected/agents/agents-ui.tsx` | `agent_created` with `agent_id` + `kind`; `agent_run` (×2 call sites) with `manual: true` |
| `app/protected/_components/welcome-dialog.tsx` | `onboarding_completed` with `skipped` flag on dismiss |

## Events summary

| Event | Description | File |
|-------|-------------|------|
| `signup_completed` | User successfully creates a new account via email | `components/sign-up-form.tsx` |
| `login` | User logs in with email/password or OAuth (X) | `components/login-form.tsx` |
| `upgrade_clicked` | User clicks a plan checkout button on the pricing page | `components/pricing-checkout-button.tsx` |
| `checkout_initiated` | Server: Stripe checkout session created for a user subscription | `app/api/stripe/checkout/route.ts` |
| `waitlist_joined` | Anonymous visitor submits the early access waitlist form | `app/api/early-access/route.ts` |
| `api_key_created` | User creates a new API key | `app/protected/api-keys/api-keys-ui.tsx` |
| `api_key_revoked` | User revokes an existing API key | `app/protected/api-keys/api-keys-ui.tsx` |
| `trade_logged` | User logs a trade entry in the portfolio tracker | `app/protected/trades/trades-ui.tsx` |
| `agent_created` | User creates a new scheduled screening agent | `app/protected/agents/agents-ui.tsx` |
| `agent_run` | User manually triggers a test run of a scheduled agent | `app/protected/agents/agents-ui.tsx` |
| `onboarding_completed` | User dismisses the welcome onboarding dialog after first login | `app/protected/_components/welcome-dialog.tsx` |

## Next steps

We've built a dashboard and 5 insights to monitor user behavior based on the instrumented events:

**Dashboard:** https://eu.posthog.com/project/173874/dashboard/665302

**Insights:**
- [Signups over time](https://eu.posthog.com/project/173874/insights/eaALprqE) — Daily signup trend
- [Waitlist growth](https://eu.posthog.com/project/173874/insights/2JNp0stD) — Early access form submissions
- [Pricing → Signup conversion funnel](https://eu.posthog.com/project/173874/insights/fH5tx8F2) — How many upgrade clicks convert to signups
- [Checkout initiated](https://eu.posthog.com/project/173874/insights/FqLAmOIq) — Stripe checkout sessions by plan (revenue signal)
- [User engagement (trades + agent runs)](https://eu.posthog.com/project/173874/insights/ZJUViYmR) — Daily active usage across core features

### Agent skill

We've left an agent skill folder in your project. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.

</wizard-report>
