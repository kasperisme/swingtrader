"use server";

import { headers } from "next/headers";
import { revalidatePath } from "next/cache";
import { createServiceClient } from "@/lib/supabase/service";
import { createClient } from "@/lib/supabase/server";
import { captureServer } from "@/lib/analytics/server";

const SCHEMA = "swingtrader";

export type PublicScreening = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  category: string | null;
  schedule: string;
  timezone: string;
  last_run_at: string | null;
  last_triggered: boolean | null;
  created_at: string;
};

export type PublicScreeningResult = {
  id: string;
  run_at: string;
  triggered: boolean;
  summary: string | null;
  status: string;
};

type ActionResult<T> = Promise<{ ok: true; data: T } | { ok: false; error: string }>;

const PUBLIC_FIELDS =
  "id, slug, name, description, category, schedule, timezone, last_run_at, last_triggered, created_at";

const validEmail = (raw: string): boolean =>
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw.trim().toLowerCase());

// ── Reads (server-side, public) ─────────────────────────────────────────────

export async function listPublicScreenings(): Promise<PublicScreening[]> {
  const client = createServiceClient();
  const { data, error } = await client
    .schema(SCHEMA)
    .from("public_screenings")
    .select(PUBLIC_FIELDS)
    .eq("is_published", true)
    .order("created_at", { ascending: false });
  if (error) {
    console.error("[public-screenings] list failed", error);
    return [];
  }
  return (data ?? []) as PublicScreening[];
}

export async function getPublicScreeningBySlug(
  slug: string,
): Promise<PublicScreening | null> {
  const client = createServiceClient();
  const { data, error } = await client
    .schema(SCHEMA)
    .from("public_screenings")
    .select(PUBLIC_FIELDS)
    .eq("slug", slug)
    .eq("is_published", true)
    .limit(1)
    .maybeSingle();
  if (error) {
    console.error("[public-screenings] getBySlug failed", error);
    return null;
  }
  return (data ?? null) as PublicScreening | null;
}

export async function getPublicScreeningResults(
  screeningId: string,
  limit = 10,
): Promise<PublicScreeningResult[]> {
  const client = createServiceClient();
  const { data, error } = await client
    .schema(SCHEMA)
    .from("public_screening_results")
    .select("id, run_at, triggered, summary, status")
    .eq("public_screening_id", screeningId)
    .eq("status", "done")
    .order("run_at", { ascending: false })
    .limit(limit);
  if (error) {
    console.error("[public-screenings] getResults failed", error);
    return [];
  }
  return (data ?? []) as PublicScreeningResult[];
}

// ── Early access signup ─────────────────────────────────────────────────────

export async function submitEarlyAccessSignup(input: {
  email: string;
  screeningSlug: string;
  source?: string;
}): ActionResult<{ alreadySignedUp: boolean }> {
  const email = (input.email ?? "").trim().toLowerCase();
  if (!validEmail(email)) {
    return { ok: false, error: "Please enter a valid email address." };
  }

  const service = createServiceClient();

  // Resolve the screening (must exist and be published).
  const { data: screening } = await service
    .schema(SCHEMA)
    .from("public_screenings")
    .select("id, name")
    .eq("slug", input.screeningSlug)
    .eq("is_published", true)
    .limit(1)
    .maybeSingle();

  if (!screening) {
    return { ok: false, error: "Screening not found." };
  }

  // Best-effort: attach the current auth user if they have a session.
  let userId: string | null = null;
  try {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    userId = user?.id ?? null;
  } catch {
    userId = null;
  }

  const headerList = await headers();
  const referrer = headerList.get("referer");
  const userAgent = headerList.get("user-agent");

  const insertRes = await service
    .schema(SCHEMA)
    .from("early_access_signups")
    .insert({
      email,
      public_screening_id: screening.id,
      user_id: userId,
      source: input.source || "gallery_subscribe",
      referrer,
      user_agent: userAgent,
    });

  // Duplicate is a success path from the user's perspective.
  if (insertRes.error) {
    const isDup =
      insertRes.error.code === "23505" ||
      /duplicate key/i.test(insertRes.error.message);
    if (!isDup) {
      console.error("[public-screenings] signup insert failed", insertRes.error);
      return { ok: false, error: "Could not record signup. Please try again." };
    }
    captureServer(userId ?? email, "early_access_signup_duplicate", {
      screening_id: screening.id,
      screening_slug: input.screeningSlug,
      source: input.source || "gallery_subscribe",
    });
    return { ok: true, data: { alreadySignedUp: true } };
  }

  captureServer(userId ?? email, "early_access_signup", {
    screening_id: screening.id,
    screening_slug: input.screeningSlug,
    screening_name: screening.name,
    source: input.source || "gallery_subscribe",
    authenticated: Boolean(userId),
  });

  return { ok: true, data: { alreadySignedUp: false } };
}

