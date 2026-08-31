# Email Setup — Resend + Supabase

This project uses **Resend** for two things:

1. Transactional + campaign email from the app (waitlist welcome, future broadcasts).
2. SMTP relay for **Supabase auth emails** (signup confirmation, password reset, magic links) so they originate from `newsimpactscreener.com` instead of the default Supabase sender.

---

## 1. DNS — verify the domain in Resend

In the Resend dashboard → **Domains** → add `newsimpactscreener.com` and add the DNS records it provides:

| Type  | Purpose       | Notes                                      |
| ----- | ------------- | ------------------------------------------ |
| MX    | Resend MX     | Required                                   |
| TXT   | SPF           | `v=spf1 include:amazonses.com ~all` style  |
| TXT   | DKIM (`resend._domainkey`) | DKIM signing                  |
| TXT   | DMARC         | `v=DMARC1; p=none; rua=mailto:...`         |

Wait until Resend marks the domain **Verified** before sending. Until then, sends will fail with `domain not verified`.

---

## 2. Environment variables (Vercel + local)

```env
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
RESEND_FROM_EMAIL=News Impact Screener <noreply@newsimpactscreener.com>
RESEND_REPLY_TO=                       # optional — defaults to none
RESEND_WAITLIST_SEGMENT_ID=            # optional — see step 3
RESEND_WAITLIST_WELCOME_TEMPLATE_ID=   # stored-template ID or alias — see step 4
RESEND_WELCOME_TEMPLATE_ID=            # stored-template ID or alias — see step 4
NEXT_PUBLIC_APP_URL=https://newsimpactscreener.com
```

`RESEND_API_KEY` is the only required value. If `RESEND_WAITLIST_SEGMENT_ID` is unset, contacts simply aren't synced (errors are logged, not thrown).

---

## 3. Resend Segments (waitlist + users)

> Resend replaced the old **Audiences** primitive with **Segments** in late 2025. The Node SDK still accepts `audienceId` but it's deprecated — we use the new `segments: [{ id }]` shape via `lib/email/segments.ts`.

Create a Segment in the Resend dashboard (e.g. `Waitlist`) and copy its ID into `RESEND_WAITLIST_SEGMENT_ID`. The contact pool itself lives at the account level; segments are subsets you target with broadcasts. A contact can belong to zero or many segments.

The waitlist API route ([app/api/early-access/route.ts](app/api/early-access/route.ts)) calls `addToWaitlistSegment(email)` after each successful signup. Duplicates are treated as idempotent successes.

To send a campaign:

1. Resend dashboard → **Broadcasts** → **New broadcast**.
2. Pick the segment (e.g. `Waitlist`), compose, preview, send. No code required.

To slice further (e.g. "paid users only"), create another segment in Resend and either:
- Add a second env var like `RESEND_USERS_SEGMENT_ID` and a wrapper alongside `addToWaitlistSegment`, **or**
- Call `addContactToSegments({ email, segmentIds: [...] })` directly with multiple IDs.

If you later want programmatic broadcasts ("weekly recap to all paid users"), add `lib/email/campaigns.ts` and call `resend.broadcasts.create()`.

---

## 4. Welcome emails — Resend stored templates

Both welcome emails live in Resend (Dashboard → **Templates**), not in this codebase. Authoring them in Resend means you can edit copy without redeploying the app.

