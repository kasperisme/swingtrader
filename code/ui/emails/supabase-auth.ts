/**
 * Supabase Auth email templates.
 *
 * These are NOT sent by this codebase. They are pasted into the Supabase
 * dashboard (Authentication → Emails → Templates), which renders them with Go
 * template syntax and mails them over the Resend SMTP relay. They live here so
 * they share emails/theme.ts with everything else we send, and so the link
 * shapes are reviewed next to the routes that have to parse them.
 *
 * ── The link shape is the whole ballgame ─────────────────────────────────────
 *
 * Supabase's stock templates use `{{ .ConfirmationURL }}`, which points at
 * Supabase's own verify endpoint and then bounces to the app. We deliberately
 * do NOT use it. This app already ships app/auth/confirm/route.ts, which reads
 * `token_hash` + `type` and calls verifyOtp itself, so every link here is built
 * as:
 *
 *   {{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=<t>&next=<path>
 *
 * That keeps the click on our own domain and lets the route run its side
 * effects (subscription tier prime, welcome email) before redirecting.
 *
 * `type` must match @supabase/supabase-js EmailOtpType, and each template has
 * exactly one correct value — the wrong one fails verifyOtp with an opaque
 * error. `next` must match what the calling form expects:
 *
 *   signup       → /protected            (sign-up-form.tsx emailRedirectTo)
 *   recovery     → /auth/update-password (forgot-password-form.tsx redirectTo;
 *                                         update-password-form.tsx needs the
 *                                         session this route establishes)
 *   magiclink    → /protected
 *   email_change → /protected
 *   invite       → /protected
 *
 * Reauthentication is the exception: it carries a 6-digit `{{ .Token }}` and no
 * link at all, because Supabase verifies it in-page rather than over a URL.
 *
 * Magic Link carries BOTH: the link above and `{{ .Token }}` below it. The login
 * form now has a code-entry screen ("Email me a 6-digit code"), and both paths
 * redeem the same underlying OTP — so which one the reader uses is theirs to
 * choose. Reading mail on a phone while signing in on a laptop is the case the
 * link alone cannot serve.
 *
 * We still do not print `{{ .Token }}` on the rest. Supabase offers it
 * everywhere, but there is no code-entry UI for signup confirmation, password
 * reset, email change or invite — and showing a code nobody can redeem is worse
 * than showing nothing.
 */

import {
  ACCENT,
  ACCENT_TEXT,
  BORDER,
  CARD,
  MONO,
  MUTED,
  ON_ACCENT,
  PAGE,
  PANEL,
  SANS,
  TEXT,
} from "./theme";

/** EmailOtpType values app/auth/confirm/route.ts will accept. */
export type AuthEmailKind =
  | "signup"
  | "recovery"
  | "magiclink"
  | "email_change"
  | "invite"
  | "reauthentication";

export type AuthEmailTemplate = {
  /** File stem, and the dashboard template it belongs in. */
  slug: string;
  /** Paste into the template's Subject field. */
  subject: string;
  /** Which dashboard tab this goes in. */
  dashboardName: string;
  html: string;
};

/**
 * Minutes a link stays valid. Shown to the reader, so it must match
 * Authentication → Providers → Email → "Email OTP Expiration" (seconds).
 * Supabase ships 3600s; override if that setting is changed.
 */
const OTP_EXPIRY_MINUTES = Number(process.env.SUPABASE_OTP_EXPIRY_MINUTES ?? 60);

const P = `font-family:${SANS};font-size:15px;line-height:1.6;color:${TEXT};margin:0 0 14px 0;`;

/**
 * The confirm-route URL for a given flow.
 *
 * `&amp;` rather than `&`: this sits in an href, where a bare ampersand is an
 * unterminated entity reference. Browsers forgive it; some mail clients and
 * link-rewriting proxies do not.
 */
function confirmUrl(type: AuthEmailKind, next: string): string {
  return `{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&amp;type=${type}&amp;next=${encodeURIComponent(next)}`;
}

