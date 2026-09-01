"use client";

import { useEffect } from "react";
import { captureAttribution } from "@/lib/attribution";

/**
 * Record first-touch ad attribution on EVERY page, once per visitor.
 *
 * `captureAttribution` used to be called only from inside the two lead-magnet
 * subscribe forms, which was enough while every ad pointed at a free email
 * capture. It stops being enough the moment an ad lands somewhere else: a
 * visitor who arrives on /pricing or /quote/<symbol> from an ad and subscribes
 * would have had no cookie to attribute the sale with, so the subscription
 * would be recorded as organic and the campaign that paid for it would look
 * like it produced nothing.
 *
 * Mounted in the root layout so the landing page no longer has to know it is a
 * landing page. First-touch still wins (the function returns early once the
 * cookie exists), and an organic visit writes nothing at all.
 */
export function AttributionCapture() {
  useEffect(() => captureAttribution(), []);
  return null;
}
