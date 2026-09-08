/**
 * Build and stage the "Priced In is free with an account" broadcast.
 *
 * Five subcommands:
 *
 *   candidates     Rank the tickers that can legally carry this email — every
 *                  claim in the copy checked against the live row. Read-only.
 *   preview        Pull the hero reconstruction live, render, write HTML + txt
 *                  to output/. Opens nothing, sends nothing, touches no API.
 *   audience       Report who is in the target segment. Read-only, by design —
 *                  see "On the audience" below.
 *   test <email>   Send the rendered email to one address as a normal
 *                  transactional send, so you can see it in a real client.
 *   draft          Create the Resend broadcast as a DRAFT against the segment.
 *                  Sending is a deliberate click in the Resend dashboard.
 *
 * Run with:  npx tsx --env-file=.env.local scripts/broadcast-priced-in.ts <cmd>
 *
 * On the audience: this targets an EXISTING curated segment (the one the user
 * calls their prospects list) by id, and never writes to it. broadcast-narrative-trading.ts rebuilds its own segment from
 * Supabase because it created that segment and owns its definition; Prospects
 * predates this script and was curated elsewhere, so reconstructing it from the
 * database would silently change who receives the mail. If it is the wrong list,
 * change SEGMENT_ID — do not teach this script to redefine one.
 *
 * On the offer: there is deliberately no price anywhere in this email. The wall
 * it is about (app/quote/[symbol]/_components/priced-in-members.tsx) gates on
 * `signedIn` alone — no plan, no trial, no card — so the ask is a free account
 * and nothing else. The list's previous broadcast was the founding-rate offer;
 * this one has to be worth opening on its own.
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { createServiceClient } from "../lib/supabase/service";
import { SITE_URL } from "../lib/site";
import { getResend } from "../lib/email/client";
import {
  createBroadcastDraft,
  updateBroadcastDraft,
} from "../lib/email/broadcasts";
import { sendEmail } from "../lib/email/send";
import { injectPrice, STALE_AFTER_DAYS } from "../lib/quote/priced-in-vote";
import {
  renderPricedInBroadcast,
  type PricedInBroadcastProps,
} from "../emails/PricedInBroadcast";

/**
 * The pre-existing curated list — pinned by ID, never created here.
 *
 * By NAME originally ("Prospects"), which broke within the hour: the segment
 * was renamed to "Hot leads" in the dashboard while this script was being
 * written, and name resolution failed with the list intact and unchanged
 * underneath. The id is the stable handle; the name is a label the owner is
 * entitled to change. NAME_HINT is only for the error message.
 */
const SEGMENT_ID =
  process.env.BROADCAST_SEGMENT_ID ?? "99be10eb-8b45-43ec-938b-52d379db44a8";
const SEGMENT_NAME_HINT = "Hot leads (formerly Prospects)";
/** Stable and date-free: `draft` matches on this to revise rather than stack. */
const BROADCAST_NAME = "Priced In — free with an account";
const HERO_TICKER = process.env.BROADCAST_HERO_TICKER ?? "AMZN";

/**
 * Signed in the email and set as the broadcast's reply-to. The sign-off
 * publishes it, so it must be a mailbox that is actually read — not noreply@.
 */
const REPLY_EMAIL = process.env.BROADCAST_REPLY_EMAIL ?? "k@newsimpactscreener.com";

/**
 * Canonical origin — SITE_URL, not a local default. Every page canonicalises to
 * `www` and the apex 301s to it, so an apex link in an email is a redirect the
 * reader's client has to follow before it can even resolve the destination.
 * This is the same split-host bug that cost the sitemap its indexing.
 */
const APP_URL = SITE_URL;
const OUT_DIR = join(process.cwd(), "output", "broadcasts");

const UTM = {
  utm_source: "resend",
  utm_medium: "email",
  utm_campaign: "priced_in_free_account",
};

/** Below this the "N published analyst targets" line is not worth citing. */
const MIN_TARGETS = 10;

// ── Hero data ───────────────────────────────────────────────────────────────

type Row = {
  ticker: string;
  as_of: string;
  price: number | null;
  n_targets: number | null;
  target_low: number | null;
  target_median: number | null;
  n_endorsed: number | null;
  summary_json: unknown;
};

const SELECT =
  "ticker, as_of, price, n_targets, target_low, target_median, n_endorsed, summary_json";

/** The generator numbers some of its bullets ("1. ..."); the email does not. */
function stripOrdinal(s: string): string {
  return s.replace(/^\s*\d+[.)]\s*/, "").trim();
}

