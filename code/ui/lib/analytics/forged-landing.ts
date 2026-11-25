/**
 * Forged-referrer landings: the signature of the headless farm that survives
 * the edge firewall.
 *
 * A first page load in a fresh tab cannot honestly have this site as its
 * referrer unless the visitor was already here, and a visitor who was already
 * here carries the PostHog or GA cookie the earlier page set. The farm sends
 * `Referer: https://www.newsimpactscreener.com/` on a cold profile every time:
 * over 3 days in Nov 2026, 2,973 such sessions came from 2,971 brand-new
 * distinct ids (1 returning), at ~1.2 events and a 0-second median.
 *
 * So a landing is treated as forged when ALL of these hold:
 *   - the referrer's host is this site,
 *   - it is a plain navigation (not reload / back-forward) in a tab with no
 *     history of its own,
 *   - and no first-party analytics identity exists yet (ph_*_posthog, _ga).
 *
 * The one human it can catch is someone whose very first page view on this
 * site happened with storage disabled and who then opened a second tab. That
 * page still renders; only analytics are skipped.
 *
 * The check runs as an inline `beforeInteractive` script so it reads the
 * storage BEFORE PostHog or gtag write their cookies; every tracker then reads
 * `window.__nisForgedLanding` and stays silent for the life of the tab.
 */
export const FORGED_LANDING_SCRIPT = `(function(){var w=window,f=false;try{
var r=document.referrer,own=false;
if(r){var a=new URL(r).hostname.replace(/^www\\./,""),b=location.hostname.replace(/^www\\./,"");own=a===b;}
if(own){
var n=w.performance&&performance.getEntriesByType?performance.getEntriesByType("navigation")[0]:null;
var t=n&&n.type?n.type:"navigate";
var fresh=t==="navigate"&&w.history.length<=1;
var seen=/(?:^|;\\s*)(_ga|ph_[^=]*_posthog)=/.test(document.cookie||"");
if(!seen){try{for(var i=0;i<localStorage.length;i++){if(/^ph_.*_posthog$/.test(localStorage.key(i)||"")){seen=true;break;}}}catch(e){}}
f=fresh&&!seen;}
}catch(e){f=false}w.__nisForgedLanding=f;})();`;

declare global {
  interface Window {
    __nisForgedLanding?: boolean;
  }
}

export function isForgedLanding(): boolean {
  return typeof window !== "undefined" && window.__nisForgedLanding === true;
}
