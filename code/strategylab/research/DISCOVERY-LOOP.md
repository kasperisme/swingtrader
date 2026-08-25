# The discovery loop — iterating without manufacturing a discovery

A loop told to run "until it finds alpha" will find alpha. The maximum of N
noise draws grows like `sqrt(2 ln N)`, so a fixed threshold of |t| > 2 is
breached essentially always once a search gets wide enough — 99% of the time at
N = 500, measured in `tests/test_discover.py`.

This project has demonstrated that repeatedly, and never once in the abstract:

| what looked like alpha | what killed it |
|---|---|
| trend screen "tripled" post-announcement drift | it lifted the no-news control by more |
| rolling anchor gave 81.8% spread convergence | random walks through the same anchor gave 81.3% |
| `rs_rank` and `reversal_5d` "timed" the breakout | they sort hit rate, not expectancy, and the control got the same lift |
| three VCP features agreed on base quality | two of them correlated at 0.92, and the sign flipped on the vault |
| `risk_pct` at \|t\| = 4.91, the largest effect measured | a tighter stop puts the 2R target nearer — mechanical |

Every one of those would have been reported as a finding by a loop optimising
for a low p-value. So the discipline is not a wrapper around the search; it is
the search.

```bash
.venv/bin/python -m strategylab.discover.cli run --iterations 40
.venv/bin/python -m strategylab.discover.cli status
```

---

## 1. The bar rises with the trial count

Significance is measured against `sqrt(2 ln N) + 0.5` — the expected maximum
|t| of N independent null draws — not against a constant:

| hypotheses tested | bar |
|---|---|
| 1 | \|t\| > 2.00 |
| 10 | 2.65 |
| 100 | 3.53 |
| 500 | 4.03 |
| 1000 | 4.22 |

This is the deflated Sharpe idea the genome search already uses, applied to
t-statistics. Its practical consequence is that **the thousandth hypothesis has
to be visibly better than the tenth to count as the same discovery**, which is
correct and is exactly what an undisciplined loop gets wrong.

`test_bar_would_be_breached_by_noise_at_a_fixed_threshold` pins the arithmetic:
across 200 simulated searches of width 500, a fixed 2.0 is cleared 99%+ of the
time and the rising bar survives most of them.

## 2. Failures count

The registry is append-only, persists across restarts, and records **every**
hypothesis that ran — including the ones screened out cheaply at rung 0. A bar
computed only from the hypotheses that looked interesting is the selection
effect wearing a lab coat, so the count that sets the bar is the count of
everything executed.

A run resumed tomorrow inherits today's trial count, and therefore today's
higher bar. Registration happens *before* execution: pre-registration, per
trial.

## 3. The space is finite, so a null is terminal

A hypothesis is a tuple — `(primitive, transform, outcome, horizon)` — over 22
features this project already computes, 5 transforms, 2 outcome families and 3
horizons. **440 hypotheses.** That buys three things a free-form proposer cannot:

* **Exhaustibility.** "Every hypothesis in the grammar has been tested and none
  cleared the bar" is an answer. A generative proposer can always produce one
  more, so it can never conclude.
* **Deduplication.** The same claim arriving twice under different words would
  inflate the trial count while adding no information — or worse, be counted as
  independent confirmation.
* **A well-defined N.** The bar is only meaningful if the thing being counted is.

Ordering is deliberate: `raw` and `negate` first, so a run stopped early has
covered the interpretable forms rather than a random slice.

## 4. What a hypothesis has to survive

Two rungs, mirroring the successive halving used on the genome search. Rung 0 is
a cheap IC screen; rung 1 pays for the full battery. To be **confirmed** a
hypothesis must:

1. clear the rising bar on dev, measured with Newey-West errors at the horizon
   (overlapping forward returns otherwise overstate significance by ~3x);
2. have a **clean placebo** — the same signal shuffled within each day must not
   fire. A hypothesis whose placebo also fires is rejected and logged as a
   broken control, not promoted;
3. beat its **matched control** — for IC, the incremental coefficient after the
   momentum controls, because on a universe that *is* a momentum screen a
   standalone IC mostly measures how much of the screen a signal re-encoded;
   for setup conditioners, the same conditioner applied to the no-trigger book;
4. **confirm on the vault**, same sign, |t| ≥ 1.5. Each vault use is logged,
   because a holdout tested repeatedly is a training set.

