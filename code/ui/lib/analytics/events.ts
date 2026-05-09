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
  trade_logged: { trade_id: string; ticker: string; side: string };

  feature_viewed: { feature: string };

  waitlist_joined: { source: string };
  checkout_initiated: { plan: string; interval: string };
  api_key_created: { scopes: string[] };
  api_key_revoked: Record<string, never>;
  onboarding_completed: { skipped: boolean };
  onboarding_step_clicked: { step: string };
  onboarding_dismissed: { completed_steps: number; total_steps: number };
  onboarding_collapsed_toggled: { collapsed: boolean };
  onboarding_restarted: { completed_steps: number; total_steps: number };
  ask_ai_reminder_clicked: Record<string, never>;
};

export function track<K extends keyof EventMap>(
  event: K,
  properties?: EventMap[K],
) {
  const ph = getPosthog();
  ph?.capture(event, properties);
}