// ── Real subscriptions (authed users) ───────────────────────────────────────

export async function getMySubscription(
  screeningId: string,
): Promise<{ isSubscribed: boolean; notificationsEnabled: boolean }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { isSubscribed: false, notificationsEnabled: false };

  const { data } = await supabase
    .schema(SCHEMA)
    .from("public_screening_subscriptions")
    .select("notifications_enabled")
    .eq("user_id", user.id)
    .eq("public_screening_id", screeningId)
    .limit(1)
    .maybeSingle();

  if (!data) return { isSubscribed: false, notificationsEnabled: false };
  return {
    isSubscribed: true,
    notificationsEnabled: Boolean(data.notifications_enabled),
  };
}

export async function subscribeToPublicScreening(
  screeningSlug: string,
): ActionResult<{ alreadySubscribed: boolean }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { ok: false, error: "You must be signed in to subscribe." };
  }

  const service = createServiceClient();
  const { data: screening } = await service
    .schema(SCHEMA)
    .from("public_screenings")
    .select("id, name")
    .eq("slug", screeningSlug)
    .eq("is_published", true)
    .limit(1)
    .maybeSingle();

  if (!screening) {
    return { ok: false, error: "Screening not found." };
  }

  // public_screening_subscriptions is the only subscription record we keep.
  // Public screenings are platform-managed; results land in user_scan_runs +
  // user_scan_rows + user_screening_results at execution time, not as a
  // user_scheduled_screenings row.
  const subRes = await supabase
    .schema(SCHEMA)
    .from("public_screening_subscriptions")
    .insert({
      user_id: user.id,
      public_screening_id: screening.id,
    });

  if (subRes.error) {
    const isDup =
      subRes.error.code === "23505" ||
      /duplicate key/i.test(subRes.error.message);
    if (!isDup) {
      console.error("[public-screenings] subscribe failed", subRes.error);
      return { ok: false, error: "Could not subscribe. Please try again." };
    }
    revalidatePath(`/screenings/${screeningSlug}`);
    return { ok: true, data: { alreadySubscribed: true } };
  }

  captureServer(user.id, "public_screening_subscribed", {
    screening_id: screening.id,
    screening_slug: screeningSlug,
    screening_name: screening.name,
  });

  revalidatePath(`/screenings/${screeningSlug}`);
  return { ok: true, data: { alreadySubscribed: false } };
}

export async function unsubscribeFromPublicScreening(
  screeningSlug: string,
): ActionResult<{ removed: boolean }> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { ok: false, error: "You must be signed in." };
  }

  const service = createServiceClient();
  const { data: screening } = await service
    .schema(SCHEMA)
    .from("public_screenings")
    .select("id")
    .eq("slug", screeningSlug)
    .limit(1)
    .maybeSingle();

  if (!screening) {
    return { ok: false, error: "Screening not found." };
  }

  const del = await supabase
    .schema(SCHEMA)
    .from("public_screening_subscriptions")
    .delete()
    .eq("user_id", user.id)
    .eq("public_screening_id", screening.id);

  if (del.error) {
    console.error("[public-screenings] unsubscribe failed", del.error);
    return { ok: false, error: "Could not unsubscribe. Please try again." };
  }

  captureServer(user.id, "public_screening_unsubscribed", {
    screening_id: screening.id,
    screening_slug: screeningSlug,
  });

  revalidatePath(`/screenings/${screeningSlug}`);
  return { ok: true, data: { removed: true } };
}
