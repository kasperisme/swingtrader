# Price Inertia, Momentum, and Money Flow — Literature Map & Quantification Brief

**Prepared as a handoff brief.** Purpose: give a downstream model the state of the
literature on flow-driven momentum, with specific attention to (a) how inertia is
quantified, (b) how much liquidity is required to break price inertia, and (c) what
volume-based observables carry the signal.

**Framing to preserve:** momentum is treated here as the *output* of a system whose
state variable is accumulated and anticipated flow, not price. Inertia is the property
that makes the flow → price mapping slow and path-dependent. This is deliberately an
engineering/control-systems framing: mass (inelasticity), forcing function (flow),
damping (arbitrage capacity), memory kernel (impact decay), and a breakout threshold
(liquidity required to move price).

---

## 1. Literature map — six clusters

### Cluster A — Flow inertia as the direct cause of momentum
The cluster that literally uses the inertia framing.

- **Vayanos & Woolley (2013), "An Institutional Theory of Momentum and Reversal", RFS 26(5).**
  Momentum arises *if flows exhibit inertia*, and because rational prices underreact to
  *expected future* flows. Reversal arises because flows push prices past fundamental
  value. Mechanism: a fundamental shock hits assets → funds holding them underperform →
  investors update on manager ability → gradual outflows → gradual further price decline.
  Also generates comovement, lead-lag effects, and amplification, all stronger for assets
  with high idiosyncratic risk.
- **Lou (2012), "A Flow-Based Explanation for Return Predictability", RFS 25(12).**
  The empirical workhorse. Constructs stock-level demand shocks by projecting mutual fund
  flows onto holdings (the FIT measure). Key result: once you control for expected
  flow-induced trading E[FIT], stock price momentum is no longer statistically
  significant. Also finds asymmetry — managers liquidate roughly dollar-for-dollar to meet
  redemptions but deploy only ~62 cents per dollar of inflow.
- **Huebner (dissertation, and with Haddad & Loualiche).** Distinguishes persistent demand
  shocks (underreaction) from the *term structure of demand elasticities*. Investors
  respond more to short-term than long-term price changes — the term structure slopes
  downward — and this is identified as the primary driver of momentum returns. Stocks with
  more investors having downward-sloping elasticity term structures show ~7%/yr stronger
  momentum.

### Cluster B — Inelasticity (the "mass" term)
- **Gabaix & Koijen, "The Inelastic Markets Hypothesis".** Aggregate: $1 of flow moves
  aggregate market value ~$5 (multiplier M ≈ 5, range 3–8 across specifications);
  implied macro elasticity ≈ −0.2 versus the −10 to −20 that frictionless models imply.
  Cause: marginal holders (index funds, pensions, insurers) operate under mandates fixing
  equity allocation in narrow bands. Programmatic claim: replace latent "dark matter" in
  asset pricing with observable flows by identifiable investors.
- **Haddad, Huebner & Loualiche (AER, March 2025), "How Competitive is the Stock Market?"**
  Strategic response is incomplete: when some investors trade less aggressively, others
  compensate, but only by about two-thirds. Consequence: the 20-year rise of passive has
  made demand for individual stocks ~11% *more* inelastic.
- **Davis, Kargar & Li, "Why is Asset Demand Inelastic?"** Surveys micro price multipliers
  (inverse micro elasticities) spanning ~0.3 to ~15 — far more inelastic than theory
  predicts — and microfounds this via investor beliefs about discount rates and cash flows.
- **Elasticity estimate spread (important for calibration honesty):** Lou (2012) stock-level
  multiplier ≈ 1.2; Pavlova & Sikorskaya ≈ 0.3–0.5; Gabaix & Koijen much larger at the
  aggregate level. A 2026 transaction-based EM study finds median stock elasticity −0.34,
  implying a 1% increase in demand relative to shares outstanding raises price ~2.9%.
  Micro > macro elasticity is expected: stocks substitute for each other more easily than
  equities substitute for bonds.

### Cluster C — Microstructure: the impact function and its memory
- **Square-root law of market impact (Bouchaud and collaborators).** For a metaorder of
  total size Q, average impact scales with sqrt(Q), approximately independent of the number
  of child orders and of execution duration, provided participation rate is moderate.
  Empirical impact exponent δ measured very close to 0.5 over ~4 decades of size.
- **Two-square-root refinement (arXiv:2311.18283).** Separates volume from participation
  rate γ: at fixed γ, impact grows as sqrt of cumulated volume; at fixed executed volume,
  peak impact scales as sqrt(γ) for large enough γ.
