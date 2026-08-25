# The news overlay — does the pipeline add anything the price data lacks?

**Verdict: not resolvable on this sample, and that is the finding.**

The NIS news pipeline is the one input in this project that is not available to
every other participant, so it is the one worth testing hardest. It is also the
one the data cannot yet answer for: the pipeline starts **2025-04-10**, giving
sixteen months that sit entirely inside the window the rest of the project
reserved as its vault.

No signal clears its power floor, at any horizon, on either half of the sample.
But "we could not see it" and "it is not there" are different statements, and
this sample only supports the first.

Reproduce: `.venv/bin/python -m strategylab.news.cli impact` (~25 s).
Artifacts: `output/news/impact/impact.json`

---

## 1. What exists, and what does not

| table | coverage | rows |
|---|---|---|
| `news_articles` | 2025-04-10 → 2026-08-20 | 213,099 |
| `ticker_sentiment_heads` | 2025-04-10 → 2026-08-20 | 342,976 |
| **`news_impact_heads`** (the NIS scores) | **2026-04-06 → 2026-08-20** | 2,622,919 |
| `news_trends_ticker_daily_v` | 2026-04-22 → 2026-08-20 | rolling window |

The proprietary impact scores — the most differentiated thing here — cover
**four and a half months**. They are not testable at all and were not tested.
The trend view is a rolling window kept for the UI, so the base table is the
better source despite the view being the more obvious one.

Aligned to the price panel, which ends 2026-06-30, the usable overlap is **306
sessions**.

## 2. Coverage of the tradeable universe

**Median 147 momentum-universe names carry news on a given day — 38% of the
cross-section.**

That number was wrong the first time it was computed. Inside the coverage window
a name with no article gets attention 0 rather than NaN, which is correct for
the *signal* and wrong for a *coverage statistic*: measuring "is the value
finite" reported **100%** when the honest figure is 38%. A signal that can rank
38% of the cross-section is usable, but it is not the whole book, and the two
readings differ by enough to change what the study is.

## 3. The power floor, stated before the results

Overlapping forward returns mean the effective sample is roughly
`sessions / horizon`, not `sessions`:

| horizon | effective independent observations | smallest resolvable IC |
|---|---|---|
| H5 | 23 – 37 | 0.031 – 0.046 |
| H21 | **4.8 – 8.7** | 0.056 – 0.111 |

A strong real-world equity signal runs an IC of 0.02–0.05. **At 21 days this
sample cannot resolve any plausible signal at all**; at 5 days it can only
resolve one at the very top of that range.

## 4. Results

Four signals, deliberately different in kind: article-weighted sentiment,
attention (article count), attention against the name's own trailing normal, and
the change in sentiment. Split into news-dev (2025-04 → 2025-12) and
news-holdout (2026-01 → 2026-06).

**Nothing clears the floor.** Not one of the sixteen span × signal × horizon
cells.

The one cell that looked significant is instructive. `news_surprise` on the
holdout at H21 reported **IC +0.0303, t = +2.95** — until the overlap correction
was fixed (§6). It rests on **4.8 effective observations**.

What the sample *can* say is something weaker and more interesting — whether the
sign is stable across the two halves:

| signal | dev IC | holdout IC | same sign |
|---|---|---|---|
| **news_attention** H5 | +0.0173 | +0.0091 | yes |
| **news_attention** H21 | +0.0158 | +0.0343 | yes |
| **news_surprise** H5 | +0.0118 | +0.0074 | yes |
| **news_surprise** H21 | +0.0021 | +0.0303 | yes |
| news_sentiment_delta H5 | −0.0035 | −0.0087 | yes |
| news_sentiment_delta H21 | −0.0068 | −0.0048 | yes |
| news_sentiment H21 | −0.0126 | −0.0037 | yes |
| news_sentiment H5 | −0.0134 | **+0.0120** | **no** |

**Attention is positive in all four of its cells**, at IC 0.007–0.034 — the
direction the Da/Engelberg/Gao attention literature predicts, and below what
this sample can resolve. Seven of eight signs agree overall, but the signals are
not independent, so this is suggestive and nothing more.

**Sentiment — the signal the product is actually built on — is the worst of the
four.** It is the only one that flips sign between the halves, and it is
negative at both horizons on dev. Attention, which is nearly free to compute and
carries no scoring model at all, looks better than the scored sentiment it was
derived from.

On the setup book the picture is the same shape and thinner still: 1,185
pullback entries on dev and 961 on holdout, with several conditioners dropping
below the 400-setup minimum. `news_surprise` runs ΔR **−0.143** on dev and
**+0.266** on holdout — a sign flip, on a sample too small to have tested it.

