/**
 * Pre-launch open-access flag.
 *
 * While true, all plan gates are bypassed and every user gets full feature
 * access. Gates still emit `would_*` analytics events so we can see where
 * users would have been blocked, then place real paywalls there at launch.
 *
 * NOW FALSE — plan gates are live and enforced.
 *
 * This constant governs the WEB APP only. The Python agent runner mirrors it
 * from its own environment (`code/analytics/shared/billing.py` reads
 * `PRELAUNCH_OPEN_ACCESS`, defaulting to open), so enforcement is only actually
 * on when BOTH are set. Flipping one and not the other leaves agents running
 * free for users the site has already downgraded to Observer.
 */
export const PRELAUNCH_OPEN_ACCESS = false;
