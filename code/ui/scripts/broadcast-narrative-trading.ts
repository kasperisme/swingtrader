/**
 * Build and stage the "narrative trading" broadcast.
 *
 * Four subcommands, in the order you run them:
 *
 *   preview        Pull the hero reconstruction live, render, write HTML + txt
 *                  to output/. Opens nothing, sends nothing, touches no API.
 *   audience       Report the reachable list, then upsert every address into
 *                  the Resend segment (creating it if absent). --dry-run first.
 *   test <email>   Send the rendered email to one address as a normal
 *                  transactional send, so you can see it in a real client.
 *   draft          Create the Resend broadcast as a DRAFT against the segment.
 *                  Sending is a deliberate click in the Resend dashboard.
 *
 * Run with:  npx tsx --env-file=.env.local scripts/broadcast-narrative-trading.ts <cmd>
 *
 * Why a script and not a route: this is a one-shot campaign against a 100-odd
 * person list. The audience lives in three Supabase tables that predate the
 * Resend segment, so the reachable set has to be reconstructed from the
 * database rather than trusted to have been synced at signup — only the
 * /api/early-access path ever called addToWaitlistSegment.
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { createServiceClient } from "../lib/supabase/service";
import { getResend } from "../lib/email/client";
import { addContactToSegments } from "../lib/email/segments";
import {
  createBroadcastDraft,
  ensureSegment,
  updateBroadcastDraft,
} from "../lib/email/broadcasts";
import { sendEmail } from "../lib/email/send";
import {
  renderNarrativeTradingBroadcast,
  type NarrativeTradingBroadcastProps,
} from "../emails/NarrativeTradingBroadcast";
import { TRIAL_DAYS } from "../lib/plans";

const SEGMENT_NAME = "Narrative Trading Launch";
const BROADCAST_NAME = "Founding rate — first 100";
const HERO_TICKER = process.env.BROADCAST_HERO_TICKER ?? "NVDA";
/**
 * Signed in the email and set as the broadcast's reply-to. The P.S. and the
 * sign-off publish it, so it must be a mailbox that is actually read — not the
 * noreply@ sender.
 */
const REPLY_EMAIL = process.env.BROADCAST_REPLY_EMAIL ?? "k@newsimpactscreener.com";

const APP_URL =
  process.env.NEXT_PUBLIC_APP_URL ?? "https://newsimpactscreener.com";
const OUT_DIR = join(process.cwd(), "output", "broadcasts");

/** Founding-phase monthly prices — Phase 1 column of app/pricing/page.tsx. */
const INVESTOR_PRICE = 9;
const TRADER_PRICE = 19;
/** Phase 2 column of app/pricing/page.tsx — what the founding rates become. */
const NEXT_INVESTOR_PRICE = 29;
const NEXT_TRADER_PRICE = 49;

/**
 * The headline claims the reader is "one of the first 100". That is a claim
 * about them, not a slogan, so refuse to render once the list has outgrown it
 * rather than letting it quietly become false. Slack over 100 because the
 * reachable list excludes opt-outs while "sign-ups" counts everyone.
 */
const FIRST_N_CLAIM_CEILING = 115;

/**
 * How long we hold the founding rate. This is OUR deadline, not the pricing
 * page's — Phase 2 triggers on user count, not on a date — so it is ours to
 * pick and ours to honour. Defaults to the coming Sunday.
 */
function comingSunday(): string {
  const d = new Date();
  d.setDate(d.getDate() + ((7 - d.getDay()) % 7 || 7));
  return `Sunday, ${d.toLocaleDateString("en-US", { month: "long", day: "numeric" })}`;
}
const DEADLINE_LABEL = process.env.BROADCAST_DEADLINE ?? comingSunday();

const UTM = {
  utm_source: "resend",
  utm_medium: "email",
  utm_campaign: "narrative_trading_launch",
};

// ── Audience ────────────────────────────────────────────────────────────────

type Recipient = { email: string; sources: Set<string> };

/**
 * The reachable list: every address that asked us for something, minus the
 * ones that have since opted out of what they asked for.
 *
 * `early_access_signups` is effectively the master table — the screening and
 * briefing signup paths both mirror into it — but it carries no unsubscribe
 * state, so the two lead-magnet tables are read as well: they contribute their
 * own addresses AND supply the opt-outs that suppress a master-table row.
 */
