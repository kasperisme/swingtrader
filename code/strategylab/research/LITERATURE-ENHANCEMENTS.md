# Enhanced momentum — what the literature says, and what it did here

Three published improvements to momentum, implemented and tested on our universe
(800 most liquid US names, 2014-2023, after modelled costs). None of them
transferred as advertised, and the reasons are specific.

---

## What was implemented

**1. Risk-managed momentum — Barroso & Santa-Clara (2015), JFE.**
Scale exposure by the inverse of the strategy's own six-month realised
volatility, targeting a constant 12%. Reported: Sharpe **0.53 → 0.97**, excess
kurtosis 18.24 → 2.68, left skew −2.47 → −0.42. Extended by Daniel & Moskowitz
with a dynamic version scaling on forecast mean and variance.
→ `pf.vol_scaling`, `pf.vol_target_portfolio`, `pf.vol_lookback`, `pf.vol_scale_cap`

**2. Frog-in-the-Pan — Da, Gurun & Warachka (2014), RFS.**
Information arriving continuously in small increments attracts less attention
than the same cumulative move delivered in jumps, so it is underreacted to and
its momentum persists. Reported: six-month momentum of **8.86%** for continuous
formation periods versus **2.91%** for discrete ones at the same cumulative
return. Measure: `ID = sign(PRET) × (%down days − %up days)`.
→ `rank.w_continuity`, `gates.max_info_discreteness`

**3. Idiosyncratic momentum — Blitz, Huij & Martens (2011).**
Rank on the residual of a rolling market regression, scaled by residual
volatility, rather than on raw past return. Strips the market component that
makes momentum crash when the market reverses.
→ `rank.w_residual_momo`

---

## What happened

| variant | reward | Sharpe | CAGR | max DD | trades | skew | kurt | alpha t |
|---|---|---|---|---|---|---|---|---|
| incumbent (long only) | −0.549 | **0.086** | 2.2% | 22.5% | 570 | −0.43 | 4.5 | −0.31 |
| + vol scaling | −0.705 | −0.001 | 1.2% | 23.8% | 1219 | −0.42 | 4.5 | −0.59 |
| + FIP continuity rank | −0.459 | −0.005 | 1.0% | 21.7% | 567 | −0.36 | 4.1 | −0.63 |
| + residual momentum | −0.442 | 0.098 | 2.4% | 22.3% | 582 | −0.39 | 4.5 | −0.27 |
| + FIP gate (continuous only) | −0.657 | 0.041 | 1.6% | 24.7% | 570 | −0.39 | 4.6 | −0.46 |
| all three | −0.509 | 0.073 | 2.1% | **18.2%** | 1043 | −0.37 | 4.1 | −0.34 |

At the incumbent's ~27-day holding period, only residual momentum improved
anything, and marginally. **That holding period turned out to be the problem** —
see below.

---

## Why volatility scaling did not transfer

This is the interesting one, because it is the best-supported result in the
literature and it went the wrong way here.

**The crash it protects against is not in this strategy.** Barroso &
Santa-Clara's gain comes almost entirely from avoiding momentum crashes — the
2009-style rebound in which a long-short momentum book loses 30% in a month.
Their unmanaged strategy has excess kurtosis of **18.2** and skew of **−2.5**.
Ours has kurtosis **4.5** and skew **−0.43**: a long-only book with a regime
filter has already given up most of that tail, so there is far less to cut. The
overlay ends up trading against noise rather than against crash risk.

**Their rebalance is free; ours is not.** They resize a monthly-rebalanced
factor portfolio. An entry-and-hold engine with stops has to *transact* to change
exposure, and every adjustment pays the spread.

That second point produced a genuinely instructive sequence:

| implementation | Sharpe | trades |
|---|---|---|
| scale new entries only (wrong, but cheap) | **0.061** | 609 |
| close positions to shed risk (churns) | **−0.088** | 1169 |
| **trim positions proportionally (correct)** | **−0.001** | 1219 |

The first version *looked* best in combination — "all three" scored Sharpe 0.187
— purely because the scaling was barely being applied. Implementing the
mechanism properly removed that flattering artefact. A cheap approximation of a
risk overlay that mostly does nothing will outperform a correct one whenever the
overlay itself is not helping.

A `vol_trim` is now booked as its own transaction, and `n_trades` excludes trims
while costs and turnover include them — otherwise a risk overlay reads as a
change in trading frequency.

---

## The one that does transfer — FIP, at the right holding horizon

