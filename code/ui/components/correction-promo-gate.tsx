import { hasPublishedCorrection } from "@/lib/drawdown/narrative";
import { CorrectionPromo } from "@/components/correction-promo";

/** Renders the site-wide /correction promo only once an analysis is published:
 *  a promo that leads to "no run yet" would spend the visitor's one click on nothing. */
export async function CorrectionPromoGate() {
  return (await hasPublishedCorrection()) ? <CorrectionPromo /> : null;
}
