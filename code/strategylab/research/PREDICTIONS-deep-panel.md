# Pre-registered predictions — deep panel (1995-2026)

Written **before** the extended data finished syncing, and before any of it was
evaluated. Recorded so the results can falsify something rather than be
narrated afterwards.

## The design problem, and how the windows are set

~250 configurations have already been searched on **2014-2023**. That period is
burned; nothing measured on it is out-of-sample any more. The sealed vault
(2024-2026) is still clean but is only ~2.5 years — too short to judge a
strategy on.

The extension creates a genuinely unseen period that is *large* and contains two
systemic crises:

| window | status | contains |
|---|---|---|
| 1998-2013 | **HOLDOUT — never searched** | dot-com crash, GFC, 2009 momentum crash |
| 2014-2023 | contaminated (250 configs) | no systemic event |
| 2024-2026 | vault, still sealed | — |

Testing the 2014-2023 winner on 1998-2013 is a true out-of-sample test. It is
not "future" data, but it is unseen data, which is what out-of-sample means
statistically. The vault stays shut.

## Predictions

**P1 — Volatility scaling will finally work on WML.**
Confidence: high. Barroso & Santa-Clara's entire result comes from avoiding the
2009 momentum crash, which was absent from 2014-2023. On 1998-2013 I expect
unmanaged WML to show excess kurtosis **> 10** and a worst month **< -20%**, and
scaling to cut both by at least half. If scaling does NOT help on a window
containing 2009, my implementation is wrong rather than the paper.

**P2 — The best genome will degrade materially on the holdout.**
Confidence: high. It was selected from 250 configurations on a crisis-free
decade; a long-only momentum book with a regime filter has never been tested
against a −50% market. I expect Sharpe **below 0.35** (versus 0.512 in-sample)
and max drawdown **worse than 25%** (versus 18.5%). A result close to in-sample
would be surprising and would need explaining, not celebrating.

**P3 — The Minervini pre-filter will help more on the holdout than it did in
sample.** Confidence: medium. Its mechanism is standing aside when nothing
qualifies, and 2014-2023 gave it almost nothing to stand aside from. This is the
prediction most likely to be wrong, and the pre-filter's in-sample gain already
failed to replicate across genomes (p = 0.53).

**P4 — TSMOM will correlate below 0.3 with the equity book.**
Confidence: medium-high. Different mechanism, different universe, can be net
short. If it comes back above 0.5, it is not a diversifier and the √N route
stays closed.

**P5 — Momentum decay will be visible.**
Confidence: medium. Comparing 1998-2010 against 2011-2023 I expect the earlier
period to show a materially higher Sharpe for the same rules. If it does not,
"the sample is adversarial" was a bad excuse and the strategy is simply weak.

## What would count as failure

If P1 fails, the vol-scaling code is wrong.
If P2 fails in the *optimistic* direction, suspect a look-ahead before believing it.
If P4 fails, the diversification route is closed and the honest recommendation
is to stop rather than to keep searching equities.