The first FIP test used the incumbent's ~27-day average hold. Da/Gurun/Warachka
measure over **six months**, and continuous-information momentum is a *slower*
effect by construction: the whole hypothesis is that the market underreacts to
information that dribbles out, so the correction takes longer.

Re-run with a 130-day maximum hold, and with the control that decides whether
FIP is doing anything at all:

| variant | reward | Sharpe | CAGR | max DD | avg hold | alpha t |
|---|---|---|---|---|---|---|
| A incumbent (60d hold) | −0.549 | 0.086 | 2.2% | 22.5% | 27d | −0.31 |
| **B incumbent + 130d hold — CONTROL** | −0.829 | **0.045** | 1.6% | 31.2% | 38d | −0.55 |
| C FIP **gate** + 130d hold | −1.384 | −0.140 | −1.1% | 34.1% | 37d | −1.19 |
| **D FIP *rank* + 130d hold** | **−0.472** | **0.215** | **4.1%** | 23.8% | 36d | **+0.09** |
| E FIP gate + rank + 130d | −0.489 | 0.210 | 4.1% | 25.1% | 36d | +0.07 |
| F residual momentum + 130d | −0.689 | 0.137 | 3.0% | 25.4% | 36d | −0.19 |
| G residual + FIP + 130d | −0.795 | 0.124 | 2.8% | 27.6% | 37d | −0.23 |

**The control (B) is the finding.** Lengthening the hold on its own makes things
*worse* — Sharpe 0.086 → 0.045, drawdown 22.5% → 31.2%. So the gain in D is not
"longer holds help"; it is FIP needing room to express. Sharpe **0.086 → 0.215**,
alpha t-stat crosses from −0.31 to positive, and drawdown barely moves.

Note C: as a **gate**, FIP is destructive (−0.140) — it removes candidates
without improving the ordering of the ones that remain. As a **ranking weight**
it works. That distinction matters and it is the opposite of how a screen-builder
would naturally reach for it.

## Why FIP did not transfer at short holds

The measure works — the synthetic test confirms a smooth path scores as more
continuous than a jumpy one with identical cumulative return — but as a *ranking
weight* it displaced relative strength, and as a *gate* it cut the candidate pool
without improving selection. Da/Gurun/Warachka sort on FIP **within** momentum
deciles over six-month holds; this strategy holds for weeks and already filters
hard on trend, so the two are competing for the same information rather than
compounding.

Testing it as a conditioning variable *within* the existing rank, over longer
holds, is the version that works — see the section above.

---

## Statistical health warning on the above

Thirteen variants have now been evaluated across two ablations, and D was chosen
after seeing the results. That is exactly the selection process the deflated
Sharpe exists to discount, and none of these numbers has been through the
acceptance gate. The reward for D is still **negative** (−0.472), it is still far
below the 1.00 Sharpe gate, and still below SPY buy-and-hold at 0.738.

What makes D worth taking seriously is not its Sharpe but its **control**: the
mechanism predicts the effect needs a longer horizon, the longer horizon alone
makes things worse, and the combination works. A confound was available and was
ruled out. It still has to survive the search, the trial-count deflation and the
vault before it means anything.

## What this does not say

It does not say these results are wrong. Every one of them is out-of-sample here
in the strongest sense — different universe, different period, different holding
horizon, different portfolio construction, and a long-only book rather than the
long-short factor the papers study. The honest reading is that **a published
factor result does not automatically survive being re-housed in a different
strategy**, and that the transfer failure is informative about which mechanism
was actually doing the work.

Reproduce: `python /tmp/ablate.py` (or the `ablation` variants in
`tests/test_short_sleeve.py` for the mechanics).

## Sources

- Barroso & Santa-Clara, "Momentum has its moments", JFE 116(1) 2015 — https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002566
- Da, Gurun & Warachka, "Frog in the Pan: Continuous Information and Momentum", RFS 27(7) 2014 — https://academic.oup.com/rfs/article-abstract/27/7/2171/1578455
- Hanauer & Windmüller, "Enhanced momentum strategies", JBF 2022 — https://www.sciencedirect.com/science/article/abs/pii/S0378426622002928
- Blitz, Huij & Martens, "Residual Momentum" — https://www.researchgate.net/publication/227415042_Residual_Momentum
- Alpha Architect summaries — https://alphaarchitect.com/risk-of-momentum-crashes/ · https://alphaarchitect.com/frog-in-the-pan-identifying-the-highest-quality-momentum-stocks/
