import { EMAIL_FROM, EMAIL_REPLY_TO, getResend } from "./client";

export type SendEmailResult =
  | { ok: true; id: string }
  | { ok: false; error: string };

export type SendEmailInput = {
  to: string | string[];
  subject: string;
  html: string;
  text?: string;
  from?: string;
  replyTo?: string;
  tags?: { name: string; value: string }[];
};

export type SendTemplateEmailInput = {
  to: string | string[];
  templateId: string;
  variables?: Record<string, string | number>;
  /** Optional override; defaults to the stored template's "from". */
  from?: string;
  /** Optional override; defaults to the stored template's subject. */
  subject?: string;
  replyTo?: string;
  tags?: { name: string; value: string }[];
};

/**
 * Send a transactional email via Resend with inline HTML. Never throws —
 * returns a result object so callers can decide whether to surface failure.
 */
export async function sendEmail(input: SendEmailInput): Promise<SendEmailResult> {
  let resend;
  try {
    resend = getResend();
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }

  const { data, error } = await resend.emails.send({
    from: input.from ?? EMAIL_FROM,
    to: input.to,
    subject: input.subject,
    html: input.html,
    text: input.text,
    replyTo: input.replyTo ?? EMAIL_REPLY_TO,
    tags: input.tags,
  });

  if (error) return { ok: false, error: error.message };
  if (!data?.id) return { ok: false, error: "Resend returned no message id" };
  return { ok: true, id: data.id };
}

/**
 * Send a transactional email by Resend stored-template ID (or alias).
 * Variables are interpolated server-side by Resend. `from` and `subject`
 * default to the values configured on the template itself.
 * Never throws.
 */
export async function sendTemplateEmail(
  input: SendTemplateEmailInput,
): Promise<SendEmailResult> {
  let resend;
  try {
    resend = getResend();
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }

  const { data, error } = await resend.emails.send({
    to: input.to,
    template: { id: input.templateId, variables: input.variables },
    // Resend rejects the send unless `from` is set somewhere — the template
    // itself can carry it, but we fall back to EMAIL_FROM so templates that
    // omit it still work.
    from: input.from ?? EMAIL_FROM,
    subject: input.subject,
    replyTo: input.replyTo ?? EMAIL_REPLY_TO,
    tags: input.tags,
  });

  if (error) return { ok: false, error: error.message };
  if (!data?.id) return { ok: false, error: "Resend returned no message id" };
  return { ok: true, id: data.id };
}