We use Resend's stored-template send API: the codebase only sends `template.id` + `variables`, and Resend renders the final email server-side. Each template's **From** and **Subject** come from the dashboard unless overridden in code (we don't override).

**General setup steps:**

1. Resend dashboard → **Templates** → **New template**.
2. Set a stable alias (e.g. `waitlist-welcome`) or copy the generated UUID.
3. Compose the email — Resend uses Handlebars-style `{{variableName}}` interpolation.
4. Declare the variables listed below on the template (sends fail if a referenced variable isn't declared on the template).
5. Set the template's **From** and **Subject** in the dashboard.
6. Publish.
7. Copy the alias or UUID into the matching env var below.

### 4a. Waitlist welcome (`RESEND_WAITLIST_WELCOME_TEMPLATE_ID`)

Sent from [app/api/early-access/route.ts](app/api/early-access/route.ts) when someone joins the waitlist. **Waitlist signups only collect email**, so the variable surface is small:

| Variable | Type   | Example                          |
| -------- | ------ | -------------------------------- |
| `email`  | string | `kasper@example.com`             |
| `appUrl` | string | `https://newsimpactscreener.com` |

If `RESEND_WAITLIST_WELCOME_TEMPLATE_ID` is unset, the email is skipped silently (the segment add still runs).

### 4b. Post-signup welcome (`RESEND_WELCOME_TEMPLATE_ID`)

Sent from [app/auth/confirm/route.ts](app/auth/confirm/route.ts) after `welcomeUserIfNeeded(user)` succeeds — fires after a successful OTP verification (signup, magic link, email change). Gated by `user_profiles.metadata.welcome_email_sent_at` so each user gets it at most once, regardless of which auth flow they came in through.

| Variable    | Type   | Example                          |
| ----------- | ------ | -------------------------------- |
| `firstName` | string | `Kasper`                         |
| `email`     | string | `kasper@example.com`             |
| `appUrl`    | string | `https://newsimpactscreener.com` |

`firstName` is derived from `user.user_metadata.first_name` / `name` / `full_name` if present, else the prettified email local-part, else `"trader"`.

If `RESEND_WELCOME_TEMPLATE_ID` is unset, the call returns silently — confirms still work without it.

---

## 5. Supabase Auth → Resend SMTP

This is **dashboard-only** — no code change required. In the Supabase project dashboard:

**Authentication → Emails → SMTP Settings** → toggle **Enable Custom SMTP** and enter:

| Field         | Value                                                |
| ------------- | ---------------------------------------------------- |
| Host          | `smtp.resend.com`                                    |
| Port          | `465`                                                |
| Username      | `resend`                                             |
| Password      | _your_ `RESEND_API_KEY`                              |
| Sender email  | `noreply@newsimpactscreener.com`                     |
| Sender name   | `News Impact Screener`                               |
| Minimum TLS   | TLS 1.2                                              |

**Authentication → Rate Limits** — bump "Emails per hour" if you expect signup bursts. Resend's free tier permits 100/day, 3000/month; paid tiers are higher.

**Authentication → Emails → Templates** — optionally edit the **Confirm signup**, **Reset password**, and **Magic Link** templates so they match the app's tone. Supabase substitutes `{{ .ConfirmationURL }}`, `{{ .Token }}`, `{{ .Email }}`.

After saving, send a test signup from a fresh email and confirm:
- The email arrives from `noreply@newsimpactscreener.com`.
- The Resend dashboard → **Logs** shows the message.
- Clicking the link redirects through `/auth/confirm` and lands the user on `/protected`.

---

## 6. Local development

For local testing without burning Resend quota, leave `RESEND_API_KEY` unset — `sendTemplateEmail()` returns `{ ok: false, error: "Missing RESEND_API_KEY" }` and the early-access / confirm routes log the failure and continue. Signups themselves still work.

To preview a template, use Resend's dashboard preview — it renders the same template that the API will send, with mock variables you control.

---

## 7. Files

| File                                              | Purpose                                                       |
| ------------------------------------------------- | ------------------------------------------------------------- |
| `lib/email/client.ts`                             | Resend singleton + env constants                              |
| `lib/email/send.ts`                               | `sendEmail()` (HTML) + `sendTemplateEmail()` (stored template) |
| `lib/email/segments.ts`                           | `addContactToSegments()` + `addToWaitlistSegment()`           |
| `lib/email/welcome-user.ts`                       | Post-signup welcome dispatch with metadata-flag dedupe        |
| `app/api/early-access/route.ts`                   | Sends waitlist welcome (template) + adds to segment           |
| `app/auth/confirm/route.ts`                       | Fires `welcomeUserIfNeeded()` after OTP verify                |

---

## 8. Broadcasts — the "narrative trading" campaign

Section 3 said programmatic broadcasts would need a `campaigns.ts`. They now live in
[lib/email/broadcasts.ts](lib/email/broadcasts.ts), and the first campaign is wired end
to end in [scripts/broadcast-narrative-trading.ts](scripts/broadcast-narrative-trading.ts).

A broadcast differs from the transactional sends above in three ways: it targets a
**Segment** instead of an address list, Resend appends its own unsubscribe handling
(so the body uses the `{{{RESEND_UNSUBSCRIBE_URL}}}` merge tag, not our signed token),
and creation is decoupled from sending. `createBroadcastDraft()` only ever creates a
**draft** — there is deliberately no `send: true` path in the module, so pressing send
is always a human click in the Resend dashboard.

### The audience is rebuilt from Supabase, not trusted

Only `/api/early-access` ever called `addToWaitlistSegment`, so the Resend segment has
never held the screening or briefing subscribers. The script therefore reconstructs the
reachable list from three tables:

| Table | Contributes | Opt-out column |
| ----- | ----------- | -------------- |
| `early_access_signups` | the master list (other paths mirror into it) | — none |
| `market_screening_email_subscriptions` | screening-results subscribers | `unsubscribed_at`, `status` |
| `news_briefing_subscriptions` | daily-briefing subscribers | `unsubscribed_at`, `status` |

An opt-out in *either* lead-magnet table suppresses the address everywhere — these
people signed up for "email from News Impact Screener", not for one specific list.
`early_access_signups` carries no unsubscribe state of its own, which is exactly why it
cannot be used alone.

### Running it

```bash
cd code/ui
npx tsx --env-file=.env.local scripts/broadcast-narrative-trading.ts preview
npx tsx --env-file=.env.local scripts/broadcast-narrative-trading.ts audience --dry-run
npx tsx --env-file=.env.local scripts/broadcast-narrative-trading.ts audience
npx tsx --env-file=.env.local scripts/broadcast-narrative-trading.ts test you@example.com
npx tsx --env-file=.env.local scripts/broadcast-narrative-trading.ts draft
```

- **preview** — pulls the hero reconstruction live from `swingtrader.research_priced_in`,
  renders, and writes `output/broadcasts/narrative-trading.{html,txt}` (gitignored).
  Touches no API. Every number in the email comes from this query, so rebuilding the day
  before you send picks up whatever the nightly batch last promoted.
- **audience** — reports the reachable list by source, then upserts each address into the
  `Narrative Trading Launch` segment, creating it if absent. Prints the segment id to put
  in `RESEND_BROADCAST_SEGMENT_ID`.
- **test** — sends the rendered email to one address as a normal transactional send.
  The `{{{RESEND_UNSUBSCRIBE_URL}}}` tag will render literally; that is expected, only
  a real broadcast substitutes it.
- **draft** — creates the broadcast against the segment and prints its dashboard URL.

Override the hero with `BROADCAST_HERO_TICKER=SHOP`. The script refuses any ticker whose
published row lacks a crux, a `pays_for` list, or unpriced drivers, so a bad hero fails
loudly at build time rather than shipping a hollow email.

### What the email is allowed to claim

It is an offer email: you were early, that earns the founding rate, the rate is held
until a date. Three claims are load-bearing, and the script refuses to render if any
stops being true rather than letting it drift:

- **"One of the first 100."** A claim about the reader, not a slogan. `build()` throws
  once the reachable list passes `FIRST_N_CLAIM_CEILING` (115 — slack because the
  reachable list excludes opt-outs while "sign-ups" counts everyone).
- **"$9/$19 → $29/$49."** Straight off the Phase 1 and Phase 2 columns of
  `app/pricing/page.tsx`. That is more than a doubling, so the email prints the four
  numbers rather than characterising the jump.
- **"Its price endorses none of them."** True only while the hero row's `n_endorsed`
  is 0. The nightly batch can change that under you, so `loadHero()` throws and tells
  you to pick another hero rather than shipping the line stale.

**The deadline is yours, not the pricing page's.** Phase 2 triggers on user count, not
on a date, so the copy says *"I'm holding it for this list until <date>"* — a promise
you control and can keep — never *"the price goes up on Monday"*, which would be false.
Defaults to the coming Sunday; override with `BROADCAST_DEADLINE="Friday, September 4"`.
Honour it, or the next deadline you set means nothing.

### Before the first send

- **Add a physical postal address** to the Resend broadcast footer (Resend →
  Settings → Branding). CAN-SPAM requires one on commercial email and the template
  does not carry it; the app has no business address anywhere in the codebase.
- **Warm the domain.** `noreply@newsimpactscreener.com` has only sent transactional
  volume. ~100 recipients in one shot is fine, but send the test first and check it
  does not land in Promotions/Spam.
- **Use a replyable From.** The P.S. asks people to reply. `RESEND_REPLY_TO` is unset,
  and `noreply@` bins the replies the campaign is explicitly soliciting.
