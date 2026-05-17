"use server";

import { createClient } from "@/lib/supabase/server";

export type OnboardingActionResult = { ok: true } | { ok: false; error: string };

export type OnboardingStepKey =
  | "profile"
  | "articles"
  | "news_trends"
  | "relations"
  | "charts"
  | "screenings"
  | "trade"
  | "agent";

export type OnboardingProgress = {
  profile: boolean;
  articles: boolean;
  news_trends: boolean;
  relations: boolean;
  charts: boolean;
  screenings: boolean;
  trade: boolean;
  agent: boolean;
};

export type VisitStepKey = Extract<
  OnboardingStepKey,
  "profile" | "articles" | "news_trends" | "relations" | "charts" | "screenings"
>;

const VISIT_KEYS: ReadonlySet<string> = new Set([
  "profile",
  "articles",
  "news_trends",
  "relations",
  "charts",
  "screenings",
]);

export type TourKey =
  | "profile"
  | "articles"
  | "news_trends"
  | "relations"
  | "charts"
  | "screenings"
  | "trade"
  | "agent";

export type ToursState = Record<TourKey, boolean>;

const ALL_TOUR_KEYS: ReadonlyArray<TourKey> = [
  "profile",
  "articles",
  "news_trends",
  "relations",
  "charts",
  "screenings",
  "trade",
  "agent",
];

const TOUR_KEY_SET: ReadonlySet<string> = new Set(ALL_TOUR_KEYS);

/**
 * Mark the current user as having seen the welcome dialog. Idempotent —
 * subsequent calls overwrite welcomed_at, which is fine.
 */
export async function markWelcomed(): Promise<OnboardingActionResult> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      { user_id: userId, welcomed_at: new Date().toISOString() },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("[onboarding] markWelcomed failed", error.message);
    return { ok: false, error: error.message };
  }
  return { ok: true };
}

/**
 * Dismiss the on-dashboard onboarding checklist. Independent of welcomed_at
 * so the welcome dialog and the checklist can be controlled separately.
 */
export async function dismissOnboardingChecklist(): Promise<OnboardingActionResult> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      { user_id: userId, onboarding_dismissed_at: new Date().toISOString() },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("[onboarding] dismissOnboardingChecklist failed", error.message);
    return { ok: false, error: error.message };
  }
  return { ok: true };
}

/**
 * Reset the onboarding so the user can retake every tour.
 *
 * Clears three things in one upsert:
 *   - metadata.onboarding_visited → {}    (the dashboard checklist's
 *     visit-based steps: profile, articles, news_trends, relations,
 *     charts, screenings)
 *   - metadata.onboarding_tours → {}      (the per-page guided tours, so
 *     revisiting each page auto-starts its tour again)
 *   - onboarding_dismissed_at → null      (re-shows the checklist on the
 *     dashboard if it had been dismissed)
 *
 * The action-based steps (trade, agent) are derived from real data —
 * having placed a trade or scheduled an agent stays "done" because we
 * won't delete the user's data just to retake the tour.
 */
export async function restartOnboardingChecklist(): Promise<OnboardingActionResult> {
  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data: existing, error: fetchError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("metadata")
    .eq("user_id", userId)
    .maybeSingle();

  if (fetchError) {
    console.error("[onboarding] restartOnboardingChecklist fetch failed", fetchError.message);
    return { ok: false, error: fetchError.message };
  }

  const metadata = (existing?.metadata as Record<string, unknown> | undefined) ?? {};
  const nextMetadata = {
    ...metadata,
    onboarding_visited: {},
    onboarding_tours: {},
  };

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      {
        user_id: userId,
        metadata: nextMetadata,
        onboarding_dismissed_at: null,
      },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("[onboarding] restartOnboardingChecklist update failed", error.message);
    return { ok: false, error: error.message };
  }
  return { ok: true };
}

/**
 * Mark a visit-based onboarding step as completed. Stored in metadata.onboarding_visited
 * (JSONB) so adding new visit-based steps doesn't require a migration.
 */
export async function markOnboardingVisited(
  step: VisitStepKey,
): Promise<OnboardingActionResult> {
  if (!VISIT_KEYS.has(step)) return { ok: false, error: "Invalid step" };

  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data: existing, error: fetchError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("metadata")
    .eq("user_id", userId)
    .maybeSingle();

  if (fetchError) {
    console.error("[onboarding] markOnboardingVisited fetch failed", fetchError.message);
    return { ok: false, error: fetchError.message };
  }

  const metadata = (existing?.metadata as Record<string, unknown> | undefined) ?? {};
  const visited = (metadata.onboarding_visited as Record<string, boolean> | undefined) ?? {};

  if (visited[step]) return { ok: true };

  const nextMetadata = {
    ...metadata,
    onboarding_visited: { ...visited, [step]: true },
  };

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      { user_id: userId, metadata: nextMetadata },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("[onboarding] markOnboardingVisited update failed", error.message);
    return { ok: false, error: error.message };
  }
  return { ok: true };
}