- **Regime crossover.** For small metaorders and low participation, impact reverts to the
  linear Kyle regime; universal crossover functions in participation rate describe the
  transition. This matters: the "inertia to break" is a *different functional form* at
  small vs large size.
- **Deviations (Zarinelli et al., "Beyond the Square Root").** Conditioning on market cap,
  participation rate, and duration reveals consistent deviations at both large and small
  Q/V_D; a logarithmic (more concave) form fits better. Decomposition: π = Q/V_D = F · η,
  where F is fractional volume duration and η is participation rate. The square-root law
  implicitly assumes impact depends only on the product.
- **Propagator / decay models.** Impact decays as a shifted power law; empirical metaorder
  decay reproduced with exponent β ≈ 0.2. Recent nonparametric multi-asset propagator
  estimators find self-impact concave, and concave cross-impact specifications outperform
  linear ones — the square-root law appears to extend to cross-impact.
- **Bouchaud, "The Inelastic Market Hypothesis: A Microstructural Interpretation"
  (arXiv:2108.00242).** Bridges Cluster B and C. Latent Liquidity Theory: the mechanism
  behind inelasticity is that private value estimates realign around the market price over
  a finite memory time, T_m. **T_m is the most literal inertia time-constant in the
  literature and should be treated as the primary target parameter.**

### Cluster D — Explicit memory-variable dynamics
- **Halperin & Itkin, "Marketron" (arXiv:2508.09863, and 2025 follow-up).** Price formation
  in an inelastic market driven by money flows plus their impact. Impact function captures
  both inelasticity and saturation from new money ("dumb money" effect). Because investor
  flows depend on market performance, there is a feedback loop → nonlinear dynamics.
  Formally: nonlinear diffusion of a quasiparticle in a 2D space of log-price x and a
  memory variable y that retains past money flows. Non-Markovian in x alone, Markovian in
  (x, y). Authors note the analogy to spiking-neuron models.
  **This is the closest thing to a state-space formulation of price inertia and is the
  most directly useful structure for a systematic implementation.**

### Cluster E — Structural / mechanical flows
- **Jiang, Vayanos & Zheng (2025), "Passive Investing and the Rise of Mega-Firms."**
  Cap-weighted passive inflows mechanically overweight the largest recent winners,
  amplifying momentum at the top of the cap distribution and raising large-cap volatility.
- **Chinco & Sammon.** Estimate the share of US market tracking major indices at ~33.5%
  (2021) using reconstitution-day identification; note true passive footprint is higher
  (possibly understated by nearly half) because large asset owners index internally.
- **Index-inclusion event studies** (Shleifer 1986; Harris & Gurel 1986; Chang, Hong &
  Liskovich; Pavlova & Sikorskaya; Greenwood & Sammon) — the canonical exogenous demand
  shocks used to identify micro elasticity.
- **Practitioner mechanical flows.** Vol-targeting and vol-control programs, CTA trend
  followers, risk parity, and dealer gamma hedging. These are the highest-frequency,
  most *predictable* component of the forcing function. Documented stress dynamic: CTA,
  vol-control and risk-parity deleveraging synchronise; top-of-book futures depth collapses
  (one episode: ~$10m → ~$4m); ETFs reached ~41% of total equity volume; dealer gamma
  turned negative, forcing selling into declines.

### Cluster F — Volume as the conditioning variable
- **Lee & Swaminathan (2000), "Price Momentum and Trading Volume", JF 55.**
  Momentum is a function of both past price and past turnover. Buying high-volume winners
  and shorting high-volume losers beats price-momentum-alone by 2–7%/yr at intermediate
  horizons. High-volume winners and low-volume losers reverse faster. Momentum Life Cycle
  (MLC) hypothesis: turnover proxies for investor favouritism vs neglect.
- **Critique — Chen, Chou et al., "Momentum life cycle, revisited" (JBF 2021).**
  MLC is largely the mechanical product of two separate documented effects (momentum and a
  turnover effect). After controlling for both, what remains is a negative pattern for
  late-stage momentum, driven mostly by low-turnover losers — and that survives only in
  optimistic periods, supporting a divergence-of-opinion reading of turnover.
  **Treat MLC as a conditioning heuristic, not a mechanism.**
- **Order Flow Imbalance (Cont, Cucuringu & Zhang, Quantitative Finance 2023).**
  Multi-level OFI (integrating several book levels) explains contemporaneous impact better
  than best-level OFI. Once multi-level OFI is used, contemporaneous cross-impact adds
  nothing; but *lagged* cross-asset OFIs do improve return forecasting, concentrated at
  short horizons and decaying rapidly.

