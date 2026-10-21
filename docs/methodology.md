# How RAGProbe measures

Every headline number in this project is a measurement on a finite, often noisy
sample: a live model is nondeterministic, and an attack set is a sample of the
attacks that could exist. A bare percentage hides how certain it is. This page
explains the statistics RAGProbe uses so that a reader can tell a real result
from sampling noise, and reproduce the maths.

All of it lives in one small, dependency-free module,
[`src/ragprobe/stats.py`](../src/ragprobe/stats.py) (standard library only — no
numpy, no scipy), and is exercised by [`tests/test_stats.py`](../tests/test_stats.py).

## 1. A rate is never reported without an interval — Wilson score

Attack-success rate, recall and false-positive rate are all **proportions**
(successes ÷ trials). We report each with a **Wilson 95% confidence interval**
rather than the textbook normal approximation, because the Wilson interval stays
inside `[0, 1]` and behaves correctly for small samples and rates near 0 % or
100 % — exactly where security numbers sit (0 % attack-success on a handful of
trials).

> **How to read it.** "ASR 8 % (95 % CI 1–27 %)" means: our best estimate is 8 %,
> but with this many trials the true rate could plausibly be anywhere from 1 % to
> 27 %. Two rates whose intervals overlap heavily are **not** a result.

`wilson_interval(successes, total)`.

## 2. Comparing two methods on the same attacks — McNemar's test

When we compare two **defences**, two **models** or two **detectors**, they are
run on the *same* attacks. That makes the comparison **paired**, and the right
test is **McNemar's test**, which looks only at the attacks where the two methods
*disagreed*:

- `b` — method A won (e.g. blocked) where B lost,
- `c` — method B won where A lost.

The null hypothesis is that a disagreement is equally likely to go either way. A
small p-value means one method is genuinely better, not luckier.

- With few disagreements (≤ 25, the usual rule) we use the **exact binomial**
  test; above that, the **continuity-corrected chi-square** approximation.
- `mcnemar(b, c)` or `mcnemar_from_pairs(wins_a, wins_b)`.

The model comparison report (`ragprobe security compare`) prints a McNemar row
for the strongest model against each other model, pairing on whether each attack
got through under the base defence (an attack counts as "through" if it succeeded
on any trial).

> **Why paired, not two separate intervals.** Two overlapping Wilson intervals
> can still hide a real, consistent difference, because they ignore that the two
> methods faced the identical attacks. McNemar uses that pairing and is more
> sensitive.

## 3. Intervals for metrics with no clean formula — the bootstrap

Recall and F1 on a labelled set have no tidy closed-form interval. We use a
**percentile bootstrap**: resample the `(prediction, label)` pairs with
replacement 2000 times, recompute the metric each time, and take the 2.5th and
97.5th percentiles. The detector benchmark reports recall with its bootstrap
interval so that a gap between two detectors (for example 40 % vs 17 %) can be
judged against the test set's size.

`bootstrap_ci(items, statistic, resamples=2000, seed=…)` — deterministic for a
given seed, so committed numbers reproduce exactly.

## 4. How big is the difference — effect sizes

A p-value says *whether* two numbers differ; an **effect size** says *by how
much*, which is what actually matters for a decision.

- **Risk difference** — `p1 − p2`, the plain gap between two rates.
- **Odds ratio** — with a 0.5 Haldane correction so a clean 10/10-vs-0/10 split
  still yields a finite number.
- **Cohen's h** — a variance-stable gap between two proportions (≈ 0.2 small,
  0.5 medium, 0.8 large). Unlike a raw difference it is stable near 0 and 1, so
  it fairly describes both "50 % vs 26 % recall" and "4 % vs 0 %".

## Reproducibility

The statistics are deterministic: the bootstrap takes an explicit seed, so
committed numbers reproduce exactly. The project's rule is that every reported
number comes from a committed run and the command that made it; the benchmark
runner records a full manifest (package version, git SHA, model, temperature,
prompt and dataset hashes, date) into the results JSON so a run can be repeated.
If a number cannot be reproduced from its committed run and command, treat it as
a bug.
