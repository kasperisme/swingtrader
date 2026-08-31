import { EMAIL_FROM, EMAIL_REPLY_TO, getResend } from "./client";

/**
 * Resend Broadcasts — the campaign counterpart to send.ts.
 *
 * Broadcasts differ from transactional sends in three ways that matter here:
 * they target a Segment rather than an address list, Resend appends its own
 * unsubscribe handling (so the body uses the {{{RESEND_UNSUBSCRIBE_URL}}} merge
 * tag rather than our signed token), and creation is decoupled from sending.
 * We always create as a DRAFT — the send is a deliberate click in the Resend
 * dashboard, never a side effect of running a script.
 *
 * Same contract as send.ts: never throws, returns a result object.
 */

export type BroadcastResult =
  | { ok: true; id: string }
  | { ok: false; error: string };

export type CreateBroadcastInput = {
  /** Segment to target. */
  segmentId: string;
  /** Internal name shown in the Resend dashboard's broadcast list. */
  name: string;
  subject: string;
  html: string;
  text?: string;
  /** Inbox preview snippet, shown beside the subject. */
  previewText?: string;
  from?: string;
  replyTo?: string;
};

/**
 * Create a broadcast as a DRAFT. Review and send it from the Resend dashboard.
 * There is deliberately no `send: true` path in this module.
 */
export async function createBroadcastDraft(
  input: CreateBroadcastInput,
): Promise<BroadcastResult> {
  let resend;
  try {
    resend = getResend();
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }

  const { data, error } = await resend.broadcasts.create({
    segmentId: input.segmentId,
    name: input.name,
    subject: input.subject,
    html: input.html,
    text: input.text,
    previewText: input.previewText,
    from: input.from ?? EMAIL_FROM,
    replyTo: input.replyTo ?? EMAIL_REPLY_TO,
  } as Parameters<typeof resend.broadcasts.create>[0]);

  if (error) return { ok: false, error: error.message };
  if (!data?.id) return { ok: false, error: "Resend returned no broadcast id" };
  return { ok: true, id: data.id };
}

/** Find a segment by exact name, or create it. Returns its id. */
export async function ensureSegment(
  name: string,
): Promise<BroadcastResult> {
  let resend;
  try {
    resend = getResend();
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }

  const list = await resend.segments.list();
  if (list.error) return { ok: false, error: list.error.message };

  const existing = (list.data?.data ?? []).find((s) => s.name === name);
  if (existing) return { ok: true, id: existing.id };

  const created = await resend.segments.create({ name });
  if (created.error) return { ok: false, error: created.error.message };
  if (!created.data?.id) {
    return { ok: false, error: "Resend returned no segment id" };
  }
  return { ok: true, id: created.data.id };
}
