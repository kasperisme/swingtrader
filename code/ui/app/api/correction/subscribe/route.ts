import { subscribeHandler } from "@/lib/email/update-list-routes";
import { CORRECTION_LIST } from "@/lib/email/update-lists";
import { renderCorrectionUpdatesConfirmation } from "@/emails/CorrectionUpdatesConfirmation";
import { getLatestRun } from "@/lib/drawdown/narrative";

export const POST = subscribeHandler(CORRECTION_LIST, async ({ appUrl, unsubscribeUrl }) => {
  const latest = await getLatestRun().catch(() => null);
  return renderCorrectionUpdatesConfirmation({ appUrl, unsubscribeUrl, latestAsOf: latest?.asOf ?? null });
});