/** The card every auth email shares. */
function shell(opts: {
  heading: string;
  /** Paragraphs of body copy, already HTML-safe. */
  body: string[];
  /** Primary action, omitted for code-only emails. */
  cta?: { label: string; url: string };
  /**
   * A 6-digit `{{ .Token }}` shown BELOW the action, for readers who would
   * rather type than click. Rendered after the CTA on purpose: the link is the
   * one-tap path and stays the primary affordance; the code is the fallback for
   * a mail client that mangles links or a phone reading mail on another device.
   */
  code?: { label: string };
  /** Small print under the action. */
  footnote: string;
}): string {
  const paragraphs = opts.body.map((b) => `<p style="${P}">${b}</p>`).join("\n                ");

  const action = opts.cta
    ? `
            <tr>
              <td style="padding:6px 28px 0 28px;">
                <a href="${opts.cta.url}"
                   style="display:inline-block;font-family:${SANS};font-size:15px;font-weight:600;color:${ON_ACCENT};background:${ACCENT};padding:12px 24px;border-radius:8px;text-decoration:none;">
                  ${opts.cta.label}
                </a>
              </td>
            </tr>

            <tr>
              <td style="padding:18px 28px 0 28px;">
                <p style="font-family:${SANS};font-size:12px;line-height:1.6;color:${MUTED};margin:0 0 6px 0;">
                  Or paste this into your browser:
                </p>
                <p style="font-family:${MONO};font-size:11px;line-height:1.5;color:${MUTED};margin:0;word-break:break-all;">
                  ${opts.cta.url}
                </p>
              </td>
            </tr>`
    : "";

  const codeBlock = opts.code
    ? `
            <tr>
              <td style="padding:20px 28px 0 28px;">
                <p style="font-family:${SANS};font-size:12px;line-height:1.6;color:${MUTED};margin:0 0 8px 0;">
                  ${opts.code.label}
                </p>
                <span style="font-family:${MONO};font-size:30px;font-weight:700;letter-spacing:0.18em;color:${TEXT};display:inline-block;background:${PANEL};border:1px solid ${BORDER};border-radius:10px;padding:12px 18px;">{{ .Token }}</span>
              </td>
            </tr>`
    : "";

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <meta name="color-scheme" content="light" />
    <meta name="supported-color-schemes" content="light" />
    <title>${opts.heading}</title>
  </head>
  <body style="margin:0;padding:0;background:${PAGE};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${PAGE};padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="max-width:480px;background:${CARD};border:1px solid ${BORDER};border-radius:14px;overflow:hidden;">

            <tr>
              <td style="padding:26px 28px 0 28px;">
                <p style="font-family:${MONO};font-size:11px;font-weight:600;letter-spacing:0.16em;text-transform:uppercase;color:${ACCENT_TEXT};margin:0 0 18px 0;">
                  News Impact Screener
                </p>
                <h1 style="font-family:${SANS};font-size:20px;line-height:1.35;font-weight:700;color:${TEXT};margin:0 0 14px 0;">
                  ${opts.heading}
                </h1>
                ${paragraphs}
              </td>
            </tr>
${action}${codeBlock}
            <tr>
              <td style="padding:22px 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="border-top:1px solid ${BORDER};padding-top:14px;">
                      <p style="font-family:${SANS};font-size:11px;line-height:1.7;color:${MUTED};margin:0;">
                        ${opts.footnote}
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
}

const IGNORE = "If you didn't request this, you can ignore this email — nothing will happen.";
const EXPIRES = `This link expires in ${OTP_EXPIRY_MINUTES} minutes and can only be used once.`;

export function buildAuthEmails(): AuthEmailTemplate[] {
  return [
    {
      slug: "confirm-signup",
      dashboardName: "Confirm signup",
      subject: "Confirm your email",
      html: shell({
        heading: "Confirm your email",
        body: [
          "You're one click from your account. Confirm this address and we'll take you straight in.",
        ],
        cta: { label: "Confirm my email &rarr;", url: confirmUrl("signup", "/protected") },
        footnote: `${EXPIRES} ${IGNORE}`,
      }),
    },
    {
      slug: "reset-password",
      dashboardName: "Reset Password",
      subject: "Reset your password",
      html: shell({
        heading: "Reset your password",
        body: [
          "Use the button below to set a new password. Your current one keeps working until you do.",
        ],
        cta: {
          label: "Set a new password &rarr;",
          url: confirmUrl("recovery", "/auth/update-password"),
        },
        footnote: `${EXPIRES} ${IGNORE} Your password will not change unless you follow this link.`,
      }),
    },
    {
      slug: "magic-link",
      dashboardName: "Magic Link",
      subject: "Your sign-in link",
      html: shell({
        heading: "Your sign-in link",
        body: ["Click below and you're in. No password needed."],
        cta: { label: "Sign in &rarr;", url: confirmUrl("magiclink", "/protected") },
        code: { label: "Or enter this code on the sign-in screen:" },
        footnote: `${EXPIRES} ${IGNORE}`,
      }),
    },
    {
      slug: "change-email",
      dashboardName: "Change Email Address",
      subject: "Confirm your new email address",
      html: shell({
        heading: "Confirm your new email address",
        body: [
          "You asked to change the address on your account to <strong>{{ .NewEmail }}</strong>. Confirm it below.",
        ],
        cta: {
          label: "Confirm the change &rarr;",
          url: confirmUrl("email_change", "/protected"),
        },
        footnote: `${EXPIRES} If you didn't ask for this, ignore this email and your address stays as it is — and consider changing your password.`,
      }),
    },
    {
      slug: "invite",
      dashboardName: "Invite user",
      subject: "You've been invited to News Impact Screener",
      html: shell({
        heading: "You've been invited",
        body: [
          "Someone invited you to News Impact Screener. Accept below to set up your account.",
        ],
        cta: { label: "Accept the invite &rarr;", url: confirmUrl("invite", "/protected") },
        footnote: `${EXPIRES} ${IGNORE}`,
      }),
    },
    {
      slug: "reauthentication",
      dashboardName: "Reauthentication",
      subject: "Your verification code",
      html: shell({
        heading: "Your verification code",
        body: [
          "Enter this code to confirm it's you:",
          `<span style="font-family:${MONO};font-size:30px;font-weight:700;letter-spacing:0.18em;color:${TEXT};display:inline-block;background:${PANEL};border:1px solid ${BORDER};border-radius:10px;padding:12px 18px;">{{ .Token }}</span>`,
        ],
        footnote: `This code expires in ${OTP_EXPIRY_MINUTES} minutes. ${IGNORE}`,
      }),
    },
  ];
}