---

## 2. Quantifying inertia — candidate estimators

Ordered from most tractable to most demanding.

**I1. Flow autocorrelation (the literal inertia coefficient).**
Fit an AR(p) to stock-level flow-induced trading. The persistence parameter *is* the
inertia constant in the Vayanos-Woolley sense. Momentum should be strongest where flow
persistence is highest. This is the single most direct test of the user's framing and is
computable from quarterly 13F/N-PORT holdings plus fund flow data.

**I2. Expected flow-induced trading, E[FIT] (Lou 2012).**
FIT = flow-driven trading by the aggregate fund industry in a stock, scaled by shares held.
Constructed with no price data, which is what makes it a clean instrument. Note the
Qin (2024) decomposition into mechanical (MFIT) vs discretionary (DFIT) components:
MFIT carries the momentum/reversal effect, and only in low-DFIT stocks.

**I3. Term structure of demand elasticities (Huebner).**
Estimate elasticity at multiple horizons per investor; the slope is the inertia measure.
Downward slope = slow adjustment = momentum. Requires 13F panel and a demand-system
estimation (Koijen-Yogo style, ideally with nested industry/stock substitution).

**I4. Impact memory time T_m (latent liquidity).**
Estimate the decay kernel G(t) of metaorder impact. Empirical decay: shifted power law,
β ≈ 0.2. T_m is the horizon over which private valuations realign to market price. In
control terms this is the system's relaxation time.

**I5. Marketron memory variable y.**
If implementing a state-space model: y = exponentially-weighted accumulation of past net
flow, with the decay rate as a fitted parameter. Price dynamics then modelled as nonlinear
diffusion in (x, y). Highest fidelity, highest implementation cost.

**I6. Proxies available without holdings data.**
ETF creation/redemption net share changes weighted by portfolio weight (the AIT analogue
of FIT); short interest change; institutional ownership breadth change; index-membership
weight drift.

---

## 3. Quantifying the liquidity required to break price inertia

Three independent routes to the same question. They should be cross-checked against each
other, because they disagree by an order of magnitude in places.

**Route 1 — Invert the square-root law (execution view).**
ΔP / σ_daily ≈ Y · sqrt(Q / V_daily), with Y typically ~0.5–1 (one large study reports
Y ≈ 0.9). Inverting: **Q_required ≈ V_daily · (ΔP / (Y · σ_daily))²**.

Worked shape: to move a stock 1σ requires roughly Q ≈ V_daily / Y² — i.e. of the order of
one full day's volume. To move it 2σ requires ~4× that. The quadratic is the key
engineering insight: *breaking inertia is superlinear in the move you want.*

Caveats to carry: use the log-form correction at very large and very small Q/V_D; decompose
π = F · η rather than assuming only the product matters; at low participation the linear
Kyle regime applies instead.

**Route 2 — Kyle's λ / Amihud (statistical view).**
- Kyle λ, firm-month: regress ΔP_τ on signed order flow OF_τ = Volume_τ · sign(ΔP_τ) within
  the month; the slope is λ. Then **Q_required = ΔP / λ**. Linear, so it will understate
  the cost of large moves relative to Route 1 — that discrepancy is diagnostic, not noise.
- Amihud ILLIQ = mean over days of |r_τ| / DollarVolume_τ. Requires only daily data,
  correlates well with λ and with effective spreads (Hasbrouck). Noisy daily; average over
  a month or more. Realized (intraday-sampled) Amihud is materially more accurate than
  daily Amihud if intraday data is available.

**Route 3 — Elasticity / multiplier (economic view).**
Given micro elasticity ε for the stock, a demand shift of ΔQ/Q_shares_outstanding produces
ΔP/P ≈ −(1/ε) · (ΔQ/Q). With median ε ≈ −0.34, 1% of shares outstanding ≈ 2.9% price move.
With multipliers spanning 0.3–15 across the literature, this route is a *range* estimate,
not a point estimate — its value is bounding the other two.

**Route 4 — Mechanical hedging thresholds (regime view).**
GEX/dealer gamma gives a conditional map of mechanical hedging obligation per unit price
move. Positive dealer gamma → counter-cyclical rebalancing (dampening, raises the liquidity
needed to break inertia). Negative dealer gamma → pro-cyclical (amplifying, lowers it).
Gamma flip level = where the sign of the damping term changes. Caveat that must survive the
handoff: GEX is a modelled quantity, dealer positioning is not observable, and every public
figure depends on sign and inventory assumptions. Use as a regime filter, not a trigger.

