# Flow-Inertia Momentum (FIM) — Strategy Specification

**Goal:** a strategy grounded in the flow-inertia literature (Vayanos-Woolley, Lou,
Gabaix-Koijen, square-root impact) that *predicts* momentum from flow persistence and
*quantifies* inertia per stock — using only non-proprietary data.

**Core hypothesis (falsifiable):** momentum returns concentrate in stocks where
(a) the driving flow is persistent (high inertia in the forcing function), and
(b) the flow is large relative to the stock's breakout liquidity threshold (forcing
exceeds the resistance implied by the impact law). Price momentum without flow support
should reverse; flow support without price movement yet should precede momentum.

---

## 0. Data — all public

| Data | Source | Frequency | Used for |
|---|---|---|---|
| OHLCV, adjusted | Yahoo/Stooq/Tiingo free tier | Daily | Returns, σ, ADV, Amihud |
| Shares outstanding | SEC XBRL company facts API (free) | Quarterly+ | Turnover, scaling |
| ETF daily holdings + shares outstanding | Issuer websites (iShares, Vanguard, SSGA publish daily CSV/XLS) | Daily | ETF flow → stock-level mechanical demand |
| Fund holdings | SEC EDGAR N-PORT (free, monthly holdings, quarterly public) | Quarterly | FIT reconstruction |
| Institutional holdings | SEC EDGAR 13F (free, 45-day lag) | Quarterly | Ownership breadth, flow persistence |
| Short interest | FINRA (free, bi-monthly) | Bi-monthly | Supply-side inertia |
| Index reconstitution announcements | S&P/FTSE Russell press releases | Event | Exogenous demand shocks |

ETF daily shares outstanding changes are the standard flow measure in the academic
literature (Ben-David et al. use daily SO changes as creations/redemptions), and the
"Ponzi Funds" paper's AIT construction — ETF flow × portfolio weight, aggregated over
ETFs per stock — is fully reproducible from issuer-published daily holdings files.
This is the highest-quality free flow signal available.

---

## 1. Two implementation tiers

### Tier 1 — Daily OHLCV only ("proxy tier")

**Flow proxy.** Without order-level data, use signed dollar volume:
```
f_t = sign(r_t) · DollarVolume_t                    (daily net flow proxy)
Φ_t = EMA_λ(f_t)                                    (smoothed forcing function)
```
This is the same signed-order-flow proxy used to estimate Kyle's λ from daily data.
It is crude — it attributes all of a day's volume to the direction of the day's return —
but it is the standard fallback and it inherits the right sign structure.

**Inertia coefficient (the prediction target).**
```
ρ_i = AR(1) coefficient of weekly Φ_t over trailing 26 weeks
```
ρ is the literal persistence of the forcing function: the Vayanos-Woolley condition
"momentum arises if flows exhibit inertia" made measurable. High ρ = high inertia.

**Half-life (the quantification of inertia).**
```
T_half,i = ln(2) / (−ln ρ_i)          [weeks]
```
This is the stock's flow-memory time — the Tier-1 stand-in for the latent-liquidity
memory time T_m. It also sets your holding period per stock (see §3).

**Breakout threshold (liquidity needed to break inertia).**
From the inverted square-root law with Y ≈ 0.75 (midpoint of the reported 0.5–1 range):
```
Q_break,i(k) = ADV_i · (k / Y)²        [dollars, to move price k·σ_daily]
```
For k = 1, Y = 0.75: Q_break ≈ 1.8 × ADV. Cross-check with the Amihud route:
```
Q_break_amihud,i(k) = k · σ_daily,i / ILLIQ_i
```
where ILLIQ = 21-day mean of |r_t|/DollarVolume_t. Keep both; their ratio is a data
quality diagnostic (they should agree within a factor of ~2–3 for liquid names).

**Forcing ratio (the trade signal).**
```
F_i = Σ_{t−20..t} f_t  /  Q_break,i(1)
```
Cumulative 1-month net flow relative to the volume needed for a 1σ move. F > 1 means
the observed flow was sufficient to break inertia; F ≫ 1 with modest realized price
movement means pressure is building faster than price is responding — the pre-momentum
state the theory predicts.

### Tier 2 — Add public filings ("mechanism tier")

**AIT (arbitrage-induced trading), daily, per stock.** For each ETF j holding stock i:
```
Flow_j,t   = (SO_j,t − SO_j,t−1) · NAV_j,t          (creation/redemption in $)
AIT_i,t    = Σ_j  w_ij,t · Flow_j,t  /  DollarVolume_i,t
```
using issuer-published daily holdings weights w_ij. This replaces the crude signed-volume
proxy with genuinely mechanical, direction-known flow. Recompute ρ, T_half and F on AIT.

**Quarterly E[FIT] (Lou).** From N-PORT holdings and TNA changes:
```
FIT_i,q = Σ_funds  shares_held_f,i,q−1 · flow_f,q · PSF  /  total shares held_i,q−1
```
with PSF (partial scaling factor) ≈ 1.0 for outflows and ≈ 0.62 for inflows, per Lou's
asymmetry estimate. Forecast next-quarter FIT from flow persistence (flows are highly
autocorrelated) → E[FIT]. This is the variable that, in Lou's data, subsumes price
momentum entirely.

