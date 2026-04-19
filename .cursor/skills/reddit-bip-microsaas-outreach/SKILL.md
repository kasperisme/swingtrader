---
name: reddit-bip-microsaas-outreach
description: >-
  Screens r/buildinpublic and r/microsaas for threads that invite people to share
  or showcase projects, then drafts or posts a helpful comment mentioning
  https://www.newsimpactscreener.com/ with a link. Covers Reddit OAuth (read vs
  write), matching heuristics, rate limits, and self-promotion / spam risks. Use
  when the user asks about Reddit outreach, share-your-build threads, BIP,
  microsaas subs, or automated commenting for News Impact Screener.
---

# Reddit: BIP + MicroSaaS “share your project” outreach

Operational playbook for finding invitation-style threads in **`r/buildinpublic`** and **`r/microsaas`**, then leaving a **single, contextual** comment that points builders to [News Impact Screener](https://www.newsimpactscreener.com/) when it genuinely fits the thread.

**Runnable script (next to this skill):** `.cursor/skills/reddit-bip-microsaas-outreach/reddit_bip_microsaas_outreach.py` — loads `code/analytics/.env` by walking up from the skill directory (or set **`REDDIT_ENV_FILE`**). Uses `REDDIT_CLIENT_ID`, `REDDIT_SECRET`, optional `REDDIT_USER_AGENT`; for posting, **`REDDIT_REFRESH_TOKEN`** or **`REDDIT_USERNAME` + `REDDIT_PASSWORD`**. Default **`REDDIT_DRY_RUN=1`**. Example from repo root: `python3 .cursor/skills/reddit-bip-microsaas-outreach/reddit_bip_microsaas_outreach.py`.

## Preconditions (read this first)

1. **Commenting is user-authenticated (Reddit-enforced).** Listing public posts works with **`client_credentials`** (`client_id` + `REDDIT_SECRET` only). **`POST /api/comment` rejects application-only tokens** with `USER_REQUIRED` / “Please log in to do that.” — there is no supported way to comment as an anonymous “app”; every comment is tied to a user account. Use either **`REDDIT_REFRESH_TOKEN`** (refresh grant: no password in env after a one-time OAuth in the browser) or **`REDDIT_USERNAME` + `REDDIT_PASSWORD`** (script password grant). Never commit passwords or long-lived tokens to git; use env vars or a secrets manager.
2. **Policy and etiquette.** Reddit and many subs restrict **self-promotion** and repetitive linking. Automated drive-by comments are often reported as spam and can lead to **subreddit bans** or **account sanctions**. Before any automation:
   - Read each sub’s **rules** and pinned threads (many use a **weekly** “share your project” megathread).
   - Prefer **one thoughtful comment per thread**, when the post explicitly invites sharing, and the product is **directly relevant** (news ↔ tickers research for founders sharing a SaaS or build).
   - Add **cooldowns**, **manual review**, or a **dry-run** mode that only prints matches and draft comments.
3. **Rotate credentials** if client id, `REDDIT_SECRET`, or passwords ever appeared in chat, logs, or CI output.

## Environment variables

| Variable | Required for | Notes |
|----------|----------------|-------|
| `REDDIT_CLIENT_ID` | Token requests | From [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) |
| `REDDIT_SECRET` | Token requests | Reddit app **client secret** (labelled “secret” in prefs/apps). Use this env name in scripts and analytics `.env`; do not use `REDDIT_CLIENT_SECRET` unless you alias it yourself. |
| `REDDIT_REFRESH_TOKEN` | **Posting comments (preferred)** | From OAuth **authorization code** flow (or any flow that returns a refresh token). Script + `grant_type=refresh_token` yields a **user** access token without storing the account password in `.env`. |
| `REDDIT_USERNAME` | **Posting comments** | Only if not using `REDDIT_REFRESH_TOKEN`. Account for the script app. |
| `REDDIT_PASSWORD` | **Posting comments** | Only if not using `REDDIT_REFRESH_TOKEN`. If 2FA is on, use an **app password** where Reddit supports it. |
| `REDDIT_USER_AGENT` | All calls | Reddit requires a descriptive UA, e.g. `NewsImpactScreenerOutreach/1.0 by /u/YourUsername` |

Optional: `REDDIT_DRY_RUN=1` to never POST comments (agent should respect if implementing a script).

## OAuth: get tokens

**Read-only (listings, no comment):**

```http
POST https://www.reddit.com/api/v1/access_token
User-Agent: ${REDDIT_USER_AGENT}
Authorization: Basic base64("${REDDIT_CLIENT_ID}:${REDDIT_SECRET}")
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
```

**User context (comment, vote as you)** — pick one:

*Refresh (no password in env on each run):*

```http
POST https://www.reddit.com/api/v1/access_token
User-Agent: ${REDDIT_USER_AGENT}
Authorization: Basic base64("${REDDIT_CLIENT_ID}:${REDDIT_SECRET}")
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&refresh_token=${REDDIT_REFRESH_TOKEN}
```

*Password grant (script app):*

```http
POST https://www.reddit.com/api/v1/access_token
User-Agent: ${REDDIT_USER_AGENT}
Authorization: Basic base64("${REDDIT_CLIENT_ID}:${REDDIT_SECRET}")
Content-Type: application/x-www-form-urlencoded

grant_type=password&username=${REDDIT_USERNAME}&password=${REDDIT_PASSWORD}
```

Use the returned `access_token` as `Authorization: bearer ...` on `oauth.reddit.com` requests. **`client_credentials` alone will not work for `POST /api/comment`.**

## Fetch latest posts from both subreddits

**Combined feed (new):**

`GET https://oauth.reddit.com/r/buildinpublic+microsaas/new.json?limit=50`

Also consider **`/hot`** or sub-specific **weekly megathreads** (often `sticky` or title contains “Weekly” / “Share”); adjust if the goal is megathreads only.

Parse JSON: `data.children[]` → `data.kind === "t3"` (link/text post) → use `data.title`, `data.selftext`, `data.created_utc`, `data.name` (fullname, e.g. `t3_abc123` for `thing_id` when commenting), `data.permalink`.

## Identify “share your project” style posts

Treat matching as **heuristic + human-in-the-loop** unless the user explicitly accepts false positives/negatives.

**High-signal phrases** (title or selftext, case-insensitive; any can trigger a *candidate*):

- `share your project`, `share what you're building`, `share what you are building`
- `show your`, `show us your`, `showcase`
- `what are you building`, `what are you working on`
- `drop your`, `link your`, `post your`, `promote your` (use with care; can be negative context)
- `roast my`, `feedback on`, `critique my`, `tear down` (often build-in-public style)
- `side project`, `indie`, `microsaas`, `SaaS` combined with `built`, `launched`, `beta`, `looking for feedback`
- Weekly thread titles: `weekly`, `thread`, `megathread`, `showoff`, `shameless plug` (only if sub rules allow replies with links)

**Down-rank or skip** when:

- Post is clearly **hiring only**, **legal advice**, **pure rant** with no invitation to share builds
- **No selftext** and title is ambiguous (prefer skipping unless title alone is explicit)
- Post age **> 48–72 hours** (stale threads annoy mods)
- You (or the bot account) **already commented** in that thread (track `t3_id` in a local store)

Optional: require **minimum score** or **flair** if the sub uses flairs for “Show” posts.

## Posting a comment

**Endpoint:**

```http
POST https://oauth.reddit.com/api/comment
Authorization: bearer ${USER_ACCESS_TOKEN}
User-Agent: ${REDDIT_USER_AGENT}
Content-Type: application/x-www-form-urlencoded

api_type=json&thing_id=${POST_FULLNAME}&text=${URL_ENCODED_MARKDOWN}
```

- `thing_id` is the submission fullname (`t3_...`), **not** the URL slug.
- `text` is **markdown**; include the canonical site link: `https://www.newsimpactscreener.com/`

**Suggested tone (adapt to the post; do not paste identical text everywhere):**

- One or two sentences tying **headlines / market-moving news** to **tickers and themes** (what the product does).
- Link once; avoid “sign up now” spam patterns.
- If the thread asks for **feedback**, offer one concrete thought about their positioning *before* the tool mention when possible.

**Rate limits:** Respect `x-ratelimit-*` response headers; sleep **several seconds** between comments; cap **comments per day** low (e.g. 3–5) unless operating under explicit mod approval.

## Verification checklist (agent should run mentally or via script)

1. Token: `GET https://oauth.reddit.com/api/v1/me` with user bearer returns 200 and your username.
2. Listing: combined `new.json` returns children for both subs.
3. Match: title/selftext hits at least one high-signal phrase (or user-defined rule).
4. Safety: post age within window; not previously commented; dry-run OK if set.
5. POST `api/comment`; confirm response JSON contains non-error `json.data.things[0].data.id` (the new comment fullname).

## When the user asks the agent to “run” this workflow

1. Do **not** ask them to paste passwords into chat; use local env or `.env` files already on their machine (and ensure `.env` is gitignored).
2. Default to **listing + candidate posts + draft comment** (dry-run). Only POST if the user clearly opts in and understands sub + Reddit rules.
3. Log **permalink** of each target post for auditability, not raw tokens.

## Product link (canonical)

- **Site:** `https://www.newsimpactscreener.com/`

Use this exact HTTPS URL in comments unless the marketing team standardizes a tracked URL later.