async function loadAudience(): Promise<{
  recipients: Recipient[];
  suppressed: string[];
}> {
  const client = createServiceClient();
  const sb = client.schema("swingtrader");
  const byEmail = new Map<string, Recipient>();
  const suppressed = new Set<string>();

  const add = (email: string | null | undefined, source: string) => {
    if (!email) return;
    const key = email.trim().toLowerCase();
    if (!key.includes("@")) return;
    const existing = byEmail.get(key);
    if (existing) existing.sources.add(source);
    else byEmail.set(key, { email: key, sources: new Set([source]) });
  };

  const { data: waitlist, error: e1 } = await sb
    .from("early_access_signups")
    .select("email, source")
    .limit(10_000);
  if (e1) throw new Error(`early_access_signups: ${e1.message}`);
  for (const r of waitlist ?? []) add(r.email, r.source ?? "waitlist");

  const { data: screenings, error: e2 } = await sb
    .from("market_screening_email_subscriptions")
    .select("email, status, unsubscribed_at")
    .limit(10_000);
  if (e2) throw new Error(`market_screening_email_subscriptions: ${e2.message}`);
  for (const r of screenings ?? []) {
    const optedOut = Boolean(r.unsubscribed_at) || r.status === "unsubscribed";
    if (optedOut) suppressed.add((r.email ?? "").toLowerCase());
    else add(r.email, "screening");
  }

  const { data: briefings, error: e3 } = await sb
    .from("news_briefing_subscriptions")
    .select("email, status, unsubscribed_at")
    .limit(10_000);
  if (e3) throw new Error(`news_briefing_subscriptions: ${e3.message}`);
  for (const r of briefings ?? []) {
    const optedOut = Boolean(r.unsubscribed_at) || r.status === "unsubscribed";
    if (optedOut) suppressed.add((r.email ?? "").toLowerCase());
    else add(r.email, "briefing");
  }

  // Registered accounts — the warmest names here, since creating an account is
  // a stronger signal than dropping an email into a form. Most never joined a
  // lead-magnet list, so the three tables above miss them entirely, and
  // auth.users is only reachable through the admin API.
  const { data: authData, error: e4 } = await client.auth.admin.listUsers({
    page: 1,
    perPage: 1000,
  });
  if (e4) throw new Error(`auth.users: ${e4.message}`);
  for (const u of authData.users) add(u.email, "account");

  // Never pitch a subscription to someone who already holds one. Zero rows
  // today, but this script outlives that.
  const { data: subs, error: e5 } = await sb
    .from("user_subscriptions")
    .select("user_id, status")
    .limit(10_000);
  if (e5) throw new Error(`user_subscriptions: ${e5.message}`);
  const paying = new Set(
    (subs ?? [])
      .filter((r) => ["active", "trialing"].includes(String(r.status)))
      .map((r) => String(r.user_id)),
  );
  for (const u of authData.users) {
    if (u.email && paying.has(u.id)) suppressed.add(u.email.toLowerCase());
  }

  // An opt-out anywhere wins over an opt-in anywhere else: these people all
  // signed up for "email from News Impact Screener", not for one specific list.
  for (const email of suppressed) byEmail.delete(email);

  return {
    recipients: [...byEmail.values()].sort((a, b) =>
      a.email.localeCompare(b.email),
    ),
    suppressed: [...suppressed],
  };
}

/**
 * Addresses that unsubscribed at the RESEND level — via the unsubscribe link on
 * a previous send, which never writes back to Supabase.
 *
 * Without this the sync would resurrect them: addContactToSegments passes
 * `unsubscribed: false`, so re-adding an opted-out contact silently flips them
 * back on. Mailing someone who has unsubscribed is the one mistake this script
 * must not make, so a failure to READ the list aborts the sync rather than
 * proceeding blind.
 */
async function resendUnsubscribed(): Promise<Set<string>> {
  const resend = getResend();
  const out = new Set<string>();
  // Page size caps at 100, so walk the cursor — a partial read would look like
  // "nobody unsubscribed" and quietly mail people who did.
  let after: string | undefined;
  for (let page = 0; page < 100; page += 1) {
    const res = await resend.contacts.list({
      limit: 100,
      ...(after ? { after } : {}),
    } as never);
    if (res.error) {
      throw new Error(`Could not read Resend contacts: ${res.error.message}`);
    }
    const body = res.data as {
      data?: { id: string; email: string; unsubscribed: boolean }[];
      has_more?: boolean;
    } | null;
    const rows = body?.data ?? [];
    for (const c of rows) {
      if (c.unsubscribed) out.add(c.email.toLowerCase());
    }
    if (!body?.has_more || rows.length === 0) return out;
    after = rows[rows.length - 1].id;
  }
  throw new Error("Resend contact pagination did not terminate");
}

