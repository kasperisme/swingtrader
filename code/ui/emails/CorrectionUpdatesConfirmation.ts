/**
 * Confirmation for the correction stress-test updates list (/correction).
 * The new-analysis mail itself is sent from Python (services/drawdown/notify.py)
 * in the same visual language (emails/theme.ts).
 */
import { ACCENT, ACCENT_TEXT, BORDER, CARD, MONO, MUTED, ON_ACCENT, PAGE, SANS, TEXT, esc } from "./theme";

export function renderCorrectionUpdatesConfirmation(props: {
  appUrl: string;
  unsubscribeUrl: string;
  /** Latest published analysis date, if one exists. */
  latestAsOf?: string | null;
}): { subject: string; html: string; text: string } {
  const base = props.appUrl.replace(/\/$/, "");
  const url = `${base}/correction`;
  const latest = props.latestAsOf ? ` The latest analysis is from ${esc(props.latestAsOf)}.` : "";
  const subject = "You're on the list: correction stress test updates";
  const html = `<!doctype html>
<html>
  <body style="margin:0;padding:0;background:${PAGE};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">One email each time a new analysis is published.</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${PAGE};padding:32px 16px;">
      <tr><td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:520px;background:${CARD};border:1px solid ${BORDER};border-radius:12px;overflow:hidden;">
          <tr><td style="padding:28px 28px 8px 28px;">
            <div style="font-family:${MONO};font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:${ACCENT_TEXT};">
              Correction stress test
            </div>
            <h1 style="font-family:${SANS};font-size:22px;line-height:1.3;color:${TEXT};margin:14px 0 0 0;">You're in.</h1>
            <p style="font-family:${SANS};font-size:15px;line-height:1.6;color:${TEXT};margin:12px 0 0 0;">
              We'll email you each time a new analysis is published: which stocks' priced-in
              stories still hold after the sell-off, which ones the price already over-funds,
              and what moved since the last one.${latest}
            </p>
          </td></tr>
          <tr><td style="padding:20px 28px 28px 28px;">
            <a href="${url}" style="display:inline-block;font-family:${SANS};font-size:14px;font-weight:600;color:${ON_ACCENT};background:${ACCENT};padding:11px 20px;border-radius:8px;text-decoration:none;">
              Open the stress test
            </a>
          </td></tr>
          <tr><td style="padding:18px 28px;border-top:1px solid ${BORDER};">
            <p style="font-family:${SANS};font-size:11px;line-height:1.6;color:${MUTED};margin:0;">
              Research, not investment advice. You're receiving this because you asked for
              correction stress test updates. <a href="${props.unsubscribeUrl}" style="color:${MUTED};text-decoration:underline;">Unsubscribe</a> anytime.
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>`;
  const text = [
    "You're in.",
    "",
    "We'll email you each time a new correction stress test analysis is published." + (props.latestAsOf ? ` The latest is from ${props.latestAsOf}.` : ""),
    "",
    `Open it: ${url}`,
    "",
    `Unsubscribe: ${props.unsubscribeUrl}`,
  ].join("\n");
  return { subject, html, text };
}
