import { RESEND_WAITLIST_SEGMENT_ID, getResend } from "./client";

export type AddContactResult =
  | { ok: true; skipped?: boolean }
  | { ok: false; error: string };

/**
 * Add a contact to one or more Resend segments. Idempotent: duplicate
 * contacts return ok=true. If `segmentIds` is empty (or undefined), skips
 * silently so dev environments without segment config don't fail.
 */
export async function addContactToSegments(args: {
  email: string;
  segmentIds: (string | undefined)[];
  firstName?: string;
  lastName?: string;
}): Promise<AddContactResult> {
  const segments = args.segmentIds.filter((id): id is string => Boolean(id));
  if (segments.length === 0) return { ok: true, skipped: true };

  let resend;
  try {
    resend = getResend();
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }

  const { error } = await resend.contacts.create({
    email: args.email,
    firstName: args.firstName,
    lastName: args.lastName,
    unsubscribed: false,
    segments: segments.map((id) => ({ id })),
  });

  if (error) {
    const msg = error.message ?? "";
    if (/already exists/i.test(msg) || /duplicate/i.test(msg)) {
      return { ok: true };
    }
    return { ok: false, error: msg };
  }
  return { ok: true };
}

/** Convenience wrapper for waitlist signups. */
export function addToWaitlistSegment(email: string): Promise<AddContactResult> {
  return addContactToSegments({
    email,
    segmentIds: [RESEND_WAITLIST_SEGMENT_ID],
  });
}