/**
 * The decline with the largest stated worth.
 *
 * The generator writes "...worth roughly 20% of the current price" / "worth up
 * to 105% above the current price" into the prose and nowhere else, so the
 * figure has to be parsed back out. Picking the largest means the one line of
 * the locked half this email gives away is the strongest one available, rather
 * than whichever the model happened to list first — which for the current hero
 * is the difference between "AWS growth above 37%" and "AWS revenue scaling
 * toward $1 trillion".
 *
 * Falls back to the first decline when nothing states a percentage, so a hero
 * whose prose is shaped differently still renders.
 */
function boldestDecline(declines: string[]): string {
  let best = declines[0];
  let bestPct = -1;
  for (const d of declines) {
    const m = d.match(/worth\s+(?:roughly|up\s+to|about|around)?\s*([\d.]+)\s*%/i);
    const pct = m ? Number(m[1]) : NaN;
    if (Number.isFinite(pct) && pct > bestPct) {
      bestPct = pct;
      best = d;
    }
  }
  return best;
}

type Checked = {
  row: Row;
  paysFor: string[];
  declines: string[];
  ageDays: number;
};

/**
 * Every claim the copy makes, checked against one row. Returns the reasons a
 * ticker CANNOT carry this email, so `candidates` and `build` share one
 * definition of "valid" instead of drifting apart.
 *
 * The claims, and where each is asserted in the template:
 *   "it endorses none of them"        -> n_endorsed === 0
 *   "N published analyst targets"     -> n_targets >= MIN_TARGETS
 *   "the other N-1 things it refuses" -> declines.length >= 2
 *   "The price pays for ..."          -> pays_for non-empty
 *   "as it stands today"              -> as_of within STALE_AFTER_DAYS
 */
function check(row: Row): { ok: Checked | null; problems: string[] } {
  const problems: string[] = [];
  const summary = (row.summary_json ?? {}) as {
    pays_for?: string[];
    declines?: string[];
  };
  const paysFor = (summary.pays_for ?? []).map(stripOrdinal).filter(Boolean);
  const declines = (summary.declines ?? []).map(stripOrdinal).filter(Boolean);

  const nTargets = Number(row.n_targets ?? 0);
  const nEndorsed = Number(row.n_endorsed ?? 0);
  const price = Number(row.price ?? 0);
  const median = Number(row.target_median ?? 0);
  const ageDays = Math.floor(
    (Date.now() - new Date(row.as_of).getTime()) / 86_400_000,
  );

  if (nEndorsed !== 0)
    problems.push(`endorses ${nEndorsed} model(s) — "endorses none of them" is false`);
  if (nTargets < MIN_TARGETS)
    problems.push(`only ${nTargets} targets (need ${MIN_TARGETS})`);
  if (declines.length < 2)
    problems.push(`${declines.length} decline(s) — "the other N" needs at least 2`);
  if (paysFor.length < 1) problems.push("no pays_for prose");
  if (!(price > 0)) problems.push("no price");
  if (!(median > 0)) problems.push("no median target");
  if (ageDays > STALE_AFTER_DAYS)
    problems.push(`${ageDays}d old — past the ${STALE_AFTER_DAYS}d staleness line`);

  return {
    ok: problems.length === 0 ? { row, paysFor, declines, ageDays } : null,
    problems,
  };
}

/** Distinct tickers with a published reconstruction — the "N companies" claim. */
async function universeTickers(): Promise<number> {
  const sb = createServiceClient().schema("swingtrader");
  const seen = new Set<string>();
  // PostgREST caps a response at 1000 rows whatever .limit() says, so page.
  for (let from = 0; from < 20_000; from += 1000) {
    const { data, error } = await sb
      .from("research_priced_in")
      .select("ticker")
      .eq("published", true)
      .range(from, from + 999);
    if (error) throw new Error(`universe: ${error.message}`);
    const rows = data ?? [];
    for (const r of rows) seen.add(String((r as { ticker: string }).ticker));
    if (rows.length < 1000) break;
  }
  return seen.size;
}

async function latestRow(ticker: string): Promise<Row | null> {
  const sb = createServiceClient().schema("swingtrader");
  const { data, error } = await sb
    .from("research_priced_in")
    .select(SELECT)
    .eq("ticker", ticker)
    .eq("published", true)
    .order("as_of", { ascending: false })
    .limit(1);
  if (error) throw new Error(`${ticker}: ${error.message}`);
  return ((data ?? [])[0] as Row | undefined) ?? null;
}