// ── Hero data ───────────────────────────────────────────────────────────────

type PricedInRow = {
  ticker: string;
  as_of: string;
  price: number;
  implied_revenue_cagr: number | null;
  discount_rate: number | null;
  terminal_growth: number | null;
  n_targets: number | null;
  target_median: number | null;
  target_high: number | null;
  median_gap: number | null;
  n_endorsed: number | null;
  n_rejected_bull: number | null;
  drivers_json: unknown;
  summary_json: unknown;
};

/**
 * Load the hero's latest PUBLISHED reconstruction plus the size of the
 * published universe. Every number in the email comes from here — nothing in
 * the template is hardcoded, so a rebuild the day before sending picks up
 * whatever the nightly batch last promoted.
 */
type HeroReconstruction = {
  ticker: string;
  price: number;
  impliedCagrPct: number;
  recentGrowthPct: number | null;
  nTargets: number;
  targetMedian: number;
  targetHigh: number;
  nEndorsed: number;
  nRejectedBull: number;
};

async function loadHero(ticker: string): Promise<{
  hero: HeroReconstruction;
  universeCount: number;
  row: PricedInRow;
}> {
  const sb = createServiceClient().schema("swingtrader");

  const { count, error: countErr } = await sb
    .from("research_priced_in")
    .select("id", { count: "exact", head: true })
    .eq("published", true);
  if (countErr) throw new Error(`universe count: ${countErr.message}`);

  const { data, error } = await sb
    .from("research_priced_in")
    .select(
      "ticker, as_of, price, implied_revenue_cagr, discount_rate, terminal_growth, n_targets, target_median, target_high, median_gap, n_endorsed, n_rejected_bull, drivers_json, summary_json",
    )
    .eq("ticker", ticker)
    .eq("published", true)
    .order("as_of", { ascending: false })
    .limit(1);
  if (error) throw new Error(`hero ${ticker}: ${error.message}`);
  const row = (data ?? [])[0] as PricedInRow | undefined;
  if (!row) throw new Error(`No published reconstruction for ${ticker}`);

  const summary = (row.summary_json ?? {}) as {
    crux?: string;
    pays_for?: string[];
  };
  const paysFor = summary.pays_for ?? [];
  if (paysFor.length === 0) {
    throw new Error(`${ticker} has no pays_for — pick another hero`);
  }

  // The P.S. asserts the price "endorses none of them", which is only true
  // while n_endorsed is 0. It is a claim about a live row that the nightly
  // batch can change under us, so fail loudly rather than ship it stale.
  const nEndorsed = Number(row.n_endorsed ?? 0);
  if (nEndorsed !== 0) {
    throw new Error(
      `${ticker} now endorses ${nEndorsed} model(s) — the "endorses none of them" ` +
        `line is no longer true. Pick another hero via BROADCAST_HERO_TICKER.`,
    );
  }

  const nTargets = Number(row.n_targets ?? 0);
  if (nTargets < 5) {
    throw new Error(`${ticker} has only ${nTargets} targets — too thin to cite`);
  }

  return {
    row,
    hero: {
      ticker: row.ticker,
      price: Number(row.price),
      impliedCagrPct: Number(row.implied_revenue_cagr ?? 0) * 100,
      recentGrowthPct: extractRecentGrowthPct(paysFor),
      nTargets,
      targetMedian: Number(row.target_median ?? 0),
      targetHigh: Number(row.target_high ?? 0),
      nEndorsed,
      nRejectedBull: Number(row.n_rejected_bull ?? 0),
    },
    universeCount: count ?? 0,
  };
}

/**
 * The recent reported growth rate, for the "…from a company that just posted
 * 68.2%" contrast — pulled out of the generator's own pays_for prose, which is
 * the only place it is written down (there is no column for it).
 *
 * Returns null when the prose doesn't state one, and the template drops the
 * clause entirely rather than inventing a figure.
 */
