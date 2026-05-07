import { PostHog } from "posthog-node";

let _client: PostHog | null = null;

export function getPosthogServer(): PostHog | null {
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (!key) return null;
  if (!_client) {
    _client = new PostHog(key, {
      host: process.env.POSTHOG_HOST ?? "https://eu.i.posthog.com",
      flushAt: 1,
      flushInterval: 0,
    });
  }
  return _client;
}

export function captureServer(
  distinctId: string,
  event: string,
  properties?: Record<string, unknown>,
) {
  const ph = getPosthogServer();
  if (!ph) return;
  ph.capture({ distinctId, event, properties });
}
