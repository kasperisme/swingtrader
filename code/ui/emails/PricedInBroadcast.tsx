/**
 * Marketing broadcast: the Priced In panel on the quote pages, and the fact
 * that the locked half of it costs nothing but an account.
 *
 * Renders to an HTML *string* rather than a React component (react-email is not
 * installed), mirroring NarrativeTradingBroadcast and the app's visual
 * language: the warm cream light theme from globals.css `:root`, amber accent,
 * monospace tickers.
 *
 * The email is a demonstration, not a pitch. It shows the free half of one real
 * reconstruction, shows one line of the locked half, and asks for a free
 * account — there is no price in it anywhere, deliberately. The previous
 * broadcast to this list was the founding-rate offer; following it with a
 * second ask would train the list to skip these.
 *
 * Four things here are load-bearing and must stay true:
 *
 *  - "Free account" is the WHOLE offer. The wall in
 *    app/quote/[symbol]/_components/priced-in-members.tsx gates on `signedIn`
 *    and nothing else — no plan check, no trial. If that ever becomes a paid
 *    gate, this email becomes a lie and must be rewritten, not re-sent.
 *  - The free/locked split is quoted from that same file: free is the
 *    distribution, where the price sits, and what the price PAYS FOR; the
 *    account buys what it DECLINES to pay for plus the claim-by-claim
 *    evidence. Getting this backwards sends people to a wall where the email
 *    promised a door.
 *  - Every number is loaded live from `research_priced_in` by the script.
 *    Nothing about the hero is hardcoded here, so a rebuild the morning of the
 *    send reflects whatever the nightly batch last published.
 *  - The hero claims are checked before render, not asserted in prose: that the
 *    price endorses none of the published targets, that it sits below every one
 *    of them, and that the row is not stale. See broadcast-priced-in.ts.
 *
 * On the ONE revealed decline: giving away a line of the gated half is the
 * point. The offer is "this is worth an account", and the only way to make that
 * case is to show a piece of it. The script picks the decline with the largest
 * stated worth, so the reveal is the strongest one available rather than
 * whichever the generator happened to list first.
 *
 * Sent as a Resend BROADCAST, so the footer uses Resend's
 * {{{RESEND_UNSUBSCRIBE_URL}}} merge tag rather than our own signed token.
 */

export type PricedInBroadcastProps = {
  /** Distinct tickers with a published reconstruction, e.g. 543. */
  universeTickers: number;
  hero: {
    ticker: string;
    /** Price the reconstruction was computed at. */
    price: number;
    /** Published analyst price targets behind it. */
    nTargets: number;
    targetMedian: number;
    targetLow: number;
    /** True when the price is below the LOWEST published target. */
    belowEveryTarget: boolean;
    /** How far below the median, as a positive percentage. */
    medianGapPct: number;
    /** One line of the free half — what the price underwrites. */
    paysFor: string;
    /** One line of the locked half — the strongest thing it refuses. */
    decline: string;
    /** How many things it declines in total, for "the other N". */
    nDeclines: number;
  };
  /** Address in the sign-off, and the broadcast's reply-to. */
  replyEmail: string;
  /** Absolute base URL, e.g. https://newsimpactscreener.com */
  appUrl: string;
  /** Appended to every link for attribution. */
  utm?: Record<string, string>;
};

import {
  ACCENT,
  ACCENT_TEXT,
  BORDER,
  CARD,
  esc,
  MONO,
  MUTED,
  ON_ACCENT,
  P,
  PAGE,
  PANEL,
  SANS,
  TEXT,
} from "./theme";

function withUtm(url: string, utm?: Record<string, string>): string {
  if (!utm || Object.keys(utm).length === 0) return url;
  const q = Object.entries(utm)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  return url.includes("?") ? `${url}&${q}` : `${url}?${q}`;
}