**Practical synthesis.** Define a *breakout liquidity threshold* per stock as the volume
required, at prevailing σ and depth, to produce a move exceeding some multiple of daily σ,
then compare it to the plausible size of the identified flow (fund flows, index demand,
ETF creations). Inertia is "breakable" when forcing ≳ threshold. This turns the whole
question into a ratio, which is the form worth backtesting.

---

## 4. Volume-based observables worth carrying

| Observable | What it proxies | Data need |
|---|---|---|
| Turnover (volume / shares out) | Investor attention, divergence of opinion | Daily, free |
| Dollar volume, ADV | Denominator for all impact laws | Daily, free |
| Amihud ILLIQ | Price impact per dollar | Daily, free |
| Realized Amihud | Same, far lower RMSE | Intraday |
| Kyle λ | Depth / adverse selection | Intraday or signed daily proxy |
| Multi-level OFI | Contemporaneous impact; lagged cross-asset OFI forecasts returns short-horizon | LOB data |
| Participation rate η, fractional duration F | Position on the impact surface | Execution data |
| ETF volume share | Mechanical flow intensity | Vendor |
| FIT / E[FIT] | Flow-induced demand shock | 13F / N-PORT + fund flows |
| Passive weight drift | Index-driven mechanical demand | Index files |
| GEX / gamma flip | Sign of the damping term | Options chain |

---

## 5. Where the literature genuinely disagrees

State these explicitly rather than resolving them.

1. **Magnitude of micro elasticity.** Estimates span roughly 0.3 to 15 in multiplier terms.
   Identification strategy drives the answer. Any single calibration is a choice.
2. **Functional form of impact.** Square-root vs logarithmic. The log form fits the extremes
   better; square root is more tractable and near-universal in the mid-range.
3. **Does flow *explain* momentum or merely *accompany* it?** Lou says E[FIT] subsumes
   momentum; Huebner attributes it to elasticity term structure; Hong & Stein-style
   underreaction remains live. Recent demand-system decompositions (JFE 2026) benchmark
   these channels on a common scale rather than declaring a winner.
4. **Whether MLC is a mechanism or an artefact.** See Cluster F critique.
5. **Predictive vs explanatory.** The inelastic-markets programme is largely explanatory,
   over short samples in economic-cycle terms, and the original work does not address
   whether the effect is tradeable. This is the most important caveat for any strategy use.
6. **Passive concentration effects** are contested in direction and magnitude, and interact
   with the volatility regime (low-vol/high-dispersion regimes complicate the usual
   small-vs-large-cap relationship).

---

## 6. Suggested tasks for the downstream model

1. Formalise the inertia/momentum system in state-space form, with explicit mass, forcing,
   damping and memory terms, mapping each to a named estimator from §2.
2. Derive a single per-stock "inertia breaking threshold" metric that reconciles Routes 1–3
   in §3, and state where the three disagree and by how much.
3. Specify a data pipeline: which fields, which vendors, which frequency, and which
   estimators degrade gracefully when only daily OHLCV is available.
4. Design the falsification test: if flow inertia drives momentum, momentum should be
   strongest in high-flow-persistence, low-elasticity, high-impact-coefficient names, and
   should decay with the estimated memory time T_m. Specify the cross-sectional sort.
5. Address the capacity question honestly: if the strategy's own metaorders sit on the same
   impact curve, at what AUM does the edge self-extinguish?

---

## 7. Primary reading list (ordered by relevance to the inertia question)

1. Vayanos & Woolley (2013), RFS — flow inertia → momentum, the core framing
2. Lou (2012), RFS — FIT construction, the empirical workhorse
3. Bouchaud et al. (arXiv:2108.00242) — inelasticity ↔ microstructure bridge, memory time
4. Gabaix & Koijen — inelastic markets hypothesis, the multiplier
5. Halperin & Itkin (arXiv:2508.09863) — marketron, explicit memory-variable dynamics
6. Haddad, Huebner & Loualiche (AER 2025) — strategic response, passive inelasticity
7. Huebner — term structure of elasticities as momentum driver
8. Zarinelli et al. (arXiv:1412.2152) — impact surface, limits of the square-root law
9. Lee & Swaminathan (2000), JF — volume conditioning
10. Cont, Cucuringu & Zhang (QF 2023) — OFI, cross-impact, forecasting
11. Jiang, Vayanos & Zheng (2025) — passive flows and mega-firms
12. Davis, Kargar & Li — why demand is inelastic, microfoundation

---

*Compiled from a literature scan. Figures are as reported in the cited sources; several
are contested (see §5). Nothing here is a trading recommendation or a calibrated model.*
