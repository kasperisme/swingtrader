/**
 * Marketing broadcast: "narrative trading" — the campaign that turns the
 * priced-in reconstruction into the reason to hold a paid plan.
 *
 * Like SubscriptionConfirmationEmail, this renders to an HTML *string* rather
 * than a React component (react-email is not installed) and mirrors the app's
 * visual language: near-black background, amber accent, monospace tickers.
 *
 * Short on purpose. The email has one job — prove the reconstruction is worth
 * paying for by handing over one real ticker's members-only half — and then
 * ask. Every number is read live from swingtrader.research_priced_in by
 * scripts/broadcast-narrative-trading.ts; nothing here is hardcoded.
 *
 * On the "first 100" framing: `listSize` is the ACTUAL reachable list, counted
 * at build time. It is used to tell recipients who they are — early — not to
 * imply seats are running out. There are no paying subscribers yet, so any
 * "X seats left" or "join N others" line would be false; the honest urgency is
 * the published price ladder in app/pricing/page.tsx, which really does step up
 * at Phase 2, and the grandfather promise, which is ours to keep.
 *
 * Sent as a Resend BROADCAST, so the footer uses Resend's
 * {{{RESEND_UNSUBSCRIBE_URL}}} merge tag rather than our own signed token.
 */

export type BroadcastDriver = {
  /** The unpriced (or partly priced) claim, verbatim from drivers_json. */
  driver: string;
  /** 0–100: how much of this the price already contains. */
  pricedInPct: number;
  /** 0–100+: upside to the current price if it proves out. */
  valueIfTruePct: number;
};