const money = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function renderPricedInBroadcast(props: PricedInBroadcastProps): {
  subject: string;
  html: string;
  text: string;
} {
  const { universeTickers, hero, replyEmail, utm } = props;
  const base = props.appUrl.replace(/\/$/, "");
  const link = (path: string, content: string) =>
    withUtm(`${base}${path}`, { ...utm, utm_content: content });

  const signupUrl = link("/auth/sign-up", "priced_in_free_account");
  const heroUrl = link(`/quote/${hero.ticker}`, "priced_in_hero_quote");
  // Its own utm_content: reusing the hero's would attribute a click on the
  // directory to the AMZN page it never went to.
  const quoteHubUrl = link("/quote", "priced_in_quote_hub");

  // "Rejects all N" is only sayable when the price is under the lowest target.
  // Otherwise fall back to the median, which is true at any position. The
  // clause carries the "endorses none" half too, so the sentence around it
  // doesn't have to say "them" twice.
  const positionLine = hero.belowEveryTarget
    ? `below every single one of them, endorsing not one`
    : `${hero.medianGapPct.toFixed(0)}% below their median, endorsing none of them`;

  const subject = hero.belowEveryTarget
    ? `${hero.ticker}'s price rejects all ${hero.nTargets} analyst targets`
    : `What ${hero.ticker}'s price is actually paying for`;

  const preheader =
    `What a price pays for is public. What it refuses to pay for is behind a free account — ` +
    `on ${universeTickers} companies.`;

  const SPLIT: [string, string][] = [
    [
      "Open to everyone",
      "the spread of published targets, where the price sits inside it, and what that price pays for",
    ],
    [
      "Free account",
      "what it declines to pay for, what each of those is worth, and the claim-by-claim evidence for and against",
    ],
  ];

  const splitRows = SPLIT.map(
    ([name, detail]) => `
      <tr>
        <td style="padding:0 0 9px 0;font-family:${SANS};font-size:14px;line-height:1.55;color:${TEXT};">
          <strong style="color:${ACCENT_TEXT};">${name}</strong>
          <span style="color:${MUTED};"> &mdash; ${detail}</span>
        </td>
      </tr>`,
  ).join("");

  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <meta name="color-scheme" content="light" />
    <meta name="supported-color-schemes" content="light" />
    <title>${esc(subject)}</title>
  </head>
  <body style="margin:0;padding:0;background:${PAGE};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;color:${PAGE};">
      ${esc(preheader)}
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${PAGE};padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="max-width:540px;background:${CARD};border:1px solid ${BORDER};border-radius:14px;overflow:hidden;">

            <tr>
              <td style="padding:26px 28px 0 28px;">
                <p style="font-family:${MONO};font-size:11px;font-weight:600;letter-spacing:0.16em;text-transform:uppercase;color:${ACCENT_TEXT};margin:0 0 18px 0;">
                  News Impact Screener
                </p>

                <h1 style="font-family:${SANS};font-size:22px;line-height:1.35;font-weight:700;color:${TEXT};margin:0 0 16px 0;">
                  A share price is an argument. We take it apart.
                </h1>

                <p style="${P}">
                  Every quote page on the site now carries a panel called
                  <strong style="color:${TEXT};">Priced In</strong>. It reads the analyst models
                  published on a company, works out what the market is already paying for, and
                  separates that from what the market is
                  <strong style="color:${TEXT};">refusing</strong> to pay for.
                  ${universeTickers} companies, rebuilt nightly.
                </p>

                <p style="${P}">
                  Here is one, as it stands today.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:6px 28px 0 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                       style="background:${PANEL};border:1px solid ${BORDER};border-radius:10px;">
                  <tr>
                    <td style="padding:16px 18px;">
                      <p style="font-family:${MONO};font-size:13px;font-weight:700;letter-spacing:0.04em;color:${TEXT};margin:0 0 4px 0;">
                        ${esc(hero.ticker)} &middot; ${money(hero.price)}
                      </p>
                      <p style="font-family:${SANS};font-size:13px;line-height:1.55;color:${MUTED};margin:0 0 14px 0;">
                        ${hero.nTargets} published analyst targets, median ${money(hero.targetMedian)}.
                        The price sits ${positionLine}.
                      </p>

                      <p style="font-family:${MONO};font-size:10px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:${MUTED};margin:0 0 5px 0;">
                        The price pays for
                      </p>
                      <p style="font-family:${SANS};font-size:14px;line-height:1.55;color:${TEXT};margin:0 0 14px 0;">
                        ${esc(hero.paysFor)}
                      </p>

                      <p style="font-family:${MONO};font-size:10px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:${ACCENT_TEXT};margin:0 0 5px 0;">
                        It declines to pay for
                      </p>
                      <p style="font-family:${SANS};font-size:14px;line-height:1.55;color:${TEXT};margin:0;">
                        ${esc(hero.decline)}
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="padding:18px 28px 0 28px;">
                <p style="${P}">
                  That second half is the one worth having, and it is the half behind an account:
                  the other ${hero.nDeclines - 1} things ${esc(hero.ticker)}&rsquo;s price refuses to
                  underwrite, what each one is worth, and the evidence for and against every claim
                  it rests on.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:0 28px 0 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                       style="background:${PANEL};border:1px solid ${BORDER};border-radius:10px;">
                  <tr>
                    <td style="padding:16px 18px;">
                      <p style="font-family:${MONO};font-size:10px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:${MUTED};margin:0 0 12px 0;">
                        Where the line is
                      </p>
                      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                        ${splitRows}
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="padding:20px 28px 0 28px;">
                <a href="${signupUrl}"
                   style="display:inline-block;font-family:${SANS};font-size:15px;font-weight:600;color:${ON_ACCENT};background:${ACCENT};padding:12px 24px;border-radius:8px;text-decoration:none;">
                  Create a free account &rarr;
                </a>
                <p style="font-family:${SANS};font-size:13px;line-height:1.6;color:${MUTED};margin:12px 0 0 0;">
                  Free, and no card &mdash; this one is not a trial. Or read
                  <a href="${heroUrl}" style="color:${ACCENT_TEXT};text-decoration:none;font-weight:600;">${esc(hero.ticker)}&rsquo;s
                  reconstruction</a> first; the free half is on the page right now.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:22px 28px 0 28px;">
                <p style="${P}margin-bottom:10px;">
                  &mdash; Kasper,
                  <a href="mailto:${esc(replyEmail)}" style="color:${ACCENT_TEXT};text-decoration:none;">${esc(replyEmail)}</a>
                </p>
                <p style="font-family:${SANS};font-size:14px;line-height:1.6;color:${MUTED};margin:0;">
                  <strong style="color:${TEXT};">P.S.</strong> There is no model judgement in the
                  part you see &mdash; the distribution is arithmetic on other people&rsquo;s published
                  targets. What we add is the reconstruction underneath it, and it runs across all
                  ${universeTickers} companies, so whatever you actually hold is probably
                  <a href="${quoteHubUrl}" style="color:${ACCENT_TEXT};text-decoration:none;font-weight:600;">already in there</a>.
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
    "A share price is an argument. We take it apart.",
    "",
    "Every quote page on the site now carries a panel called Priced In. It reads the",
    "analyst models published on a company, works out what the market is already paying",
    "for, and separates that from what the market is REFUSING to pay for.",
    `${universeTickers} companies, rebuilt nightly.`,
    "",
    "Here is one, as it stands today.",
    "",
    `  ${hero.ticker} · ${money(hero.price)}`,
    `  ${hero.nTargets} published analyst targets, median ${money(hero.targetMedian)}.`,
    `  The price sits ${positionLine}.`,
    "",
    "  THE PRICE PAYS FOR",
    `  ${hero.paysFor}`,
    "",
    "  IT DECLINES TO PAY FOR",
    `  ${hero.decline}`,
    "",
    "That second half is the one worth having, and it is the half behind an account:",
    `the other ${hero.nDeclines - 1} things ${hero.ticker}'s price refuses to underwrite, what each one is worth,`,
    "and the evidence for and against every claim it rests on.",
    "",
    "WHERE THE LINE IS",
    ...SPLIT.map(([name, detail]) => `  ${name} — ${detail}`),
    "",
    `Create a free account: ${signupUrl}`,
    "",
    `Free, and no card — this one is not a trial. Or read ${hero.ticker}'s reconstruction`,
    `first; the free half is on the page right now: ${heroUrl}`,
    "",
    `— Kasper, ${replyEmail}`,
    "",
    "P.S. There is no model judgement in the part you see — the distribution is arithmetic",
    "on other people's published targets. What we add is the reconstruction underneath it,",
    `and it runs across all ${universeTickers} companies, so whatever you actually hold is probably`,
    "already in there.",
    "",
    "---",
    "Research and data, not investment advice.",
    "You signed up at newsimpactscreener.com.",
    "Unsubscribe: {{{RESEND_UNSUBSCRIBE_URL}}}",
  ].join("\n");

  return { subject, html, text };
}