## 5. Stopping conditions

1. A confirmed finding.
2. The space is exhausted.
3. The iteration or time budget is spent.

Not on the list: "it started to look promising." That is the condition that ends
most searches and is the reason most searches are wrong.

## 6. The loop is validated in both directions

A search that cannot detect a real effect is worthless however disciplined; a
search that reports findings on noise is worse than worthless. Both are pinned:

* `test_loop_finds_a_planted_signal` builds a panel where the 5-day return
  genuinely predicts the next five days, and asserts the loop surfaces it at
  |t| > 3.
* `test_loop_confirms_nothing_on_pure_noise` runs the loop over 30+ hypotheses
  on a panel with no planted effect and asserts it comes back empty.

## 7. First full run: 440 hypotheses, nothing cleared

The loop ran the entire grammar to exhaustion in about five minutes.

```
space 440 hypotheses | tested 440 | cleared 0 | confirmed 0
significance bar |t| > 3.99   (max |t| seen 3.72, mean 1.05)
stopped: space exhausted
```

**The headline is the maximum.** For N absolute standard normals the expected
largest value is `sqrt(2 ln 2N)`, which at N = 439 is **3.68**. The search's
actual maximum was **3.72**. The single best result out of 440 is, to two
significant figures, exactly the size a search of this width produces from
nothing at all.

| top hypothesis | t | placebo t | |
|---|---|---|---|
| `rs_line_high\|delta_21\|setup` | +3.72 | **+2.03** | placebo also fired |
| `rs_line_high\|vs_own_mean_63\|setup` | +3.62 | −0.86 | below bar |
| `rs_line_high\|delta_21\|ic\|H21` | −3.60 | −0.72 | below bar |
| `dist_from_sma20\|vs_own_mean_63\|ic\|H21` | −3.36 | +0.02 | below bar |

The best result of all is also the one whose **shuffled-label placebo fired at
+2.03** — a broken control, correctly rejected rather than promoted. Its sibling
`rs_line_high|delta_63|setup` had a placebo at +3.16. Whatever the `rs_line_high`
family does inside the setup book, it is not measuring what it claims to.

### A defect the run exposed

`negate` was in the transform list. Every test in the loop is **two-sided**, so
negating a signal returns an exact sign mirror of the same statistic — **83 of 88
raw/negate pairs came back as exact mirrors**, including `rs_line_high|raw`
at −2.97 against `rs_line_high|negate` at +2.97. It doubled the trial count while
adding no information.

The direction was safe — an inflated N means a bar that is too high, which costs
power rather than creating false positives — but a count that sets a
significance threshold has to mean something, and a duplicate does not.
`negate` is removed; the space is now **352 hypotheses** and the honest bar is
**|t| > 3.92**. Against a maximum of 3.72, the conclusion is unchanged.

### The distribution is wider than iid noise, and that is expected

Mean |t| came in at **1.05** against the 0.80 an independent-noise search would
give, and **12.8%** of results exceeded |t| > 2 against 4.6%. That is not
evidence of signal — it is what correlated tests look like. Many primitives
measure nearly the same thing (`mom_12_1` and `residual_momentum` correlated at
+0.83 in the earlier IC study), and transforms of one primitive are related by
construction. Correlation widens the cross-hypothesis distribution without
putting anything in the tail, which is precisely the pattern observed: a fat
middle and a maximum sitting exactly on the noise benchmark.

**It is also the argument against reading the near-misses as "almost".** Three
of the top five are the same underlying quantity in different clothing.

## 8. Limitations

- **The grammar bounds what can be found.** 440 hypotheses over features this
  project already computes is a search of the plausible, not the ingenious. A
  genuine edge expressible only outside the grammar is invisible here, and no
  amount of iteration inside it will surface one.
- **The primitives are all price and volume.** Everything in the space derives
  from OHLCV plus a benchmark. That is the same information every other
  participant has, which is the strongest prior against finding anything.
- **The universe is fixed and survivorship-biased.** 2,129 of 2,130 panel
  symbols still trade at the panel end; zero names the screen ever held stopped
  trading. Any edge found here is found on a panel with the failures removed.
- **The vault is finite.** It has now been used by several studies. Each
  additional use erodes it, and the registry logs them so the erosion is
  visible rather than assumed.