## 5. What this does and does not license

- It does **not** license "news adds nothing." The floor is above every
  plausible effect size; the test could not have found a real signal of normal
  strength.
- It does **not** license trading any of these. Nothing is established.
- It **does** license two priorities. First, **wait for data** — the pipeline
  needs roughly three more years before an H21 test has the power to conclude,
  and the impact scores need considerably longer. Second, **prefer attention
  over sentiment** when the time comes: it was consistent where sentiment was
  not, and it requires no model.

## 5b. Tried it in the portfolio: a tilt, paired against the untilted book

An IC is a statistic; the question a trader asks is whether the P&L changes. So
the news signals were used to *weight* the momentum book — same universe, same
rebalance dates, same costs, same period, only the weights differ. The paired
difference is far less noisy than either book alone, which is the only reason a
fifteen-month window is worth running at all.

Window 2025-04 → 2026-06. Untilted screen **+49.0% CAGR, Sharpe 2.11**; SPY
**+33.0%, Sharpe 2.14**. (That is an unusually strong period for both — it is
not a normal fifteen months, and nothing here generalises on its own.)

| tilt | CAGR | Sharpe | delta/yr | t | +months | bites |
|---|---|---|---|---|---|---|
| **news_surprise** rank-weight | +53.6% | 2.21 | **+3.17%** | +1.88 | 60% | 93% |
| **news_attention** rank-weight | +53.3% | 2.13 | **+3.10%** | +1.13 | 60% | 100% |
| news_sentiment_delta rank-weight | +48.7% | 2.09 | −0.17% | −0.17 | 47% | 93% |
| news_sentiment_delta top-half | +48.1% | 2.13 | −0.68% | −0.36 | 33% | 93% |
| **news_sentiment** rank-weight | +47.4% | 2.06 | **−1.13%** | −0.59 | 40% | 100% |
| **news_sentiment** top-half | +44.2% | 2.00 | **−3.38%** | −1.21 | 33% | 100% |
| news_surprise top-half | — | — | not testable | | | 14% |
| news_attention top-half | — | — | not testable | | | 7% |

Fifteen monthly observations, so nothing is significant and nothing should be
traded on this. What is worth noting is that the ordering is the same as the IC
table produced independently: **attention and surprise add, sentiment subtracts,
and sentiment's strongest form is the worst row in the study.**

### Two rows are marked "not testable", and finding out why mattered

The `bites` column reports the share of rebalances on which the tilt actually
changed the weights. `news_attention|top_half` bit on **7%** of them — it was a
no-op, and its "−0.58% a year, zero months positive" was a statement about the
tilt construction rather than about news.

Two separate causes, both worth recording:

* **The median was taken over the whole cross-section.** With 62% of names
  carrying no article and given the neutral middle rank, the median *is* that
  rank, so "keep everything at or above the median" keeps everything. Thirteen
  of fifteen months came back as exactly zero difference. The cut is now taken
  over the names that actually have a signal.
* **`news_attention` is an integer count with heavy ties.** Even after the fix,
  a median split of a variable whose modal value is 1 selects nothing. That is
  not repairable by construction and the row is reported as not testable rather
  than as a null.

A tilt that never bites produces a perfect null, and a perfect null is exactly
what an underpowered study wants to find. `run_hold` now returns
`tilt_effective_share`, anything below 50% is refused, and
`test_run_hold_reports_whether_the_tilt_actually_bit` pins it.

## 6. Two defects found, both in the harness rather than the data

**Newey-West under-corrected on the short sample.** `ic_summary` used
`lags = horizon` unconditionally. That is the standard choice and it silently
fails when the sample is only a few multiples of the horizon: 21 lags on 101
observations is 21% of the sample, against a rule-of-thumb of about 4. It
reported **t = 2.95** where the honest figure from 4.8 effective observations is
**1.09**. Lags are now capped at a tenth of the sample, the result carries an
`overlap_unreliable` flag, and a non-overlapping block statistic is reported
alongside — withheld entirely below eight blocks, because a t-statistic from
four observations is theatre. Pinned by
`test_newey_west_lags_are_capped_on_a_short_sample`.

This one matters beyond the news study: every IC in the momentum work used the
same function. Those samples are long (2,500 sessions, 119 effective
observations at H21) so the cap does not bind there, but it would have bound
silently on any short-window study run later.

**Coverage conflated "in window" with "seen".** Reported 100% of the
cross-section when the true figure was 38% — see §2.

**A degenerate tilt read as a null.** See §5b: two of eight tilts never changed
the portfolio, and reported clean-looking zeros.
