import { subscribeHandler } from "@/lib/email/update-list-routes";
import { ARENA_LIST } from "@/lib/email/update-lists";
import { renderArenaDigestConfirmation } from "@/emails/ArenaDigestConfirmation";

export const POST = subscribeHandler(ARENA_LIST, async ({ appUrl, unsubscribeUrl }) =>
  renderArenaDigestConfirmation({ appUrl, unsubscribeUrl }),
);
