/**
 * Marketing broadcast: the founding-rate offer to the first ~100 sign-ups.
 *
 * Renders to an HTML *string* rather than a React component (react-email is not
 * installed), mirroring SubscriptionConfirmationEmail and the app's visual
 * language: near-black background, amber accent, monospace tickers.
 *
 * Offer-first and deliberately short. The proof that the product is worth
 * paying for sits in the P.S., not above the ask — this list has already been
 * told what the product does, so the email's job is the price and the date.
 *
 * Three things here are load-bearing and must stay true:
 *
 *  - "one of the first 100" is a claim about the READER. It holds only while
 *    the list is actually that small, so the script asserts listSize before
 *    rendering rather than letting it quietly become false.
 *  - The price step is $9/$19 -> $29/$49, straight off the Phase 2 column of
 *    app/pricing/page.tsx. That is more than a doubling, so the email states
 *    the four numbers instead of characterising them.
 *  - The deadline is OURS, not the pricing page's. Phase 2 triggers on user
 *    count, not on a date, so the copy says "I'm holding it until <date>" —
 *    a promise we control and can keep — never "the price changes on Monday",
 *    which would be false. Honour it, or the next deadline means nothing.
 *
 * Sent as a Resend BROADCAST, so the footer uses Resend's
 * {{{RESEND_UNSUBSCRIBE_URL}}} merge tag rather than our own signed token.
 */

export type NarrativeTradingBroadcastProps = {
  /** Founding (Phase 1) monthly prices. */
  investorPrice: number;
  traderPrice: number;
  /** Phase 2 prices — what they become for everyone after. */
  nextInvestorPrice: number;
  nextTraderPrice: number;
  /** When we stop holding the rate, e.g. "Sunday night". */
  deadlineLabel: string;
  /** Full-access trial length in days. */
  trialDays: number;
  /** Published reconstructions, e.g. 204. */
  universeCount: number;
  /** One line of proof for the P.S. — the whole hero teardown, compressed. */
  proof: {
    ticker: string;
    nTargets: number;
    /** Reverse-DCF implied revenue CAGR, as a percent. */
    impliedCagrPct: number;
    /** Most recent reported growth, for the contrast. Null drops the clause. */
    recentGrowthPct: number | null;
  };
  /** Absolute base URL, e.g. https://newsimpactscreener.com */
  appUrl: string;
  /** Appended to every link for attribution. */
  utm?: Record<string, string>;
};

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const BG = "#0b0f17";
const CARD = "#111620";
const TEXT = "#e6e9ef";
const MUTED = "#8b93a7";
const BORDER = "#1e2533";
const ACCENT = "#f5a623";
const MONO =
  "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace";
const SANS =
  "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

const P = `font-family:${SANS};font-size:15px;line-height:1.6;color:${TEXT};margin:0 0 14px 0;`;

function withUtm(url: string, utm?: Record<string, string>): string {
  if (!utm || Object.keys(utm).length === 0) return url;
  const q = Object.entries(utm)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  return url.includes("?") ? `${url}&${q}` : `${url}?${q}`;
}

