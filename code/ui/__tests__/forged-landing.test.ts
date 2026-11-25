import { describe, expect, it } from "vitest";

import { FORGED_LANDING_SCRIPT } from "@/lib/analytics/forged-landing";

type Env = {
  referrer?: string;
  host?: string;
  navType?: string | null;
  historyLength?: number;
  cookie?: string;
  storageKeys?: string[];
};

/** Run the inline script against a stubbed browser and return the flag it sets. */
function run(env: Env): boolean | undefined {
  const keys = env.storageKeys ?? [];
  const win: Record<string, unknown> = {
    history: { length: env.historyLength ?? 1 },
    performance: {
      getEntriesByType: () => (env.navType === null ? [] : [{ type: env.navType ?? "navigate" }]),
    },
  };
  const fn = new Function(
    "window",
    "document",
    "location",
    "performance",
    "localStorage",
    "URL",
    FORGED_LANDING_SCRIPT,
  );
  fn(
    win,
    { referrer: env.referrer ?? "", cookie: env.cookie ?? "" },
    { hostname: env.host ?? "www.newsimpactscreener.com" },
    win.performance,
    { length: keys.length, key: (i: number) => keys[i] ?? null },
    URL,
  );
  return win.__nisForgedLanding as boolean | undefined;
}

const SELF = "https://www.newsimpactscreener.com/";

describe("forged-referrer landing", () => {
  it("flags a cold-profile landing that claims to come from this site", () => {
    expect(run({ referrer: SELF })).toBe(true);
    expect(run({ referrer: "https://newsimpactscreener.com/articles" })).toBe(true);
  });

  it("passes a visitor who already has an analytics identity", () => {
    expect(run({ referrer: SELF, cookie: "a=1; ph_phc_abc_posthog=%7B%7D" })).toBe(false);
    expect(run({ referrer: SELF, cookie: "_ga=GA1.1.1.1" })).toBe(false);
    expect(run({ referrer: SELF, storageKeys: ["x", "ph_phc_abc_posthog"] })).toBe(false);
  });

  it("passes in-tab navigation, reloads and back/forward", () => {
    expect(run({ referrer: SELF, historyLength: 3 })).toBe(false);
    expect(run({ referrer: SELF, navType: "reload" })).toBe(false);
    expect(run({ referrer: SELF, navType: "back_forward" })).toBe(false);
  });

  it("passes external and empty referrers", () => {
    expect(run({ referrer: "https://www.google.com/" })).toBe(false);
    expect(run({ referrer: "https://evilnewsimpactscreener.com/" })).toBe(false);
    expect(run({ referrer: "" })).toBe(false);
  });

  it("treats a missing navigation entry as a plain navigation", () => {
    expect(run({ referrer: SELF, navType: null })).toBe(true);
  });

  it("never throws, and fails open on a malformed referrer", () => {
    expect(run({ referrer: "not a url" })).toBe(false);
  });
});