export type NarrativeTradingBroadcastProps = {
  /** Hero ticker's reconstruction — the whole email is one worked example. */
  hero: {
    ticker: string;
    price: number;
    /** Reverse-DCF implied 10-year revenue CAGR, as a percent (18.4). */
    impliedCagrPct: number;
    /** Most recent reported growth, for the contrast — as a percent. Optional. */
    recentGrowthPct: number | null;
    /** Published analyst models considered. */
    nTargets: number;
    targetMedian: number;
    /** Highest published target — the sharpest contrast with the price. */
    targetHigh: number;
    /** Models the price endorses vs rejects as too bullish. */
    nEndorsed: number;
    nRejectedBull: number;
    /** The members-only half: what the price declines to pay for. */
    drivers: BroadcastDriver[];
  };
  /** Total published reconstructions, e.g. 204. */
  universeCount: number;
  /** Actual size of the reachable list — the "first N" the reader is one of. */
  listSize: number;
  /** Full-access trial length in days. */
  trialDays: number;
  /** Founding (Phase 1) monthly prices. */
  investorPrice: number;
  traderPrice: number;
  /** The next phase's prices — what these rates become. */
  nextInvestorPrice: number;
  nextTraderPrice: number;
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

// Visual language, identical to SubscriptionConfirmationEmail.
const BG = "#0b0f17";
const CARD = "#111620";
const TEXT = "#e6e9ef";
const MUTED = "#8b93a7";
const BORDER = "#1e2533";
const ACCENT = "#f5a623";
const GREEN = "#3fb950";
const MONO =
  "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace";
const SANS =
  "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

const P = `font-family:${SANS};font-size:15px;line-height:1.6;color:${TEXT};margin:0 0 14px 0;`;

/**
 * How much of a claim the price already contains, as the same four words the
 * quote panel uses (app/quote/[symbol]/_components/priced-in-ui.tsx `band`).
 *
 * The raw priced_in_pct is deliberately NOT printed. It is an unvalidated
 * estimate, the product shows the band word rather than the number for exactly
 * that reason, and the landing page excludes it outright.
 */
function bandLabel(pricedInPct: number): string {
  if (pricedInPct <= 25) return "Unpriced";
  if (pricedInPct <= 55) return "Partly priced";
  if (pricedInPct <= 84) return "Mostly priced";
  return "Fully priced";
}

/** Cents only where there are cents — "$500.00" beside "$303.50" reads ragged. */
function usd(n: number): string {
  const places = Number.isInteger(n) ? 0 : 2;
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  })}`;
}

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
    hero,
    universeCount,
    listSize,
    trialDays,
    investorPrice,
    traderPrice,
    nextInvestorPrice,
    nextTraderPrice,
    utm,
  } = props;
  const base = props.appUrl.replace(/\/$/, "");
  const link = (path: string, content: string) =>
    withUtm(`${base}${path}`, { ...utm, utm_content: content });

  const quoteUrl = link(`/quote/${hero.ticker}`, "hero_quote");
  const trialUrl = link("/auth/sign-up", "trial");

  const subject = `${hero.ticker} isn't priced for perfection. It's priced for a slowdown.`;
  const preheader = `${hero.nTargets} analysts published targets. The price endorses none of them.`;

  const endorseLine =
    hero.nEndorsed === 0
      ? `The price endorses none of them.`
      : `The price endorses ${hero.nEndorsed} and rejects ${hero.nRejectedBull} as too bullish.`;

  const growthContrast =
    hero.recentGrowthPct != null
      ? ` &mdash; from a company that just posted ${hero.recentGrowthPct.toFixed(1)}%.`
      : `.`;

  const driverRows = hero.drivers
    .map(
      (d, i) => `
      <tr>
        <td style="padding:${i === 0 ? "0" : "9px"} 12px 9px 0;border-top:${
          i === 0 ? "none" : `1px solid ${BORDER}`
        };font-family:${SANS};font-size:13px;line-height:1.45;color:${TEXT};">
          ${esc(d.driver)}
        </td>
        <td style="padding:${i === 0 ? "0" : "9px"} 10px 9px 0;border-top:${
          i === 0 ? "none" : `1px solid ${BORDER}`
        };font-family:${SANS};font-size:12px;color:${
          d.pricedInPct <= 55 ? ACCENT : MUTED
        };text-align:right;white-space:nowrap;">
          ${esc(bandLabel(d.pricedInPct))}
        </td>
        <td style="padding:${i === 0 ? "0" : "9px"} 0 9px 0;border-top:${
          i === 0 ? "none" : `1px solid ${BORDER}`
        };font-family:${MONO};font-size:13px;font-weight:700;color:${GREEN};text-align:right;white-space:nowrap;">
          +${Math.round(d.valueIfTruePct)}%
        </td>
      </tr>`,
    )
    .join("");

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
                 style="max-width:560px;background:${CARD};border:1px solid ${BORDER};border-radius:14px;overflow:hidden;">

            <tr>
              <td style="padding:24px 28px 0 28px;">
                <p style="font-family:${MONO};font-size:11px;font-weight:600;letter-spacing:0.16em;text-transform:uppercase;color:${ACCENT};margin:0 0 18px 0;">
                  News Impact Screener
                </p>

                <h1 style="font-family:${SANS};font-size:23px;line-height:1.3;font-weight:700;color:${TEXT};margin:0 0 16px 0;">
                  You're one of the first ${listSize}.
                </h1>

                <p style="${P}">
                  That's the whole list right now. Which is why you get this before anyone
                  else &mdash; and why you get it cheapest, permanently. First, the thing itself.
                </p>

                <p style="${P}">
                  A share price is a bet on a story. We reconstruct <em style="font-style:normal;font-weight:600;color:${TEXT};">which</em>
                  story &mdash; what the price already pays for, and what it flatly refuses to.
                  It runs nightly on ${universeCount} companies.
                </p>
              </td>
            </tr>

            <!-- The proof, in one card -->
            <tr>
              <td style="padding:4px 28px 0 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                       style="background:${BG};border:1px solid ${BORDER};border-radius:10px;">
                  <tr>
                    <td style="padding:16px 18px;">
                      <p style="font-family:${MONO};font-size:15px;font-weight:700;color:${ACCENT};margin:0 0 10px 0;">
                        ${esc(hero.ticker)} &middot; ${usd(hero.price)}
                      </p>
                      <p style="font-family:${SANS};font-size:14px;line-height:1.6;color:${TEXT};margin:0;">
                        ${hero.nTargets} analysts have published targets. Median ${usd(hero.targetMedian)}.
                        <strong>${endorseLine}</strong> It's paying for revenue compounding at
                        ${hero.impliedCagrPct.toFixed(1)}% a year${growthContrast}
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="padding:18px 28px 0 28px;">
                <p style="${P}">
                  That's not &ldquo;priced for perfection.&rdquo; That's a price braced for a
                  slowdown while the sell side writes targets up to ${usd(hero.targetHigh)}. Which turns an
                  unanswerable question &mdash; is ${esc(hero.ticker)} expensive? &mdash; into a watchlist:
                </p>
              </td>
            </tr>

            <!-- The gated half -->
            <tr>
              <td style="padding:0 28px 0 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                       style="background:${BG};border:1px solid ${BORDER};border-radius:10px;">
                  <tr>
                    <td style="padding:15px 18px;">
                      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                          <td style="padding:0 12px 9px 0;font-family:${MONO};font-size:10px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:${MUTED};">
                            What it won't pay for
                          </td>
                          <td style="padding:0 10px 9px 0;font-family:${MONO};font-size:10px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:${MUTED};text-align:right;white-space:nowrap;">
                            How&nbsp;priced
                          </td>
                          <td style="padding:0 0 9px 0;font-family:${MONO};font-size:10px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:${MUTED};text-align:right;white-space:nowrap;">
                            If&nbsp;true
                          </td>
                        </tr>
                        ${driverRows}
                      </table>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="padding:16px 28px 0 28px;">
                <p style="${P}">
                  Free on the site: the distribution, and what the price pays for. Members: what
                  it <em style="font-style:normal;font-weight:600;color:${TEXT};">won't</em>, and the
                  evidence under every claim. You just read ${esc(hero.ticker)}'s locked half.
                </p>
                <a href="${quoteUrl}"
                   style="display:inline-block;font-family:${SANS};font-size:14px;font-weight:600;color:${ACCENT};text-decoration:none;border-bottom:1px solid ${ACCENT};padding-bottom:1px;">
                  See the whole reconstruction &rarr;
                </a>
              </td>
            </tr>

            <!-- The offer -->
            <tr>
              <td style="padding:24px 28px 0 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                       style="background:${BG};border:1px solid ${BORDER};border-radius:10px;">
                  <tr>
                    <td style="padding:18px;">
                      <p style="font-family:${SANS};font-size:16px;font-weight:700;color:${TEXT};margin:0 0 10px 0;">
                        Your price, for good
                      </p>
                      <p style="font-family:${SANS};font-size:14px;line-height:1.6;color:${TEXT};margin:0 0 14px 0;">
                        ${trialDays} days of the full Trader tier first, no card. After that it's
                        <strong>$${investorPrice}</strong> or <strong>$${traderPrice}</strong> a month &mdash;
                        the rate for the first hundred people here. It becomes $${nextInvestorPrice} and
                        $${nextTraderPrice} as this grows. Yours doesn't, for as long as you stay.
                      </p>
                      <a href="${trialUrl}"
                         style="display:inline-block;font-family:${SANS};font-size:14px;font-weight:600;color:${BG};background:${ACCENT};padding:11px 20px;border-radius:8px;text-decoration:none;">
                        Start the ${trialDays} days &rarr;
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <tr>
              <td style="padding:20px 28px 0 28px;">
                <p style="${P}margin-bottom:10px;">&mdash; Kasper</p>
                <p style="font-family:${SANS};font-size:14px;line-height:1.6;color:${MUTED};margin:0;">
                  <strong style="color:${TEXT};">P.S.</strong> Reply with one ticker and I'll send
                  back what its price is paying for.
                </p>
              </td>
            </tr>

            <tr>
              <td style="padding:22px 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="border-top:1px solid ${BORDER};padding-top:14px;">
                      <p style="font-family:${SANS};font-size:11px;line-height:1.7;color:${MUTED};margin:0 0 6px 0;">
                        Upside is arithmetic on published analyst targets; how priced a claim is, is an
                        estimate. Research, not investment advice &mdash; and it can be wrong.
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
    `You're one of the first ${listSize}.`,
    "",
    "That's the whole list right now. Which is why you get this before anyone else — and",
    "why you get it cheapest, permanently. First, the thing itself.",
    "",
    "A share price is a bet on a story. We reconstruct WHICH story — what the price",
    `already pays for, and what it flatly refuses to. It runs nightly on ${universeCount} companies.`,
    "",
    `${hero.ticker} · ${usd(hero.price)}`,
    `${hero.nTargets} analysts have published targets. Median ${usd(hero.targetMedian)}. ${endorseLine}`,
    `It's paying for revenue compounding at ${hero.impliedCagrPct.toFixed(1)}% a year${
      hero.recentGrowthPct != null
        ? ` — from a company that just posted ${hero.recentGrowthPct.toFixed(1)}%.`
        : "."
    }`,
    "",
    `That's not "priced for perfection." That's a price braced for a slowdown while the`,
    `sell side writes targets up to ${usd(hero.targetHigh)}. Which turns an unanswerable question — is`,
    `${hero.ticker} expensive? — into a watchlist:`,
    "",
    "WHAT IT WON'T PAY FOR",
    ...hero.drivers.map(
      (d) =>
        `  - ${d.driver} — ${bandLabel(d.pricedInPct).toLowerCase()}, +${Math.round(d.valueIfTruePct)}% if true`,
    ),
    "",
    "Free on the site: the distribution, and what the price pays for. Members: what it",
    `WON'T, and the evidence under every claim. You just read ${hero.ticker}'s locked half.`,
    "",
    `See the whole reconstruction: ${quoteUrl}`,
    "",
    "YOUR PRICE, FOR GOOD",
    `${trialDays} days of the full Trader tier first, no card. After that it's $${investorPrice} or $${traderPrice} a`,
    `month — the rate for the first hundred people here. It becomes $${nextInvestorPrice} and $${nextTraderPrice} as`,
    "this grows. Yours doesn't, for as long as you stay.",
    "",
    `Start the ${trialDays} days: ${trialUrl}`,
    "",
    "— Kasper",
    "",
    "P.S. Reply with one ticker and I'll send back what its price is paying for.",
    "",
    "---",
    "Upside is arithmetic on published analyst targets; how priced a claim is, is an",
    "estimate. Research, not investment advice — and it can be wrong.",
    "You signed up at newsimpactscreener.com.",
    "Unsubscribe: {{{RESEND_UNSUBSCRIBE_URL}}}",
  ].join("\n");

  return { subject, html, text };
}