function extractRecentGrowthPct(paysFor: string[]): number | null {
  const patterns = [
    /recent\s+([\d.]+)%\s+year-over-year/i,
    /from\s+the\s+recent\s+([\d.]+)%/i,
    /just\s+reported\s+([\d.]+)%/i,
  ];
  for (const text of paysFor) {
    for (const re of patterns) {
      const m = text.match(re);
      if (m) {
        const v = Number(m[1]);
        if (Number.isFinite(v) && v > 0) return v;
      }
    }
  }
  return null;
}

async function build() {
  const [{ hero, universeCount }, { recipients }] = await Promise.all([
    loadHero(HERO_TICKER),
    loadAudience(),
  ]);

  if (recipients.length > FIRST_N_CLAIM_CEILING) {
    throw new Error(
      `List is ${recipients.length} — too big for the "first 100" headline. ` +
        `Rewrite the claim or raise FIRST_N_CLAIM_CEILING deliberately.`,
    );
  }

  const props: NarrativeTradingBroadcastProps = {
    investorPrice: INVESTOR_PRICE,
    traderPrice: TRADER_PRICE,
    nextInvestorPrice: NEXT_INVESTOR_PRICE,
    nextTraderPrice: NEXT_TRADER_PRICE,
    deadlineLabel: DEADLINE_LABEL,
    trialDays: TRIAL_DAYS,
    universeCount,
    proof: {
      ticker: hero.ticker,
      nTargets: hero.nTargets,
      impliedCagrPct: hero.impliedCagrPct,
      recentGrowthPct: hero.recentGrowthPct,
    },
    replyEmail: REPLY_EMAIL,
    appUrl: APP_URL,
    utm: UTM,
  };
  const rendered = renderNarrativeTradingBroadcast(props);
  return { props, listSize: recipients.length, ...rendered };
}

// ── Commands ────────────────────────────────────────────────────────────────

async function cmdPreview() {
  const { props, listSize, subject, html, text } = await build();
  mkdirSync(OUT_DIR, { recursive: true });
  const stem = join(OUT_DIR, "narrative-trading");
  writeFileSync(`${stem}.html`, html, "utf8");
  writeFileSync(`${stem}.txt`, text, "utf8");

  console.log(`Subject:  ${subject}\n`);
  console.log(`List      ${listSize} reachable (claim ceiling ${FIRST_N_CLAIM_CEILING})`);
  console.log(
    `Offer     $${props.investorPrice}/$${props.traderPrice} now → $${props.nextInvestorPrice}/$${props.nextTraderPrice} after`,
  );
  console.log(`Deadline  ${props.deadlineLabel}`);
  console.log(
    `Proof     ${props.proof.ticker}: ${props.proof.nTargets} targets, ${props.proof.impliedCagrPct.toFixed(
      1,
    )}% implied${
      props.proof.recentGrowthPct != null
        ? ` vs ${props.proof.recentGrowthPct}% reported`
        : ""
    }`,
  );
  console.log(`\nWrote ${stem}.html and ${stem}.txt`);
}

async function cmdAudience(dryRun: boolean) {
  const { recipients, suppressed } = await loadAudience();

  const bySource = new Map<string, number>();
  for (const r of recipients) {
    for (const s of r.sources) bySource.set(s, (bySource.get(s) ?? 0) + 1);
  }
  console.log(`Reachable: ${recipients.length} unique addresses`);
  console.log(`Suppressed (opted out): ${suppressed.length}`);
  console.log(`\nBy signup source (addresses can appear in several):`);
  for (const [s, n] of [...bySource].sort((a, b) => b[1] - a[1])) {
    console.log(`  ${String(n).padStart(4)}  ${s}`);
  }

  // Resend-side opt-outs, which Supabase cannot see.
  const optedOutAtResend = await resendUnsubscribed();
  const sendable = recipients.filter((r) => !optedOutAtResend.has(r.email));
  const blocked = recipients.length - sendable.length;
  if (blocked > 0) {
    console.log(
      `\nHeld back ${blocked} already unsubscribed in Resend (invisible to Supabase):`,
    );
    for (const r of recipients) {
      if (optedOutAtResend.has(r.email)) console.log(`  ${r.email}`);
    }
  }
  console.log(`\nWill sync: ${sendable.length}`);

  if (dryRun) {
    console.log(`--dry-run: nothing written to Resend.`);
    return;
  }

  const seg = await ensureSegment(SEGMENT_NAME);
  if (!seg.ok) {
    console.error(`Segment "${SEGMENT_NAME}" failed: ${seg.error}`);
    process.exitCode = 1;
    return;
  }
  console.log(`\nSegment "${SEGMENT_NAME}" → ${seg.id}`);

  let added = 0;
  const failures: string[] = [];
  for (const r of sendable) {
    const res = await addContactToSegments({
      email: r.email,
      segmentIds: [seg.id],
    });
    if (res.ok) added += 1;
    else failures.push(`${r.email}: ${res.error}`);
  }
  console.log(`Synced ${added}/${sendable.length} contacts.`);
  if (failures.length) {
    console.error(`\n${failures.length} failed:`);
    for (const f of failures.slice(0, 20)) console.error(`  ${f}`);
  }
  console.log(`\nSet RESEND_BROADCAST_SEGMENT_ID=${seg.id}`);
}

