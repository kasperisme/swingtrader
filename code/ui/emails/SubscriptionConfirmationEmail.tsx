/**
 * Transactional confirmation email for the lightweight (email-only) screening
 * subscription flow. The project's `sendEmail` helper takes an HTML string
 * (react-email is not installed), so this module renders to a string rather
 * than exporting a React component.
 *
 * Visual language mirrors the app: near-black background, amber accent, and
 * monospace for screening/ticker names.
 */

export type ConfirmationScreening = {
  name: string;
  slug: string;
  /** Human-readable cadence, e.g. "Every Friday at 4:00 PM ET". */
  schedule: string;
  /**
   * Snapshot of the most recent run, embedded inline so the subscriber sees
   * the picks immediately (the full table is also attached as CSV). Omitted /
   * empty when the screening hasn't produced results yet.
   */
  latest?: {
    /** ISO timestamp of the latest done run, or null if none yet. */
    runAt: string | null;
    /** Total tickers in the latest run. */
    rowCount: number;
    /** Leading tickers to show inline (already truncated by the caller). */
    symbols: string[];
  };
};

/** "Jun 6, 2026" from an ISO timestamp; empty string if unparseable. */
function formatRunDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "America/New_York",
  });
}

export type SubscriptionConfirmationProps = {
  screenings: ConfirmationScreening[];
  /** Absolute base URL, e.g. https://newsimpactscreener.com */
  appUrl: string;
  /** One-click unsubscribe URL (signed token). */
  unsubscribeUrl: string;
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
const ACCENT = "#f5a623"; // amber — the site's primary
const MONO =
  "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace";
const SANS =
  "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

export function subscriptionConfirmationSubject(
  screenings: ConfirmationScreening[],
): string {
  const first = screenings[0]?.name ?? "your screenings";
  if (screenings.length <= 1) {
    return `You're in — ${first} results coming your way`;
  }
  return `You're in — ${first} + ${screenings.length - 1} more coming your way`;
}

export function renderSubscriptionConfirmationEmail(
  props: SubscriptionConfirmationProps,
): { subject: string; html: string; text: string } {
  const { screenings, appUrl, unsubscribeUrl } = props;
  const base = appUrl.replace(/\/$/, "");
  const subject = subscriptionConfirmationSubject(screenings);

  const rows = screenings
    .map((s) => {
      const picks = s.latest?.symbols ?? [];
      const runDate = formatRunDate(s.latest?.runAt ?? null);
      const extra =
        s.latest && s.latest.rowCount > picks.length
          ? s.latest.rowCount - picks.length
          : 0;

      const latestBlock = picks.length
        ? `
          <div style="font-family:${MONO};font-size:10px;letter-spacing:0.12em;text-transform:uppercase;color:${MUTED};margin-top:12px;">
            Latest picks${runDate ? ` &middot; ${esc(runDate)}` : ""}
          </div>
          <div style="margin-top:8px;">
            ${picks
              .map(
                (sym) =>
                  `<span style="display:inline-block;font-family:${MONO};font-size:12px;color:${TEXT};background:${BG};border:1px solid ${BORDER};border-radius:6px;padding:3px 8px;margin:0 6px 6px 0;">${esc(sym)}</span>`,
              )
              .join("")}${
                extra
                  ? `<span style="display:inline-block;font-family:${SANS};font-size:12px;color:${MUTED};padding:3px 2px;">+${extra} more</span>`
                  : ""
              }
          </div>`
        : `
          <div style="font-family:${SANS};font-size:12px;color:${MUTED};margin-top:10px;">
            First results land on the next scheduled run.
          </div>`;

      return `
      <tr>
        <td style="padding:14px 16px;border-bottom:1px solid ${BORDER};">
          <a href="${base}/marketscreenings/${esc(s.slug)}"
             style="font-family:${MONO};font-size:14px;color:${TEXT};text-decoration:none;font-weight:600;">
            ${esc(s.name)}
          </a>
          <div style="font-family:${SANS};font-size:12px;color:${MUTED};margin-top:4px;">
            ${esc(s.schedule)}
          </div>
          ${latestBlock}
        </td>
        <td style="padding:14px 16px;border-bottom:1px solid ${BORDER};text-align:right;vertical-align:top;">
          <a href="${base}/marketscreenings/${esc(s.slug)}"
             style="font-family:${MONO};font-size:12px;color:${ACCENT};text-decoration:none;">
            View &rsaquo;
          </a>
        </td>
      </tr>`;
    })
    .join("");

  const html = `<!doctype html>
<html>
  <body style="margin:0;padding:0;background:${BG};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
      Confirmed — screening results are on their way.
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:${BG};padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="max-width:520px;background:${CARD};border:1px solid ${BORDER};border-radius:12px;overflow:hidden;">
            <tr>
              <td style="padding:28px 28px 8px 28px;">
                <div style="font-family:${MONO};font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:${ACCENT};">
                  News Impact Screener
                </div>
                <h1 style="font-family:${SANS};font-size:22px;line-height:1.3;color:${TEXT};margin:14px 0 0 0;">
                  You're in.
                </h1>
                <p style="font-family:${SANS};font-size:14px;line-height:1.6;color:${MUTED};margin:10px 0 0 0;">
                  You'll get results for the screening${screenings.length > 1 ? "s" : ""}
                  below on schedule. The latest picks are shown right here, and the
                  full run is attached as a CSV so you're caught up now.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px 4px 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                       style="background:${BG};border:1px solid ${BORDER};border-radius:8px;">
                  ${rows}
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px 28px 28px;">
                <a href="${base}/marketscreenings"
                   style="display:inline-block;font-family:${SANS};font-size:14px;font-weight:600;color:${BG};background:${ACCENT};padding:11px 20px;border-radius:8px;text-decoration:none;">
                  Browse all screenings
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 28px;border-top:1px solid ${BORDER};">
                <p style="font-family:${SANS};font-size:11px;line-height:1.6;color:${MUTED};margin:0;">
                  You're receiving this because you asked for these results by email.
                  <a href="${unsubscribeUrl}" style="color:${MUTED};text-decoration:underline;">Unsubscribe</a>
                  anytime.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;

  const text = [
    "You're in.",
    "",
    `You'll get results for the following on schedule (latest run attached as CSV):`,
    ...screenings.flatMap((s) => {
      const lines = [
        `- ${s.name} (${s.schedule}) — ${base}/marketscreenings/${s.slug}`,
      ];
      const picks = s.latest?.symbols ?? [];
      if (picks.length) {
        const runDate = formatRunDate(s.latest?.runAt ?? null);
        const extra =
          s.latest && s.latest.rowCount > picks.length
            ? ` +${s.latest.rowCount - picks.length} more`
            : "";
        lines.push(
          `    Latest picks${runDate ? ` (${runDate})` : ""}: ${picks.join(", ")}${extra}`,
        );
      }
      return lines;
    }),
    "",
    `Browse all screenings: ${base}/marketscreenings`,
    "",
    `Unsubscribe: ${unsubscribeUrl}`,
  ].join("\n");

  return { subject, html, text };
}
