"use client";

import { gaEvent } from "./ga";
import { getPosthog } from "./posthog";

type EventMap = {
  signup_completed: { method: "email" | "oauth"; plan?: string };
  login: { method: "email" | "oauth" };
  logout: Record<string, never>;
  upgrade_clicked: { from_plan: string; to_plan: string; surface: string };
  upgrade_completed: { plan: string };

  screening_created: { screening_id: string; trigger_condition?: string };
  screening_run: { screening_id: string; manual: boolean };
  screening_alert_received: { screening_id: string };

  agent_created: { agent_id: string; kind: string };
  agent_updated: { agent_id: string };
  agent_run: { agent_id: string; manual: boolean };

  podcast_started: { mode: "single_agent" | "multi_agent" };
  podcast_completed: { mode: "single_agent" | "multi_agent"; duration_s: number };

  article_opened: { article_id: string; source?: string };
  article_engagement: {
    article_id: number;
    slug: string;
    /** Time on this article (ms), measured from mount — SPA-nav safe. */
    dwell_ms: number;
    /** Deepest scroll reached on this article, 0–100. */
    max_scroll_pct: number;
    /** Whether the Tier-2 "go deeper" block scrolled into view. */
    reached_cta: boolean;
    /** The value-prop experiment variant the reader was assigned, if any. */
    value_prop_variant: string | null;
  };
  trade_logged: { trade_id: string; ticker: string; side: string };

  feature_viewed: { feature: string };

  waitlist_joined: { source: string };

  // Lead-magnet subscribe funnel (ad → landing → form → subscribe). `magnet` splits
  // the news briefing from the market-screening flow; `utm_content` carries the ad
  // feature so PostHog funnels segment by campaign. Pairs with the server-side
  // `briefing_subscribed` / screening subscribe events for the confirmed conversion.
  lead_form_viewed: {
    magnet: "news_briefing" | "market_screening";
    utm_content?: string;
    preset?: boolean;
  };
  lead_form_submitted: {
    magnet: "news_briefing" | "market_screening";
    utm_content?: string;
  };
  lead_form_error: {
    magnet: "news_briefing" | "market_screening";
    reason: string;
  };
  lead_subscribed: {
    magnet: "news_briefing" | "market_screening";
    utm_content?: string;
  };
  cta_exposed: { cta: string; variant: string };
  checkout_initiated: { plan: string; interval: string };
  api_key_created: { scopes: string[] };
  api_key_revoked: Record<string, never>;
  onboarding_completed: { skipped: boolean };
  // First-join onboarding funnel — one event each time a welcome-dialog step is
  // shown (video → setup → plan). Build a PostHog funnel on `step` to see where
  // new users drop off. `step_index` is 1-based; `step_count` is the total.
  onboarding_step_viewed: {
    step: "video" | "setup" | "plan";
    step_index: number;
    step_count: number;
  };
  onboarding_step_clicked: { step: string };
  onboarding_dismissed: { completed_steps: number; total_steps: number };
  onboarding_collapsed_toggled: { collapsed: boolean };
  onboarding_restarted: { completed_steps: number; total_steps: number };
  ask_ai_reminder_clicked: Record<string, never>;
  // AI setup-agent utilization. `surface` = where it was opened ("welcome" =
  // first-join dialog, "profile" = re-entry). Together these show how far the
  // agent gets a new user: opened → messages_sent (engagement) → which of the 5
  // tasks it completed → finished (summary).
  setup_assistant_opened: { surface: string };
  setup_assistant_message_sent: { surface: string; via: "typed" | "quick_reply" };
  setup_assistant_task_completed: {
    surface: string;
    task: "strategy" | "holdings" | "screenings" | "telegram" | "agent";
  };
  setup_assistant_finished: {
    surface: string;
    tasks_completed: number;
    messages_sent: number;
  };
  onboarding_exit_without_billing: Record<string, never>;

  paywall_viewed: {
    surface: string;
    user_plan: string;
    required_plan: string;
    reason?: string;
  };
  paywall_hit: {
    surface: string;
    user_plan: string;
    required_plan?: string;
    reason: string;
  };
  plan_limit_reached: {
    limit_type: "screenings_active" | "api_keys" | string;
    user_plan: string;
    used: number;
    limit: number;
  };
  schedule_frequency_blocked: {
    user_plan: string;
    requested_schedule: string;
    allowed_schedule: string;
  };
  news_trends_gate_applied: {
    user_plan: string;
    upgrade_plan: string;
    restriction_days: number;
    part: string;
  };
  watchlist_alert_attempted: {
    user_plan: string;
    blocked: boolean;
  };
  api_quota_exceeded: {
    user_plan: string;
    scope?: string;
  };

  would_paywall_hit: {
    surface: string;
    user_plan: string;
    required_plan?: string;
    reason: string;
  };
  would_plan_limit_reached: {
    limit_type: "screenings_active" | "api_keys" | string;
    user_plan: string;
    used: number;
    limit: number;
  };
  would_news_trends_gate_applied: {
    user_plan: string;
    upgrade_plan: string;
    restriction_days: number;
    part: string;
  };
};

export function track<K extends keyof EventMap>(
  event: K,
  properties?: EventMap[K],
) {
  const ph = getPosthog();
  ph?.capture(event, properties);

  // Forward the confirmed lead-magnet conversion to GA4 as `sign_up`, so GA4 stops
  // showing 0 conversions against real leads. Mark `sign_up` a Key event in GA4
  // (Admin → Events) once it starts flowing. `magnet`/`utm_content` ride along so
  // GA4 can segment by lead magnet + ad feature, mirroring the PostHog funnel.
  if (event === "lead_subscribed") {
    const p = (properties ?? {}) as EventMap["lead_subscribed"];
    gaEvent("sign_up", {
      method: "email",
      magnet: p.magnet,
      utm_content: p.utm_content,
    });
  }
}