export function renderNarrativeTradingBroadcast(
  props: NarrativeTradingBroadcastProps,
): { subject: string; html: string; text: string } {
  const {
    investorPrice,
    traderPrice,
    nextInvestorPrice,
    nextTraderPrice,
    deadlineLabel,
    trialDays,
    universeCount,
    proof,
    utm,
  } = props;
  const base = props.appUrl.replace(/\/$/, "");
  const link = (path: string, content: string) =>
    withUtm(`${base}${path}`, { ...utm, utm_content: content });

  // Straight to sign-up, not /pricing: the plan picker is a step in onboarding
  // (components/onboarding-plan-step.tsx), so creating the account IS the path
  // to locking the rate. A detour through the pricing page adds a click and a
  // second chance to leave.
  const signupUrl = link("/auth/sign-up", "founding_rate");
  const quoteUrl = link(`/quote/${proof.ticker}`, "proof_quote");

  const subject = `Your $${investorPrice} rate, held until ${deadlineLabel}`;
  const preheader = `You were one of the first 100 sign-ups. That locks $${investorPrice} or $${traderPrice} a month before it becomes $${nextInvestorPrice} and $${nextTraderPrice}.`;

  const growthClause =
    proof.recentGrowthPct != null
      ? `, from a company that just posted ${proof.recentGrowthPct.toFixed(1)}%`
      : "";

  const FEATURES: [string, string][] = [
    [
      "Narrative trading",
      `what a share price already pays for, and what it refuses to &mdash; reconstructed nightly across ${universeCount} companies`,
    ],
    ["News impact", "real-time scoring on the headlines hitting your holdings"],
    [
      "Agents",
      "they watch your names and tell you when a headline actually lands",
    ],
    ["History", "up to 400 days of it, so you can check the pattern yourself"],
  ];

  const featureRows = FEATURES.map(
    ([name, detail]) => `
      <tr>
        <td style="padding:0 0 9px 0;font-family:${SANS};font-size:14px;line-height:1.55;color:${TEXT};">
          <strong style="color:${ACCENT};">${name}</strong>
          <span style="color:${MUTED};"> &mdash; ${detail}</span>
        </td>
      </tr>`,
  ).join("");

  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <meta name="color-scheme" content="dark" />
    <title>${esc(subject)}</title>
  </head>
  <body style="margin:0;padding:0;background:${BG};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;color:${BG};">
      ${esc(preheader)}
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${BG};padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="max-width:540px;background:${CARD};border:1px solid ${BORDER};border-radius:14px;overflow:hidden;">

            <tr>
              <td style="padding:26px 28px 0 28px;">
                <p style="font-family:${MONO};font-size:11px;font-weight:600;letter-spacing:0.16em;text-transform:uppercase;color:${ACCENT};margin:0 0 18px 0;">
                  News Impact Screener
                </p>

                <h1 style="font-family:${SANS};font-size:22px;line-height:1.35;font-weight:700;color:${TEXT};margin:0 0 16px 0;">
                  You were one of the first 100 to sign up.
                </h1>

                <p style="${P}">
                  That gets you the founding rate &mdash;
                  <strong style="color:${TEXT};">$${investorPrice}</strong> or
                  <strong style="color:${TEXT};">$${traderPrice}</strong> a month, locked for as
                  long as you stay. For everyone who comes after you, it's
                  $${nextInvestorPrice} and $${nextTraderPrice}.
                </p>

                <p style="${P}">
                  I'm holding it for this list until <strong style="color:${ACCENT};">${esc(deadlineLabel)}</strong>.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:6px 28px 0 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                       style="background:${BG};border:1px solid ${BORDER};border-radius:10px;">
                  <tr>
                    <td style="padding:16px 18px;">
                      <p style="font-family:${MONO};font-size:10px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:${MUTED};margin:0 0 12px 0;">
                        What it gets you
                      </p>
                      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                        ${featureRows}
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="padding:20px 28px 0 28px;">
                <a href="${signupUrl}"
                   style="display:inline-block;font-family:${SANS};font-size:15px;font-weight:600;color:${BG};background:${ACCENT};padding:12px 24px;border-radius:8px;text-decoration:none;">
                  Lock in your rate &rarr;
                </a>
                <p style="font-family:${SANS};font-size:13px;line-height:1.6;color:${MUTED};margin:12px 0 0 0;">
                  Every account starts with ${trialDays} days of full access, no card. The rate
                  locks when you pick a plan &mdash; cancel anytime, in two clicks.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:22px 28px 0 28px;">
                <p style="${P}margin-bottom:10px;">&mdash; Kasper</p>
                <p style="font-family:${SANS};font-size:14px;line-height:1.6;color:${MUTED};margin:0;">
                  <strong style="color:${TEXT};">P.S.</strong> One example of what narrative trading
                  means: ${proof.nTargets} analysts have published price targets on
                  <a href="${quoteUrl}" style="color:${ACCENT};text-decoration:none;font-weight:600;">${esc(proof.ticker)}</a>,
                  and its price endorses none of them &mdash; it's paying for
                  ${proof.impliedCagrPct.toFixed(1)}% growth a year${growthClause}. That's on the site now.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:22px 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="border-top:1px solid ${BORDER};padding-top:14px;">
                      <p style="font-family:${SANS};font-size:11px;line-height:1.7;color:${MUTED};margin:0 0 6px 0;">
                        Research and data, not investment advice.
                      </p>
                      <p style="font-family:${SANS};font-size:11px;line-height:1.7;color:${MUTED};margin:0;">
                        You signed up at newsimpactscreener.com.
                        <a href="{{{RESEND_UNSUBSCRIBE_URL}}}" style="color:${MUTED};text-decoration:underline;">Unsubscribe</a>.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;

  const text = [
    "You were one of the first 100 to sign up.",
    "",
    `That gets you the founding rate — $${investorPrice} or $${traderPrice} a month, locked for as long as`,
    `you stay. For everyone who comes after you, it's $${nextInvestorPrice} and $${nextTraderPrice}.`,
    "",
    `I'm holding it for this list until ${deadlineLabel}.`,
    "",
    "WHAT IT GETS YOU",
    ...FEATURES.map(
      ([name, detail]) => `  ${name} — ${detail.replace(/&mdash;/g, "—")}`,
    ),
    "",
    `Lock in your rate: ${signupUrl}`,
    "",
    `Every account starts with ${trialDays} days of full access, no card. The rate locks when`,
    "you pick a plan — cancel anytime, in two clicks.",
    "",
    "— Kasper",
    "",
    `P.S. One example of what narrative trading means: ${proof.nTargets} analysts have published`,
    `price targets on ${proof.ticker}, and its price endorses none of them — it's paying for`,
    `${proof.impliedCagrPct.toFixed(1)}% growth a year${
      proof.recentGrowthPct != null
        ? `, from a company that just posted ${proof.recentGrowthPct.toFixed(1)}%`
        : ""
    }. That's on the site now:`,
    quoteUrl,
    "",
    "---",
    "Research and data, not investment advice.",
    "You signed up at newsimpactscreener.com.",
    "Unsubscribe: {{{RESEND_UNSUBSCRIBE_URL}}}",
  ].join("\n");

  return { subject, html, text };
}
