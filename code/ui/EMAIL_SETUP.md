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

# Tutorial dialog
NEXT_PUBLIC_TUTORIAL_VIDEO_URL=        # YouTube embed URL, e.g. https://www.youtube.com/embed/abc123
NEXT_PUBLIC_TUTORIAL_PLAYLIST_URL=https://www.youtube.com/@newsimpactscreener
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
