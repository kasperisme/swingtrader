/**
 * Pre-launch open-access flag.
 *
 * While true, all plan gates are bypassed and every user gets full feature
 * access. Gates still emit `would_*` analytics events so we can see where
 * users would have been blocked, then place real paywalls there at launch.
 *
 * Flip to `false` at launch.
 */
export const PRELAUNCH_OPEN_ACCESS = true;