/**
 * Compute checklist progress for the current user. Visit flags come from
 * user_profiles.metadata.onboarding_visited; activation flags (trade, agent)
 * are derived from real DB rows so the checklist auto-checks when the user
 * actually does the thing without needing event wiring.
 */
export async function getOnboardingProgress(): Promise<OnboardingProgress> {
  const empty: OnboardingProgress = {
    profile: false,
    articles: false,
    news_trends: false,
    relations: false,
    charts: false,
    screenings: false,
    trade: false,
    agent: false,
  };

  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return empty;

  const [profileRes, tradeRes, agentRes] = await Promise.all([
    supabase
      .schema("swingtrader")
      .from("user_profiles")
      .select("metadata")
      .eq("user_id", userId)
      .maybeSingle(),
    supabase
      .schema("swingtrader")
      .from("user_trades")
      .select("id", { count: "exact", head: true })
      .limit(1),
    supabase
      .schema("swingtrader")
      .from("user_scheduled_screenings")
      .select("id", { count: "exact", head: true })
      .limit(1),
  ]);

  const metadata = (profileRes.data?.metadata as Record<string, unknown> | undefined) ?? {};
  const visited = (metadata.onboarding_visited as Record<string, boolean> | undefined) ?? {};

  return {
    profile: Boolean(visited.profile),
    articles: Boolean(visited.articles),
    news_trends: Boolean(visited.news_trends),
    relations: Boolean(visited.relations),
    charts: Boolean(visited.charts),
    screenings: Boolean(visited.screenings),
    trade: (tradeRes.count ?? 0) > 0,
    agent: (agentRes.count ?? 0) > 0,
  };
}

/**
 * Read which per-page guided tours the user has completed. Stored in
 * metadata.onboarding_tours JSONB so adding a tour doesn't require a migration.
 */
export async function getOnboardingTours(): Promise<ToursState> {
  const empty: ToursState = {
    profile: false,
    articles: false,
    news_trends: false,
    relations: false,
    charts: false,
    screenings: false,
    trade: false,
    agent: false,
  };

  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return empty;

  const { data, error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("metadata")
    .eq("user_id", userId)
    .maybeSingle();

  if (error) {
    console.error("[onboarding] getOnboardingTours fetch failed", error.message);
    return empty;
  }

  const metadata = (data?.metadata as Record<string, unknown> | undefined) ?? {};
  const tours = (metadata.onboarding_tours as Record<string, boolean> | undefined) ?? {};

  const result = { ...empty };
  for (const key of ALL_TOUR_KEYS) {
    if (tours[key]) result[key] = true;
  }
  return result;
}

/**
 * Mark a per-page guided tour as completed. Also marks the corresponding
 * visit-step done (since completing a tour implies the user reached the page),
 * keeping the dashboard checklist in sync without a separate call.
 */
export async function markTourComplete(tour: TourKey): Promise<OnboardingActionResult> {
  if (!TOUR_KEY_SET.has(tour)) return { ok: false, error: "Invalid tour key" };

  const supabase = await createClient();
  const { data: claims } = await supabase.auth.getClaims();
  const userId = claims?.claims?.sub;
  if (!userId) return { ok: false, error: "Not authenticated" };

  const { data: existing, error: fetchError } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .select("metadata")
    .eq("user_id", userId)
    .maybeSingle();

  if (fetchError) {
    console.error("[onboarding] markTourComplete fetch failed", fetchError.message);
    return { ok: false, error: fetchError.message };
  }

  const metadata = (existing?.metadata as Record<string, unknown> | undefined) ?? {};
  const tours = (metadata.onboarding_tours as Record<string, boolean> | undefined) ?? {};
  const visited = (metadata.onboarding_visited as Record<string, boolean> | undefined) ?? {};

  const alreadyToured = Boolean(tours[tour]);
  const visitKey = VISIT_KEYS.has(tour) ? tour : null;
  const alreadyVisited = visitKey ? Boolean(visited[visitKey]) : true;

  if (alreadyToured && alreadyVisited) return { ok: true };

  const nextMetadata: Record<string, unknown> = {
    ...metadata,
    onboarding_tours: { ...tours, [tour]: true },
  };
  if (visitKey) {
    nextMetadata.onboarding_visited = { ...visited, [visitKey]: true };
  }

  const { error } = await supabase
    .schema("swingtrader")
    .from("user_profiles")
    .upsert(
      { user_id: userId, metadata: nextMetadata },
      { onConflict: "user_id" },
    );

  if (error) {
    console.error("[onboarding] markTourComplete update failed", error.message);
    return { ok: false, error: error.message };
  }
  return { ok: true };
}