async function cmdTest(to: string) {
  const { subject, html, text } = await build();
  const res = await sendEmail({
    to,
    subject,
    html,
    text,
    tags: [{ name: "type", value: "broadcast_test" }],
  });
  console.log(res.ok ? `Sent test to ${to} (${res.id})` : `Failed: ${res.error}`);
  if (!res.ok) process.exitCode = 1;
}

async function cmdDraft() {
  const segmentId = process.env.RESEND_BROADCAST_SEGMENT_ID;
  let id = segmentId;
  if (!id) {
    const seg = await ensureSegment(SEGMENT_NAME);
    if (!seg.ok) {
      console.error(`Segment lookup failed: ${seg.error}`);
      process.exitCode = 1;
      return;
    }
    id = seg.id;
  }

  const resend = getResend();
  const seg = await resend.segments.get(id);
  if (seg.error) {
    console.error(`Segment ${id} unreadable: ${seg.error.message}`);
    process.exitCode = 1;
    return;
  }

  const { props, subject, html, text } = await build();
  const preview = `Founding rate held until ${props.deadlineLabel}: $${props.investorPrice} or $${props.traderPrice} a month, before it becomes $${props.nextInvestorPrice} and $${props.nextTraderPrice}.`;
  // Stable, date-free: the name is the key `update` matches on, so stamping it
  // with today's date meant a rebuild the next morning silently created a
  // second draft instead of revising the one already open.
  const name = BROADCAST_NAME;
  const payload = {
    name,
    subject,
    html,
    text,
    previewText: preview,
    // Otherwise the broadcast replies to noreply@ while the sign-off invites
    // a reply to REPLY_EMAIL.
    replyTo: REPLY_EMAIL,
  };

  // Revise the draft we already made for this segment rather than stacking a
  // second one. Only ever a draft — a broadcast that has been sent is left
  // alone, since updating it would be editing history.
  const existing = await resend.broadcasts.list();
  const prior = (existing.data?.data ?? []).find(
    (b) => b.name === name && b.status === "draft",
  );

  if (prior) {
    const upd = await updateBroadcastDraft(prior.id, { ...payload, segmentId: id });
    if (!upd.ok) {
      console.error(`Update failed: ${upd.error}`);
      process.exitCode = 1;
      return;
    }
    console.log(`Draft updated: ${prior.id}`);
    console.log(`Segment: ${seg.data?.name} (${id})`);
    console.log(
      `\nReview and send it at https://resend.com/broadcasts/${prior.id} — this script never sends.`,
    );
    return;
  }

  const res = await createBroadcastDraft({ segmentId: id, ...payload });

  if (!res.ok) {
    console.error(`Draft failed: ${res.error}`);
    process.exitCode = 1;
    return;
  }
  console.log(`Draft created: ${res.id}`);
  console.log(`Segment: ${seg.data?.name} (${id})`);
  console.log(
    `\nReview and send it at https://resend.com/broadcasts/${res.id} — this script never sends.`,
  );
}

// ── Entry ───────────────────────────────────────────────────────────────────

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  switch (cmd) {
    case "preview":
      return cmdPreview();
    case "audience":
      return cmdAudience(rest.includes("--dry-run"));
    case "test": {
      const to = rest.find((a) => a.includes("@"));
      if (!to) throw new Error("usage: test <email>");
      return cmdTest(to);
    }
    case "draft":
      return cmdDraft();
    default:
      console.log(
        "usage: broadcast-narrative-trading.ts preview | audience [--dry-run] | test <email> | draft",
      );
      process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
