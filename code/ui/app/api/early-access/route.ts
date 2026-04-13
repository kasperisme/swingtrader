import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { createServiceClient } from "@/lib/supabase/service";

const bodySchema = z.object({
  email: z.string().trim().email().max(320),
  source: z.string().trim().max(64).optional(),
});

/**
 * Public waitlist signup from the marketing site.
 * Persists to swingtrader.early_access_signups using the service role.
 */
export async function POST(req: NextRequest) {
  let json: unknown;
  try {
    json = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid email" }, { status: 400 });
  }

  const email = parsed.data.email.toLowerCase();
  const source = parsed.data.source?.trim() || "landing";

  let supabase;
  try {
    supabase = createServiceClient();
  } catch {
    return NextResponse.json({ error: "Waitlist is temporarily unavailable." }, { status: 503 });
  }

  const { error } = await supabase
    .schema("swingtrader")
    .from("early_access_signups")
    .insert({ email, source });

  if (error) {
    // Unique violation — treat as idempotent success for UX / privacy
    if (error.code === "23505") {
      return NextResponse.json({ ok: true, duplicate: true });
    }
    console.error("[early-access] insert failed", error.message);
    return NextResponse.json({ error: "Could not save your signup. Please try again." }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
