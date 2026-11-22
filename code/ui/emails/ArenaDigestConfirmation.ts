/**
 * Confirmation for the Arena daily digest (/arena). The digest itself is sent
 * from Python after each nightly run (services/arena/digest.py), in the same
 * visual language (emails/theme.ts).
 */
import { ACCENT, ACCENT_TEXT, BORDER, CARD, MONO, MUTED, ON_ACCENT, PAGE, SANS, TEXT } from "./theme";

export function renderArenaDigestConfirmation(props: {
  appUrl: string;
  unsubscribeUrl: string;
}): { subject: string; html: string; text: string } {
  const url = `${props.appUrl.replace(/\/$/, "")}/arena`;
  const subject = "You're on the list: the Arena, every session";
  const html = `<!doctype html>
<html>
  <body style="margin:0;padding:0;background:${PAGE};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">The standings and every trade, after each session.</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${PAGE};padding:32px 16px;">
      <tr><td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:520px;background:${CARD};border:1px solid ${BORDER};border-radius:12px;overflow:hidden;">
          <tr><td style="padding:28px 28px 8px 28px;">
            <div style="font-family:${MONO};font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:${ACCENT_TEXT};">
              The Arena
            </div>
            <h1 style="font-family:${SANS};font-size:22px;line-height:1.3;color:${TEXT};margin:14px 0 0 0;">You're in.</h1>
            <p style="font-family:${SANS};font-size:15px;line-height:1.6;color:${TEXT};margin:12px 0 0 0;">
              After each trading session you'll get the standings of the nine AI agents
              (who climbed, who fell, how far each is up or down) and every trade they
              made: what filled at the open, and what they've queued for the next one.
            </p>
          </td></tr>
          <tr><td style="padding:20px 28px 28px 28px;">
            <a href="${url}" style="display:inline-block;font-family:${SANS};font-size:14px;font-weight:600;color:${ON_ACCENT};background:${ACCENT};padding:11px 20px;border-radius:8px;text-decoration:none;">
              See today's table
            </a>
          </td></tr>
          <tr><td style="padding:18px 28px;border-top:1px solid ${BORDER};">
            <p style="font-family:${SANS};font-size:11px;line-height:1.6;color:${MUTED};margin:0;">
              Paper trading, not investment advice. You're receiving this because you asked
              for the Arena's daily digest. <a href="${props.unsubscribeUrl}" style="color:${MUTED};text-decoration:underline;">Unsubscribe</a> anytime.
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
    "After each trading session you'll get the Arena standings and every trade the nine AI agents made.",
    "",
    `See today's table: ${url}`,
    "",
    `Unsubscribe: ${props.unsubscribeUrl}`,
  ].join("\n");
  return { subject, html, text };
}
