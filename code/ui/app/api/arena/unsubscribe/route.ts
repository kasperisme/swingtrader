import { unsubscribeHandler } from "@/lib/email/update-list-routes";
import { ARENA_LIST } from "@/lib/email/update-lists";

export const GET = unsubscribeHandler(ARENA_LIST, {
  eyebrow: "The Arena",
  what: "the Arena's daily standings and trades",
  cta: { label: "Open the Arena", href: "/arena" },
});
