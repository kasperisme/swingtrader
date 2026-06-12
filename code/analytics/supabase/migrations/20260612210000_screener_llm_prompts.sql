-- Set the bulk-analysis llm_prompt for three published screenings. When a
-- screening has llm_prompt set, the bulk-analytics worker runs one chart-AI
-- pass per ticker (price snapshot in, strict JSON out: status + comment +
-- analysis_markdown), and fan-out is deferred until that enrichment lands.
--
-- Matched by script_key (stable). Idempotent — re-running re-sets the same text.
-- Dollar-quoted ($p$…$p$) so apostrophes/newlines need no escaping.

-- ── AI Supercycle ────────────────────────────────────────────────────────────
UPDATE swingtrader.market_screenings SET
    llm_prompt = $p$This ticker is part of the AI Supercycle basket — a curated set of AI-infrastructure names (compute, memory, networking/optics, semicap, power & thermal, hyperscalers) tracked against a momentum + growth-fundamentals screen. Using the price snapshot, judge the swing-trade setup over a 2-10 day horizon:
- pipeline:  clean, actionable setup — uptrend with price above rising 50/150/200-day MAs, in a tight base or breaking out near support, not extended.
- watchlist: constructive trend but needs confirmation — basing, pulling back to support, or below a key MA awaiting a reclaim.
- active:    in an uptrend but extended or mid-range; note it, no immediate action.
- dismissed: broken structure, downtrend, or below the long-term MAs.
comment (<=140 chars): the setup plus the trigger or stop level.
analysis_markdown: 2-4 sentences on trend, key levels, and what confirms or invalidates the idea.$p$,
    updated_at = NOW()
WHERE script_key = 'ai_supercycle';

-- ── IPO Screener ─────────────────────────────────────────────────────────────
UPDATE swingtrader.market_screenings SET
    llm_prompt = $p$This ticker IPO'd within the last year and surfaced on the IPO screen (the same momentum + growth screen as AI Supercycle, run on shorter moving-average history). Recent IPOs base differently — judge the post-IPO setup from the price snapshot, accounting for the limited history (it may not have a full 200-day trend yet):
- pipeline:  constructive post-IPO action — holding above its IPO range / key MAs, a tight base or first-base breakout on volume, not extended.
- watchlist: still building its first base, choppy, or below key MAs — needs confirmation.
- active:    in an uptrend but extended or only thinly established; note it.
- dismissed: broken below its IPO range, clear downtrend, or no setup.
comment (<=140 chars): the setup plus the key level.
analysis_markdown: 2-4 sentences on the post-IPO structure, key levels, and the trigger that confirms or invalidates.$p$,
    updated_at = NOW()
WHERE script_key = 'ipo_screener';

-- ── Insider & Congress Activity ──────────────────────────────────────────────
UPDATE swingtrader.market_screenings SET
    llm_prompt = $p$This ticker came from the "Insider & Congress Activity" screen: it has recently disclosed open-market trades by company insiders (executives/directors) and/or members of Congress. Treat that as the thesis and use the price snapshot to test it. Judge whether the technicals confirm the smart-money signal:
- pipeline:  buying interest + a clean, actionable setup — uptrend or tight base near support, holding key moving averages, not extended.
- watchlist: constructive but unconfirmed — still basing, below key MAs, or awaiting a trigger.
- active:    mixed or unclear — note it, no action.
- dismissed: broken chart / clear downtrend, or activity that reads as routine selling with no setup.
comment (<=140 chars): the net tilt you'd act on and the key level.
analysis_markdown: 2-4 sentences linking the insider/Congress angle to the chart, and the price level that confirms or invalidates.$p$,
    updated_at = NOW()
WHERE script_key = 'insider_congress';
