"""Small, honest statistics - standard library only, no numpy or scipy.

RAGProbe reports rates measured on finite, often noisy samples (a live model is
nondeterministic; an attack set is a sample of the attacks that exist). A single
percentage hides how uncertain it is and whether a difference between two
defences is real or just noise. These helpers put error bars and paired tests
around every headline number so the claims survive scrutiny.

Everything here is deterministic given its inputs (the bootstrap takes an
explicit seed), closed-form where possible, and has no third-party dependency,
so it runs in the same minimal environment as the rest of the core.

- ``wilson_interval``    - a confidence interval for a single rate (a proportion)
- ``mcnemar`` / ``mcnemar_from_pairs`` - did two methods differ on the *same* items?
- ``bootstrap_ci``       - a confidence interval for any metric (F1, recall, ...)
- ``risk_difference`` / ``odds_ratio`` / ``cohens_h`` - how big is the effect?
"""

from __future__ import annotations

import math
import random
from typing import Callable, List, Sequence, Tuple, TypeVar

T = TypeVar("T")

# 95% by default. z is the standard-normal critical value for the two-sided
# interval; 1.96 <-> 95%, 2.576 <-> 99%.
Z95 = 1.959963984540054


def wilson_interval(successes: int, total: int, z: float = Z95) -> Tuple[float, float]:
    """Wilson score interval for a proportion ``successes / total``.

    Preferred over the textbook "normal approximation" because it stays inside
    [0, 1] and behaves well for small samples and rates near 0 or 1 - exactly
    the regime security rates live in (0% attack-success, a handful of trials).
    """
    if total <= 0:
        return (0.0, 0.0)
    phat = successes / total
    denom = 1.0 + z * z / total
    centre = (phat + z * z / (2 * total)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def _binom_two_sided_p(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-sided binomial p-value for ``k`` successes in ``n`` trials.

    Used for the exact McNemar test. For p = 0.5 the distribution is symmetric,
    so the two-sided p is twice the smaller tail, capped at 1.
    """
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
               for i in range(0, min(k, n - k) + 1))
    return min(1.0, 2.0 * tail)


def mcnemar(b: int, c: int, exact: bool | None = None) -> dict:
    """McNemar's paired test on the two *discordant* counts.

    When you run two methods (two defences, two models, two detectors) on the
    **same** attacks, each attack falls into one of four cells. Only the two
    where the methods disagree carry information:

    - ``b`` - method A succeeded (e.g. blocked) where B failed
    - ``c`` - method B succeeded where A failed

    The null hypothesis is that the two methods are equally likely to be the one
    that wins a disagreement. A small p-value means the difference is real, not
    sampling noise. Uses the exact binomial test when the number of
    disagreements is small (<= 25, the usual rule) and the continuity-corrected
    chi-square approximation otherwise; pass ``exact`` to force a choice.
    """
    n = b + c
    use_exact = (n <= 25) if exact is None else exact
    if use_exact:
        p = _binom_two_sided_p(min(b, c), n)
        stat = float(min(b, c))  # the test statistic for the exact test
        method = "exact-binomial"
    else:
        stat = (abs(b - c) - 1) ** 2 / n if n else 0.0
        # survival of chi-square with 1 df at `stat` is erfc(sqrt(stat/2))
        p = math.erfc(math.sqrt(stat / 2.0)) if stat > 0 else 1.0
        method = "chi2-continuity"
    return {"b": b, "c": c, "discordant": n, "statistic": round(stat, 4),
            "p_value": round(p, 6), "method": method}


def mcnemar_from_pairs(wins_a: Sequence[bool], wins_b: Sequence[bool],
                       exact: bool | None = None) -> dict:
    """McNemar's test from two equal-length per-item outcome vectors.

    ``wins_a[i]`` / ``wins_b[i]`` are the paired outcomes on item ``i`` (for
    example "did this defence block attack i"). Raises if the vectors differ in
    length, since the test is only valid on the same items.
    """
    if len(wins_a) != len(wins_b):
        raise ValueError("paired outcomes must have the same length")
    b = sum(1 for a, bb in zip(wins_a, wins_b) if a and not bb)
    c = sum(1 for a, bb in zip(wins_a, wins_b) if bb and not a)
    return mcnemar(b, c, exact=exact)


def bootstrap_ci(items: Sequence[T], statistic: Callable[[Sequence[T]], float],
                 resamples: int = 2000, alpha: float = 0.05,
                 seed: int = 0) -> Tuple[float, float]:
    """Percentile bootstrap confidence interval for any ``statistic``.

    Resamples ``items`` with replacement ``resamples`` times, recomputes the
    statistic each time, and takes the ``alpha/2`` and ``1 - alpha/2``
    percentiles. Works for metrics that have no clean closed-form interval, such
    as F1 or recall over a labelled set, where each item is a ``(prediction,
    label)`` pair. Deterministic for a given ``seed``.
    """
    n = len(items)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats: List[float] = []
    for _ in range(resamples):
        sample = [items[rng.randrange(n)] for _ in range(n)]
        stats.append(statistic(sample))
    stats.sort()
    lo = stats[max(0, int(math.floor((alpha / 2) * resamples)))]
    hi = stats[min(resamples - 1, int(math.ceil((1 - alpha / 2) * resamples)) - 1)]
    return (round(lo, 4), round(hi, 4))


def risk_difference(s1: int, n1: int, s2: int, n2: int) -> float:
    """Difference of two proportions, ``p1 - p2`` (a simple, readable effect size)."""
    p1 = s1 / n1 if n1 else 0.0
    p2 = s2 / n2 if n2 else 0.0
    return round(p1 - p2, 4)


def odds_ratio(s1: int, n1: int, s2: int, n2: int) -> float:
    """Odds ratio between two groups, with a 0.5 Haldane correction for zero cells."""
    a, b = s1, n1 - s1
    c, d = s2, n2 - s2
    if 0 in (a, b, c, d):
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    return round((a * d) / (b * c), 4)


def cohens_h(p1: float, p2: float) -> float:
    """Cohen's h effect size for the gap between two proportions.

    Roughly: 0.2 small, 0.5 medium, 0.8 large. Unlike a raw difference it is
    stable near 0 and 1, so it fairly describes "50% vs 26% recall" and
    "4% vs 0%" on the same scale.
    """
    phi1 = 2 * math.asin(math.sqrt(max(0.0, min(1.0, p1))))
    phi2 = 2 * math.asin(math.sqrt(max(0.0, min(1.0, p2))))
    return round(phi1 - phi2, 4)