async function build() {
  const [count, row] = await Promise.all([
    universeTickers(),
    latestRow(HERO_TICKER),
  ]);
  if (!row) throw new Error(`No published reconstruction for ${HERO_TICKER}`);

  const { ok, problems } = check(row);
  if (!ok) {
    throw new Error(
      `${HERO_TICKER} cannot carry this email:\n` +
        problems.map((p) => `  - ${p}`).join("\n") +
        `\nRun \`candidates\` and set BROADCAST_HERO_TICKER to one of them.`,
    );
  }

  const price = Number(row.price);
  const targetLow = Number(row.target_low ?? 0);
  const targetMedian = Number(row.target_median);

  const props: PricedInBroadcastProps = {
    universeTickers: count,
    hero: {
      ticker: row.ticker,
      price,
      nTargets: Number(row.n_targets),
      targetMedian,
      targetLow,
      belowEveryTarget: targetLow > 0 && price < targetLow,
      medianGapPct: Math.abs((price / targetMedian - 1) * 100),
      paysFor: injectPrice(ok.paysFor[0], price),
      decline: injectPrice(boldestDecline(ok.declines), price),
      nDeclines: ok.declines.length,
    },
    replyEmail: REPLY_EMAIL,
    appUrl: APP_URL,
    utm: UTM,
  };

  return { props, ageDays: ok.ageDays, ...renderPricedInBroadcast(props) };
}

// ── Segment (read-only) ─────────────────────────────────────────────────────

/**
 * Resolve the target segment by id, reporting whatever it is called today.
 *
 * Deliberately NOT ensureSegment(): that creates on miss, and creating a
 * segment here would produce an empty list and a broadcast that looks staged
 * and reaches nobody. A missing id is an error, never a new segment.
 */
async function resolveSegment(): Promise<{ id: string; name: string }> {
  const resend = getResend();
  const list = await resend.segments.list();
  if (list.error) throw new Error(`segments.list: ${list.error.message}`);
  const all = list.data?.data ?? [];
  const found = all.find((s) => s.id === SEGMENT_ID);
  if (!found) {
    const rows = all.map((s) => `  ${s.id}  ${s.name}`).join("\n");
    throw new Error(
      `No segment with id ${SEGMENT_ID} (${SEGMENT_NAME_HINT}). Existing:\n${rows || "  (none)"}\n` +
        `Set BROADCAST_SEGMENT_ID to the right one.`,
    );
  }
  return { id: found.id, name: found.name };
}

async function segmentContacts(
  segmentId: string,
): Promise<{ total: number; unsubscribed: number }> {
  const resend = getResend();
  let after: string | undefined;
  let total = 0;
  let unsubscribed = 0;
  // Page size caps at 100; a partial read would understate the list.
  for (let page = 0; page < 200; page += 1) {
    const res = await resend.contacts.list({
      limit: 100,
      segmentId,
      ...(after ? { after } : {}),
    } as never);
    if (res.error) throw new Error(`contacts.list: ${res.error.message}`);
    const body = res.data as {
      data?: { id: string; unsubscribed: boolean }[];
      has_more?: boolean;
    } | null;
    const rows = body?.data ?? [];
    total += rows.length;
    unsubscribed += rows.filter((c) => c.unsubscribed).length;
    if (!body?.has_more || rows.length === 0) {
      return { total, unsubscribed };
    }
    after = rows[rows.length - 1].id;
  }
  throw new Error("Resend contact pagination did not terminate");
}

// ── Commands ────────────────────────────────────────────────────────────────

async function cmdCandidates() {
  const sb = createServiceClient().schema("swingtrader");
  const { data, error } = await sb
    .from("research_priced_in")
    .select(SELECT)
    .eq("published", true)
    .order("as_of", { ascending: false })
    .limit(1000);
  if (error) throw new Error(error.message);

  const newest = new Map<string, Row>();
  for (const r of (data ?? []) as Row[]) {
    if (!newest.has(r.ticker)) newest.set(r.ticker, r);
  }

  const valid = [...newest.values()]
    .map((row) => ({ row, ...check(row) }))
    .filter((c) => c.ok)
    .map((c) => c.ok as Checked)
    // Most published targets first: the "N analyst targets" line is the claim
    // doing the most work, so a bigger N is a better hero.
    .sort((a, b) => Number(b.row.n_targets) - Number(a.row.n_targets));

  console.log(
    `Valid heroes (of ${newest.size} tickers with a published row): ${valid.length}\n`,
  );
  console.log("ticker   as_of        price   targets  median   below-all  declines");
  for (const c of valid.slice(0, 20)) {
    const price = Number(c.row.price);
    const low = Number(c.row.target_low ?? 0);
    console.log(
      c.row.ticker.padEnd(8),
      String(c.row.as_of).slice(0, 10),
      price.toFixed(2).padStart(8),
      String(c.row.n_targets).padStart(8),
      Number(c.row.target_median).toFixed(0).padStart(7),
      (low > 0 && price < low ? "yes" : "no").padStart(10),
      String(c.declines.length).padStart(9),
    );
  }
  console.log(
    `\nCurrent hero: ${HERO_TICKER}. Override with BROADCAST_HERO_TICKER=<ticker>.`,
  );
}

