# FIM Strategy — Implementation on Financial Modeling Prep (Premium)

Maps every variable in the Flow-Inertia Momentum spec to a concrete FMP endpoint.
Base URL: `https://financialmodelingprep.com` — append `?apikey=KEY`.
FMP has two doc generations: **stable** (`/stable/...`) and **legacy v3/v4**
(`/api/v3/...`). Both work on premium; endpoint names below use the ones documented.
Verify each response shape once in the API Viewer (playground) before wiring the
pipeline — FMP occasionally renames fields between generations.

---

## 1. Endpoint → variable mapping

### Tier 1 — daily pipeline (all from FMP, no other source needed)

| Strategy variable | FMP endpoint | Call pattern |
|---|---|---|
| OHLCV, adjusted | `/api/v3/historical-price-full/{symbol}` (Daily Chart EOD) | Per symbol, full history |
| Whole-universe daily bar | `/api/v4/batch-request-end-of-day-prices?date=YYYY-MM-DD` (Batch EOD) | **One call per day for ALL symbols** — use this for the backtest build, not per-symbol loops |
| Universe definition | `/api/v3/stock-screener` (filter: exchange, marketCap, volume, price>5, isEtf=false) | Monthly refresh |
| Shares outstanding | `/api/v4/shares_float?symbol=X` + `/api/v4/historical/shares_float?symbol=X` | Quarterly; for turnover = Volume/SO |
| SO daily proxy | `/api/v3/historical-market-capitalization/{symbol}` → SO_t = mktCap_t / close_t | Daily; validates the float series |
| σ_daily, ADV, ILLIQ | computed from OHLCV | — |
| Realized-vol overlay | `/api/v3/technical_indicator/1day/{symbol}?type=standardDeviation` (or compute) | — |

From these alone you get: f_t (signed dollar volume), Φ_t, ρ, T_half, ILLIQ,
Q_break, F — the complete Tier-1 signal set.

### Tier 2 — flow mechanism (this is where premium FMP earns its fee)

| Strategy variable | FMP endpoint | Notes |
|---|---|---|
| ETF → stock positions | `/api/v3/etf-holder/{ETF}` (current) and historical ETF holdings via `/api/v4/etf-holdings?symbol=ETF&date=...` with `/api/v4/etf-holdings/portfolio-date?symbol=ETF` for available dates | N-PORT-derived; monthly/quarterly snapshots, NOT daily |
| Reverse map: which ETFs hold stock i | `/api/v3/etf-stock-exposure/{symbol}` | Gives per-ETF weight & shares in one call per stock — this is the w_ij matrix without looping over ETFs |
| All ETF holders in bulk | Bulk ETF Holders endpoint | One pull for the whole cross-section |
| Quarterly institutional flow per stock | `/api/v4/institutional-ownership/symbol-ownership?symbol=X&includeCurrentQuarter=true` (Institutional Stock Ownership) | Returns investorsHolding, ownershipPercent, totalInvested and their QoQ changes — **ownership breadth change and net institutional demand pre-aggregated**. This replaces hand-rolling FIT from raw 13Fs for a first pass |
| Fund-level holdings (full FIT) | Form 13F: `/api/v3/form-thirteen/{cik}?date=...` + `/api/v3/cik_list` + Form 13F dates | Only needed if the pre-aggregated series proves too coarse |
| Mutual fund holdings | Mutual Funds historical holdings endpoints (N-PORT) | For the Lou-style FIT with the 0.62/1.0 inflow/outflow asymmetry |
| Index reconstitution events | `/api/v3/historical/sp500_constituent` (+ Nasdaq, Dow variants) | Exogenous demand shocks for elasticity calibration |
| Supply friction | Fail-to-deliver endpoint, short-interest via FINRA still | FTD spikes = borrow-side inertia |

---

## 2. The one real gap — and the workaround

**FMP does not provide daily ETF creations/redemptions.** Its ETF holdings are
N-PORT snapshots (monthly at best). The spec's daily AIT flow therefore cannot be
built from FMP holdings alone.

**Workaround A (test first):** daily ETF shares outstanding implied from FMP:
```
SO_etf,t = historical-market-capitalization(ETF).mktCap_t / close_t
Flow_etf,t = (SO_etf,t − SO_etf,t−1) · NAV_t
```
Whether this works depends on whether FMP updates ETF market cap with actual daily
SO or just price-scales a stale SO. **Validation:** compute SO_t for SPY over a month;
if it's constant while price moves, it's stale → workaround fails. If it steps on
creation/redemption days, you have daily flow from FMP alone.

