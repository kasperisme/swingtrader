import { unsubscribeHandler } from "@/lib/email/update-list-routes";
import { CORRECTION_LIST } from "@/lib/email/update-lists";

export const GET = unsubscribeHandler(CORRECTION_LIST, {
  eyebrow: "Correction stress test",
  what: "correction stress test updates",
  cta: { label: "Open the stress test", href: "/correction" },
});