async function cmdPreview() {
  const { props, subject, html, text, ageDays } = await build();
  mkdirSync(OUT_DIR, { recursive: true });
  const stem = join(OUT_DIR, "priced-in");
  writeFileSync(`${stem}.html`, html, "utf8");
  writeFileSync(`${stem}.txt`, text, "utf8");

  const h = props.hero;
  console.log(`Subject:  ${subject}\n`);
  console.log(`Universe  ${props.universeTickers} tickers with a published reconstruction`);
  console.log(
    `Hero      ${h.ticker} @ $${h.price.toFixed(2)} · ${h.nTargets} targets · median $${h.targetMedian.toFixed(0)}` +
      ` · ${h.belowEveryTarget ? "below every target" : `${h.medianGapPct.toFixed(0)}% below median`}` +
      ` · ${ageDays}d old`,
  );
  console.log(`Pays for  ${h.paysFor}`);
  console.log(`Declines  ${h.decline}`);
  console.log(`          (+${h.nDeclines - 1} more behind the account wall)`);
  console.log(`\nWrote ${stem}.html and ${stem}.txt`);
}

async function cmdAudience() {
  const seg = await resolveSegment();
  const { total, unsubscribed } = await segmentContacts(seg.id);
  console.log(`Segment    ${seg.name} (${seg.id})`);
  console.log(`Contacts   ${total}`);
  console.log(`Opted out  ${unsubscribed}`);
  console.log(`Will reach ${total - unsubscribed}`);
  console.log(
    `\nRead-only: this script never writes to "${seg.name}". Edit the segment in Resend.`,
  );
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
  const seg = await resolveSegment();
  const { props, subject, html, text } = await build();
  const h = props.hero;

  const preview =
    `${h.ticker} sits ${h.belowEveryTarget ? "below every one of" : "below the median of"} ` +
    `${h.nTargets} published analyst targets. What it refuses to pay for is behind a free account.`;

  const payload = {
    name: BROADCAST_NAME,
    subject,
    html,
    text,
    previewText: preview,
    // Otherwise the broadcast replies to noreply@ while the sign-off invites a
    // reply to REPLY_EMAIL.
    replyTo: REPLY_EMAIL,
  };

  // Revise the draft already staged for this campaign rather than stacking a
  // second one. A broadcast that has been SENT is left alone — updating it
  // would be editing history.
  const resend = getResend();
  const existing = await resend.broadcasts.list();
  const prior = (existing.data?.data ?? []).find(
    (b) => b.name === BROADCAST_NAME && b.status === "draft",
  );

  const res = prior
    ? await updateBroadcastDraft(prior.id, { ...payload, segmentId: seg.id })
    : await createBroadcastDraft({ segmentId: seg.id, ...payload });

  if (!res.ok) {
    console.error(`Draft ${prior ? "update" : "create"} failed: ${res.error}`);
    process.exitCode = 1;
    return;
  }

  console.log(`Draft ${prior ? "updated" : "created"}: ${res.id}`);
  console.log(`Segment: ${seg.name} (${seg.id})`);
  console.log(`Subject: ${subject}`);
  console.log(
    `\nReview and send it at https://resend.com/broadcasts/${res.id} — this script never sends.`,
  );
}

// ── Entry ───────────────────────────────────────────────────────────────────

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  switch (cmd) {
    case "candidates":
      return cmdCandidates();
    case "preview":
      return cmdPreview();
    case "audience":
      return cmdAudience();
    case "test": {
      const to = rest.find((a) => a.includes("@"));
      if (!to) throw new Error("usage: test <email>");
      return cmdTest(to);
    }
    case "draft":
      return cmdDraft();
    default:
      console.log(
        "usage: broadcast-priced-in.ts candidates | preview | audience | test <email> | draft",
      );
      process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