**Workaround B (robust):** keep issuer daily-holdings CSVs (iShares/Vanguard) for the
top ~50 ETFs by AUM only — they carry the bulk of mechanical flow — and use FMP for
everything else. Small scraper, big coverage.

**Workaround C (accept monthly):** run AIT at monthly frequency from FMP's ETF
holding-date snapshots: ΔShares_ij between snapshots × price = flow. Coarser, but
consistent with a monthly-rebalance strategy, and zero extra infrastructure.

Recommendation: A as a one-hour test; C as the default; B only if tests show daily
flow materially improves ρ estimation.

---

## 3. Pipeline sketch (build order)

```python
import requests, pandas as pd, numpy as np
BASE = "https://financialmodelingprep.com"
KEY  = "..."

# ── Step 1: universe (monthly) ─────────────────────────────
scr = requests.get(f"{BASE}/api/v3/stock-screener",
    params=dict(exchange="NYSE,NASDAQ", isEtf="false", isActivelyTrading="true",
                priceMoreThan=5, volumeMoreThan=500_000, limit=5000,
                apikey=KEY)).json()
universe = [s["symbol"] for s in scr]

# ── Step 2: prices — batch EOD, one call per trading day ──
# loop dates, cache to parquet; ~15y × 252d = ~3800 calls total, well within limits
def eod(date):
    return requests.get(f"{BASE}/api/v4/batch-request-end-of-day-prices",
        params=dict(date=date, apikey=KEY)).json()

# ── Step 3: Tier-1 signals per stock ──────────────────────
# f_t   = sign(ret) * close * volume
# Phi_t = f.ewm(halflife=10).mean()
# rho   = AR(1) on weekly Phi (26w window)     -> inertia
# T_half= np.log(2)/-np.log(rho)               -> memory time
# ILLIQ = (ret.abs()/dollar_vol).rolling(21).mean()
# Qbrk  = ADV * (1/0.75)**2          # k=1, Y=0.75
# F     = f.rolling(20).sum() / Qbrk

# ── Step 4: Tier-2 quarterly institutional flow ───────────
inst = requests.get(f"{BASE}/api/v4/institutional-ownership/symbol-ownership",
    params=dict(symbol="AAPL", includeCurrentQuarter="false", apikey=KEY)).json()
# fields incl. investorsHolding + change, totalInvested + change
# breadth_flow = change_investorsHolding / investorsHolding   (persistence -> rho_q)

# ── Step 5: ETF weight matrix (monthly) ───────────────────
exp = requests.get(f"{BASE}/api/v3/etf-stock-exposure/AAPL",
    params=dict(apikey=KEY)).json()   # -> [{etfSymbol, weightPercentage, sharesNumber}...]
# AIT_i = sum_j w_ij * ETF_flow_j / dollar_volume_i   (flow per workaround A or C)
```

Rate-limit notes (premium): batch and bulk endpoints exist precisely so you don't
loop; use Batch EOD for prices and Bulk ETF Holders for the weight matrix. Cache
everything locally — the backtest should hit FMP once per dataset, not per run.

---

## 4. FMP-specific upgrades to the original spec

1. **Ownership breadth flow (new, FMP-native).** The symbol-ownership endpoint's
   `investorsHolding` change is a direct breadth measure — Chen-Hong-Stein-style
   breadth changes are themselves a documented return predictor and a clean quarterly
   flow proxy. Fit ρ_q on this series as the Tier-2 inertia estimate; it requires
   one call per stock per quarter, no 13F parsing.
2. **Elasticity calibration from reconstitutions.** Historical S&P 500 constituents
   + Batch EOD around event dates → your own per-cap-bucket price multiplier,
   replacing the literature's wide 0.3–15 range with a self-estimated Y and
   elasticity for your universe. This is the piece the free plan made painful.
3. **DCF/screener overlay.** Since FMP ships valuation endpoints, the earlier idea
   of screening for below-fair-value names and entering on the flow trigger drops in
   naturally: screener + DCF as the *candidate filter*, F > 1 with high ρ as the
   *entry condition*. Value tells you the spring is loaded; flow tells you it fired.

---

## 5. Validation checklist before trusting FMP data

- [ ] SPY implied SO test (workaround A viability)
- [ ] Cross-check FMP shares_float vs SEC XBRL for 20 random names
- [ ] Check institutional-ownership changes against two known 13F events
- [ ] Confirm etf-stock-exposure weights sum ≈ ETF's actual weight for 5 stocks
- [ ] Survivorship: confirm delisted names appear in historical batch EOD
      (FMP has a delisted-companies endpoint — join it into the universe)

The survivorship item is the one that silently destroys momentum backtests;
FMP's delisted list makes it checkable, so check it.
