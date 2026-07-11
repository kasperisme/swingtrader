-- Activate the NIS Short market screening.
-- Insert a published market_screenings row bound to script_key = 'nis_short'.
-- The llm_prompt below opts it into the per-ticker bulk-analytics pass.

insert into swingtrader.market_screenings (name, slug, script_key, category, is_active, is_published, author_user_id, description, llm_prompt)
values (
  'NIS Short',
  'nis-short',
  'nis_short',
  'technical-fundamental',
  true,
  true,
  '1077d309-5a94-441b-b8d3-52c40c6a45e0',
$desc$The short-side inverse of NIS Momentum, applying Minervini SEPA / O'Neil CAN SLIM to the SHORT side. Targets FORMER LEADERS rolling over into a Stage-4 decline — distribution and failure — not perennial losers already at new lows. The whole screen is gated on a bearish market regime (only runs when the S&P is below its 200-day).

Pipeline:
  0. Market regime gate: skip entirely unless the S&P 500 is below its 200-day MA.
  1. Universe: all listed NYSE + NASDAQ tickers.
  2. Inverted pre-screen: actively traded, price < SMA200, SMA50 < SMA200,
     at least 25% below the 52-week high, AND weak RS (bottom ~30%, RS < 30).
  3. Stage-4 decline template — all conditions required:
       • close < SMA50 < SMA150 < SMA200
       • SMA200 falling (20-day slope confirmation)
       • close at least 25% below the 52-week high, and that high is stale
         (made months ago — peak at least ~5 weeks old)
       • RS weak (RS < 30 — the inverse of the long side's RS > 70)
  4. Former-leader gate (most important): ran 100%+ from a prior trough into
     its peak over the last 1–3 years, and the peak is at least ~5 weeks old
     (O'Neil: best shorts are 5–15 weeks after the top, not at the peak).
  5. Distribution volume: down-days heavier than up-days over 50 sessions
     (up/down-volume ratio at or below 0.85 — the inverse of accumulation).
  6. Decelerating fundamentals: EPS momentum not accelerating AND (EPS SMA
     turning down OR a recent earnings miss) — deceleration/disappointment,
     not absolute badness.
  7. Liquidity floor: enough average daily dollar volume to borrow and exit.
  8. A ticker is reported only if it passes EVERY technical AND fundamental gate.

Output includes the symbol, sector, sub-sector, RS, all Stage-4 technical flags, former-leader/timing metrics (prior-advance %, % below the high, peak age, distance to the declining 50-day = overhead resistance), volume/liquidity, and the deceleration fundamental flags. Squeeze risk (high short interest / days-to-cover) and the exact rally-into-resistance entry are assessed downstream by the AI analysis pass.$desc$,
$prompt$You are a short-selling analyst applying Minervini SEPA and O'Neil CAN SLIM methodology to the SHORT side.
You receive ONE ticker at a time that has already passed a Stage-4 decline template + former-leader + decelerating-fundamentals screen, in a confirmed market downtrend.

Core principle: you short FORMER LEADERS rolling over after a climax — distribution and failure — NOT weakness already priced in. Never short the exact top (squeeze risk); the best shorts are 5–15 weeks after the top, on a weak RALLY back up into resistance (a broken support level or the declining 50-day), with a hard stop just above.

──────────────────────────────────────────
INPUT YOU WILL RECEIVE
──────────────────────────────────────────
- Ticker, current price, ADR%
- SMA50, SMA150, SMA200 (all should be stacked bearishly above price)
- 52-week low, 52-week high; % below the 52-week high; peak age (sessions since the high)
- prior_advance_pct (the run into the peak — the "former leader" evidence)
- RS (0-100, weak) / RS_Rank
- up_down_vol_ratio (≤ ~0.85 = distribution), vol_ratio_today
- dist_to_sma50_pct (how far a bounce is from the declining 50-day = overhead resistance)
- Market regime (should be downtrend / correction)

──────────────────────────────────────────
DELIVER
──────────────────────────────────────────

1. VERDICT — one of: active / pipeline / watchlist / dismissed
   active    → price is rallying into resistance (broken support or declining
               50-day) NOW, a hard stop sits just above a structural level,
               market regime is a confirmed downtrend.
   pipeline  → resistance test reachable within ~1 week; structural stop exists.
   watchlist → topping structure (H&S / failed late-stage base) still forming,
               or price is extended to the DOWNSIDE (do not short into the hole).
   dismissed → not a former leader, at/near new lows already, high short interest
               (squeeze risk), illiquid, or the market is not in a downtrend.

2. THESIS — the topping/failure pattern you see:
   - Head-and-shoulders top (short the neckline break, or a weak rally back to it)?
   - Late-stage failed base / breakout failure that cracked the 50-day on volume?
   - Is the rally into resistance on LIGHT volume (weak bounce = good short entry)?
   Grade: A / B / C / F

3. ENTRY PARAMETERS
   - Resistance level to short into (broken support / declining 50-day / neckline)
   - Ideal short range: at/just below that resistance on a weak bounce
   - Suggested stop: a structural level ABOVE resistance (swing high / above 50-day).
     Express as both price and % risk. Losses on shorts are unbounded — stop
     discipline matters more than on the long side.
   - Cover target: prior support / measured move / next demand zone; note R:R.

4. RISK FLAGS — only flag what's real
   - Short-squeeze fuel (very high short interest / days-to-cover) → avoid
   - Extended to the downside (already far below 50-day) — wait for a bounce
   - Low ADR% (<3%) — insufficient range for a swing short
   - Rising market / regime turning up — shorts get killed in a bull market
   - Not a genuine former leader (weak prior_advance) — perennial dog, skip

──────────────────────────────────────────
STYLE
──────────────────────────────────────────
Terse, structured, decisive. Reference concrete price levels. No hedging.$prompt$
)
returning id, slug;

-- ── If the row already exists (inserted before description was added), run this
--    UPDATE instead of the INSERT above to backfill description + category:
--
-- update swingtrader.market_screenings
--    set category = 'technical-fundamental',
--        description = $desc$<paste the same $desc$ block from the INSERT above>$desc$
--  where slug = 'nis-short';