---

## 2. Signal construction

Monthly rebalance. Universe: liquid equities (ADV > threshold, price > $5).

**Double sort:**
1. Sort into quintiles on **ρ** (flow persistence / inertia).
2. Within the top-ρ quintile, sort on **F** (forcing ratio).

**Long book:** high-ρ, high-positive-F stocks — persistent flow, strong enough to break
inertia, still in progress.
**Short book:** high-ρ, high-negative-F stocks — persistent outflows exceeding threshold.

**Explicit exclusions (from the theory, not ad hoc):**
- Exclude high-F, *low*-ρ stocks: a one-off flow burst without persistence predicts
  reversal, not momentum (temporary price pressure, Lou/Coval-Stafford).
- Exclude stocks where price has already moved > ~2× what F implies via the impact law:
  price has outrun its flow support; the surplus is the reversal-prone component.
  This is the strategy's built-in "late-stage momentum" detector, replacing the
  Lee-Swaminathan turnover heuristic with a mechanism-based one.

**Conditioning overlay (optional, Tier 1-compatible):** scale gross exposure down when
market-level realized vol rises sharply, because vol-targeting/CTA deleveraging makes
the aggregate forcing function flip sign quickly and synchronously — the environment
where flow persistence estimates break down.

---

## 3. Holding period and exit — set by the physics, not convention

- **Hold horizon per stock ≈ its own T_half.** The theory says the price drift lasts as
  long as the flow persists; a stock with a 3-week flow half-life should not be held on
  a 6-month momentum schedule.
- **Exit trigger:** F crossing zero (flow decelerated below breakeven) — *not* a price
  stop. In this framework, flow deceleration is the leading indicator of reversal;
  price weakness is the lagging one.
- **Reversal module (optional):** after F turns negative on a former long, the
  Vayanos-Woolley reversal phase predicts underperformance — a candidate short with the
  same machinery run in reverse.

---

## 4. What the strategy quantifies (deliverable metrics per stock)

| Metric | Meaning | Formula |
|---|---|---|
| ρ | Inertia of the forcing flow | AR(1) of Φ or AIT |
| T_half | Flow memory time | ln2 / −lnρ |
| Q_break(k) | Liquidity to break inertia by k·σ | ADV·(k/Y)² and k·σ/ILLIQ |
| F | Forcing vs threshold | Σflow / Q_break(1) |
| Slippage gap | Realized move minus flow-implied move | r_realized − Y·sign(F)·√|F|·σ |

The slippage gap is the most interesting diagnostic: persistently positive gaps mean
other (unobserved) flows are pushing the same way; persistently negative gaps mean
elastic capital is absorbing the flow — the stock has more "damping" than its ADV implies.

---

## 5. Falsification tests (run these before believing anything)

1. **Cross-sectional:** momentum profits (standard 12-1) should be increasing in ρ.
   If momentum is as strong in the low-ρ quintile, the inertia mechanism is not the driver.
2. **Timing:** returns after F > 1 events should be positive over ~T_half and fade after;
   returns after high-F/low-ρ events should reverse. Both must hold.
3. **Impact-law check:** regress |monthly return|/σ on √|F| — slope should be ≈ Y and
   stable across cap buckets. If the fit prefers log|F|, switch the threshold formula
   to the logarithmic form (the literature says this happens at the extremes).
4. **Placebo:** rebuild ρ from randomly re-signed volume. Signal must die.
5. **Tier consistency:** Tier-2 AIT-based ρ and Tier-1 proxy ρ should correlate. If not,
   the Tier-1 proxy is picking up something other than flow (likely volatility clustering)
   and Tier 1 alone should not be traded.

---

## 6. Known limitations — stated up front

- **The signed-volume proxy is the weak link in Tier 1.** It conflates flow with
  volatility. Tier 2's AIT fixes this for the ETF-held portion of demand only.
- **13F/N-PORT lags (45 days) mean quarterly FIT is a slow signal** — usable because
  flows are persistent (that's the whole thesis), but it forecasts quarters, not weeks.
- **The literature's own warning applies:** empirical support for flow-driven pricing is
  largely explanatory, over short samples; whether it is exploitable after costs is
  exactly what this backtest exists to determine, and the honest prior is uncertain.
- **Capacity:** the strategy's own orders sit on the same impact curve. Trading more than
  a small fraction of Q_break per name per day consumes the edge being harvested.
- **Y and the AR window are the two free parameters.** Fit them on a training period,
  freeze them, and report out-of-sample only. Two parameters is few enough to take
  seriously; ten would not be.

---

## 7. Build order

1. Tier 1 pipeline: OHLCV → Φ, ρ, T_half, ILLIQ, Q_break, F. Pure pandas, one afternoon.
2. Falsification tests 1–4 on 15+ years of US equities.
3. If test 1 and 2 pass: add the ETF daily-holdings scraper (iShares/Vanguard CSVs) → AIT.
4. Re-run with AIT; run test 5.
5. Only then: portfolio construction, costs, capacity analysis.

*Not investment advice; a research specification. Every parameter above is a reported
literature value, not a fitted one — treat all of them as priors to be re-estimated.*
