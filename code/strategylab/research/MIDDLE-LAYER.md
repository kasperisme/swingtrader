# The middle layer — working backwards from what actually outperformed

**Verdict: the prize is enormous and none of it is reachable from price and
volume. A middle layer between the screen and the setup cannot be built from
this information.**

The pipeline is two steps: a screen that says which names are eligible, and a
setup rule that says when to buy one. The proposal was a third step in between,
selecting the names most likely to outperform before any setup is looked for.

Rather than guess at what that layer should select on, the question was posed
backwards: label every eligible name-day by whether it *did* beat the benchmark
over a swing horizon, then ask (a) what perfect selection would have earned and
(b) how much of that is predictable from information available at the time.

Reproduce: see `strategylab/pipeline/attainability.py`.

---

## 1. Why this is a stronger test than anything before it

Every test in this project has been **univariate** — one signal, one horizon,
does its rank correlate with a forward return. Twenty-eight of those in the
setup study, 440 single hypotheses in the discovery loop. None of them can see
an **interaction**: a feature that matters only when another is high, a rule
that holds only in one regime.

A gradient-boosted model over all twenty-two features at once can. So a null
here rules out far more than a null from any number of univariate tests.

## 2. The ceiling: what perfect selection would earn

Momentum universe, 380,909 name-days over 1,716 sessions, excess return against
SPY, fills at the open of t+1:

| horizon | base rate beating SPY | oracle top decile | prize over random |
|---|---|---|---|
| 5 days | 49.8% | +8.12% | **+8.06%** |
| **10 days** | **49.6%** | **+11.74%** | **+11.58%** |
| 21 days | 49.4% | +17.58% | **+17.27%** |

Two things worth pausing on.

**The base rate is a coin flip.** Names passing the Minervini screen beat SPY
49.6% of the time over ten days. The screen selects strong trends and does not,
on its own, tilt the odds of outperformance at all — which is consistent with
`MOMENTUM-UNIVERSE.md` §5b finding that holding the whole screen merely matches
the index.

**The prize is enormous.** Perfect selection of the top decile would earn
**11.6% in excess return every ten sessions**. If any part of that were
reachable, a middle layer would be the most valuable component in the system.

## 3. How much is reachable: none of it

A `HistGradientBoostingClassifier` on all 22 features, trained on 302,361
name-days through 2023-11-30, tested on the sealed 2024-2026 vault with a
**21-day embargo** between them (labels are forward returns, so adjacent rows
share outcome; without the gap the model is scored on what it memorised):

| horizon | AUC train | **AUC test** | shuffled-label control | model top-minus-bottom decile |
|---|---|---|---|---|
| 5 days | 0.5784 | **0.4959** | 0.5067 | −0.08% |
| 10 days | 0.5834 | **0.4939** | 0.5011 | −0.62% |
| 21 days | 0.5920 | **0.5062** | 0.4991 | +0.14% |

**Out of sample the model is a coin flip at every swing horizon.** At ten days
its top decile returned +0.46% and its bottom decile +1.07% — the names it liked
did *worse* than the names it disliked.

The train/test gap is the signature: AUC 0.58 in-sample against 0.49 out. The
model can fit this data and none of what it fits generalises. The shuffled-label
control sits at 0.50 throughout, which certifies the embargo worked and the
0.49 is not an artefact of leakage.

## 4. What this does and does not rule out

**Ruled out:** a middle layer built from price and volume. Twenty-two features,
302k training rows, a learner that can represent interactions, three horizons,
a clean out-of-sample split. This is as strong a negative as the data can
produce, and it explains every earlier null in the project rather than adding
another to the pile — the univariate tests were not failing to find the right
signal, there is no signal in that information to find.

**Not ruled out:** a layer built from *different* information. Fundamentals
(point-in-time filings are wired but untested here), institutional flow, and the
news pipeline are all outside the feature set. `NEWS-OVERLAY-FINDINGS.md` shows
the news data is not yet long enough to test; fundamentals are available and
have never been put through this.

That is the shape of the answer worth acting on. **The three-step pipeline is a
good architecture and the middle slot is empty for a reason: everything
currently available to fill it is already in the screen.** Filling it requires
new information, not a better model over the same information.

## 5. Limitations

- **One model family.** `HistGradientBoosting` with one hyperparameter set. It
  is a strong learner and its in-sample AUC of 0.58 shows it can fit; but a
  different architecture is not literally excluded.
- **One label.** Binary outperformance versus SPY. A different target — risk-
  adjusted outperformance, drawdown avoidance, survival — might be more
  learnable, and the drawdown result elsewhere in this project hints that
  *risk* is more predictable here than *return*.
- **Survivorship.** Of 2,130 panel symbols, 2,129 still trade at the end. The
  names that failed are absent, so "which stocks outperform" is being asked of
  a sample with the losers removed.
