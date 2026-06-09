"use client";

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
  cta_exposed: { cta: string; variant: string };
  checkout_initiated: { plan: string; interval: string };
  api_key_created: { scopes: string[] };
  api_key_revoked: Record<string, never>;
  onboarding_completed: { skipped: boolean };
  onboarding_step_clicked: { step: string };
  onboarding_dismissed: { completed_steps: number; total_steps: number };
  onboarding_collapsed_toggled: { collapsed: boolean };
  onboarding_restarted: { completed_steps: number; total_steps: number };
  ask_ai_reminder_clicked: Record<string, never>;
  setup_assistant_opened: { surface: string };
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
}
