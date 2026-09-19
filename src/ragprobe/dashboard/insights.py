"""Auto-generated findings.

Every insight is produced by a small, explicit rule and carries that rule as text,
so the reader can decide whether to trust it. The aim is not to be clever; it is
to do the first ten minutes of triage a QA engineer would do by hand - find the
worst category, the check that fails most, the cases that will not stay still,
and whether a failure is the retriever's fault or the generator's - and to say
exactly how each conclusion was reached.

Nothing here is a verdict. A heuristic that overclaims trains people to ignore the
panel, so each rule states its own limits (for example, that a flip across a
config change is sensitivity, not flakiness).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ragprobe.dashboard.analytics import (
    ATTRIBUTION_ERROR,
    ATTRIBUTION_GENERATION,
    ATTRIBUTION_MIXED,
    ATTRIBUTION_REFUSAL,
    ATTRIBUTION_RETRIEVAL,
    DashboardModel,
)
from ragprobe.regression.diff import STATUS_DEGRADED, STATUS_REGRESSED

SEVERITY_GOOD = "good"
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_BAD = "bad"

#: Minimum number of runs before flakiness is reported at all. Two runs give one
#: transition, which is a change, not a pattern.
MIN_RUNS_FOR_FLAKINESS = 3


@dataclass
class Insight:
    kind: str
    severity: str
    title: str
    body: str
    #: The rule that produced this insight, shown as a tooltip.
    rule: str
    cases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "body": self.body,
            "rule": self.rule,
            "cases": list(self.cases),
        }


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _join(ids: List[str], limit: int = 4) -> str:
    shown = ", ".join(ids[:limit])
    return shown if len(ids) <= limit else f"{shown} (+{len(ids) - limit} more)"


# ------------------------------------------------------------------ rules


def worst_category(model: DashboardModel) -> Optional[Insight]:
    failing = [c for c in model.categories if c.failed > 0]
    if not failing:
        return Insight(
            "worst_category", SEVERITY_GOOD, "Every category is passing",
            f"All {len(model.categories)} categories pass every case in the latest run.",
            "Rule: report the category with the lowest pass rate; none has a failing case.",
        )
    worst = failing[0]
    ids = [row.id for row in model.rows if str(row.case.get("category")) == worst.name and not row.passed]
    trend = ""
    if worst.previous_pass_rate is not None and abs(worst.previous_pass_rate - worst.pass_rate) > 1e-9:
        direction = "down from" if worst.pass_rate < worst.previous_pass_rate else "up from"
        trend = f" ({direction} {_pct(worst.previous_pass_rate)} on the previous run)"
    return Insight(
        "worst_category",
        SEVERITY_BAD if worst.pass_rate < 0.5 else SEVERITY_WARN,
        f"Weakest category: {worst.name}",
        f"{worst.passed}/{worst.total} passing ({_pct(worst.pass_rate)}){trend}. Failing: {_join(ids)}.",
        "Rule: categories ranked by pass rate ascending, ties broken by mean score. Only categories "
        "with at least one failing case qualify. Small categories swing hard - one case out of two is 50%.",
        ids,
    )


def most_common_failing_check(model: DashboardModel) -> Optional[Insight]:
    failing = [c for c in model.checks if c.failed > 0 and not c.advisory]
    if not failing:
        advisory = [c for c in model.checks if c.failed > 0 and c.advisory]
        if advisory:
            top = advisory[0]
            return Insight(
                "failing_check", SEVERITY_INFO, f"Only advisory checks are failing ({top.name})",
                f"No required check fails. The most common advisory failure is {top.name} "
                f"({top.failed} of {top.passed + top.failed} applicable cases). Advisory checks are "
                "reported but never gate the build.",
                "Rule: count failed checks by name over the latest run, required checks first. "
                "A check is advisory when it is not in evaluation.required_checks.",
            )
        return None
    top = failing[0]
    ids = [
        row.id for row in model.rows
        if any(ch.get("name") == top.name and ch.get("applicable", True) and not ch.get("passed")
               for ch in row.case.get("checks") or [])
    ]
    return Insight(
        "failing_check",
        SEVERITY_WARN,
        f"Most common failing check: {top.name}",
        f"{top.failed} of {top.passed + top.failed} applicable cases fail {top.name} "
        f"({_pct(top.fail_rate)}). Cases: {_join(ids)}.",
        "Rule: count failed, applicable checks by name over the latest run; required checks rank "
        "above advisory ones. Skipped (not applicable) checks are excluded from the denominator.",
        ids,
    )


def flaky_cases(model: DashboardModel) -> Optional[Insight]:
    runs = len(model.points)
    if runs < MIN_RUNS_FOR_FLAKINESS:
        return Insight(
            "flakiness", SEVERITY_INFO, "Not enough history to assess flakiness",
            f"{runs} run(s) stored; flakiness is only assessed from {MIN_RUNS_FOR_FLAKINESS}. "
            "Keep running the suite and this panel fills in.",
            f"Rule: a case is flaky when its pass/fail status changes between consecutive runs with "
            f"an identical config fingerprint. Needs at least {MIN_RUNS_FOR_FLAKINESS} runs.",
        )
    flaky = sorted(
        (h for h in model.case_histories.values() if h.flips_same_config > 0),
        key=lambda h: (-h.flips_same_config, h.id),
    )
    sensitive = sorted(
        (h for h in model.case_histories.values() if h.flips_same_config == 0 and h.flips_config_change > 0),
        key=lambda h: (-h.flips_config_change, h.id),
    )
    rule = (
        "Rule: a flip is a pass/fail change between two consecutive runs that both contain the case. "
        "Flips under an identical config fingerprint are nondeterminism (flaky); flips across a "
        "config change are sensitivity to that change and are listed separately."
    )
    if flaky:
        ids = [h.id for h in flaky]
        return Insight(
            "flakiness", SEVERITY_BAD,
            f"{len(flaky)} flaky case(s) flip under an unchanged config",
            f"{_join(ids)} changed pass/fail status between runs whose config fingerprint was identical. "
            "With a deterministic provider that should be impossible; check for nondeterminism in the "
            "pipeline, the corpus, or the evaluator.",
            rule, ids,
        )
    if sensitive:
        ids = [h.id for h in sensitive]
        return Insight(
            "flakiness", SEVERITY_INFO,
            f"No flaky cases; {len(sensitive)} case(s) are config-sensitive",
            f"No case flips under an identical config. {_join(ids)} flipped only when the configuration "
            "changed, which is the harness doing its job, not noise.",
            rule, ids,
        )
    return Insight(
        "flakiness", SEVERITY_GOOD, "No case flips across the stored history",
        f"Every case kept the same pass/fail status across all {runs} runs.",
        rule,
    )


def largest_drops(model: DashboardModel, limit: int = 3) -> Optional[Insight]:
    if model.diff is None:
        return None
    changed = [
        c for c in model.diff.cases
        if c.score_delta is not None and c.score_delta < -model.epsilon
    ]
    changed.sort(key=lambda c: (c.score_delta or 0.0, c.id))
    if not changed:
        return Insight(
            "score_drops", SEVERITY_GOOD, "No case lost score against the baseline",
            f"No case's score fell by more than epsilon ({model.epsilon}) since the baseline.",
            "Rule: cases ranked by (current score - baseline score); only drops larger than epsilon count.",
        )
    top = changed[:limit]
    parts = []
    for c in top:
        tag = " (now failing)" if c.status == STATUS_REGRESSED else ""
        parts.append(f"{c.id} {c.score_delta:+.3f}{tag}")
    regressed = [c.id for c in changed if c.status == STATUS_REGRESSED]
    return Insight(
        "score_drops",
        SEVERITY_BAD if regressed else SEVERITY_WARN,
        f"Largest score drops since baseline: {len(changed)} case(s) fell",
        "; ".join(parts) + ". "
        + (f"{len(regressed)} of them crossed from passing to failing." if regressed
           else "None crossed the pass/fail line, so these are drift, not breaks."),
        f"Rule: cases ranked by score delta versus the baseline; only drops larger than epsilon "
        f"({model.epsilon}) count. A drop that also flips pass -> fail is a regression; a drop "
        f"that stays passing is degradation ({STATUS_DEGRADED}).",
        [c.id for c in top],
    )


def attribution(model: DashboardModel) -> Optional[Insight]:
    failing = [row for row in model.rows if not row.passed and row.attribution is not None]
    if not failing:
        return Insight(
            "attribution", SEVERITY_GOOD, "Nothing to attribute: every case passes",
            "There are no failing cases in the latest run.",
            "Rule: failing cases are attributed to retrieval, generation, refusal policy or an error "
            "using their retrieval metrics and failing checks.",
        )
    by_kind: Dict[str, List[str]] = {}
    for row in failing:
        by_kind.setdefault(row.attribution.kind, []).append(row.id)  # type: ignore[union-attr]
    sentences = []
    label = {
        ATTRIBUTION_GENERATION: "a generation problem (retrieval found every expected chunk)",
        ATTRIBUTION_RETRIEVAL: "a retrieval problem (no expected chunk was retrieved)",
        ATTRIBUTION_REFUSAL: "a refusal-policy problem (the case has no expected chunks)",
        ATTRIBUTION_MIXED: "mixed (retrieval was partial)",
        ATTRIBUTION_ERROR: "an error (the case raised before evaluation)",
    }
    for kind in (ATTRIBUTION_GENERATION, ATTRIBUTION_RETRIEVAL, ATTRIBUTION_REFUSAL, ATTRIBUTION_MIXED, ATTRIBUTION_ERROR):
        ids = by_kind.get(kind)
        if ids:
            sentences.append(f"{len(ids)} {label[kind]}: {_join(ids)}")
    top_count = max(len(ids) for ids in by_kind.values())
    leaders = sorted(kind for kind, ids in by_kind.items() if len(ids) == top_count)
    if len(leaders) == 1:
        headline = {
            ATTRIBUTION_GENERATION: "Failures point at generation, not retrieval",
            ATTRIBUTION_RETRIEVAL: "Failures point at retrieval",
            ATTRIBUTION_REFUSAL: "Failures are about refusal policy",
            ATTRIBUTION_MIXED: "Failures have mixed causes",
            ATTRIBUTION_ERROR: "Failures are crashes, not verdicts",
        }[leaders[0]]
    else:
        headline = "Failures split evenly between " + " and ".join(leaders)
    return Insight(
        "attribution",
        SEVERITY_BAD if ATTRIBUTION_ERROR in by_kind else SEVERITY_WARN,
        headline,
        "; ".join(sentences) + ".",
        "Rule: for each failing case, recall@k = 1.0 means every expected chunk was retrieved, so the "
        "generator had the evidence and the fault is in generation; hit rate 0 means no expected chunk "
        "was retrieved, so fix retrieval first; no expected chunks means the case tests refusal policy; "
        "anything in between is mixed. This is a triage hint, not a root cause.",
        [row.id for row in failing],
    )


def pass_rate_trend(model: DashboardModel) -> Optional[Insight]:
    rates = [p.pass_rate for p in model.points]
    if len(rates) < 2 or any(r is None for r in rates[-2:]):
        return None
    rule = (
        "Rule: compare pass rate on each consecutive pair of stored runs. A streak is the number of "
        "consecutive runs moving in the same direction, ending at the latest run. Runs across a config "
        "change are included, so a streak can be the sum of deliberate changes."
    )
    # Count the streak ending at the latest run.
    direction = 0
    streak = 0
    for i in range(len(rates) - 1, 0, -1):
        cur, prev = rates[i], rates[i - 1]
        if cur is None or prev is None:
            break
        step = (cur > prev) - (cur < prev)
        if step == 0:
            break
        if direction == 0:
            direction = step
        if step != direction:
            break
        streak += 1
    latest, previous = rates[-1], rates[-2]
    if direction == 0:
        return Insight(
            "trend", SEVERITY_INFO, "Pass rate is flat against the previous run",
            f"Pass rate held at {_pct(latest)} between the last two runs.", rule,
        )
    if direction < 0:
        return Insight(
            "trend", SEVERITY_BAD if streak >= 2 else SEVERITY_WARN,
            f"Pass rate has fallen for {streak} consecutive run(s)",
            f"Now {_pct(latest)}, down from {_pct(previous)} on the previous run"
            + (f" and {_pct(rates[-1 - streak])} {streak} runs ago." if streak >= 2 else "."),
            rule,
        )
    return Insight(
        "trend", SEVERITY_GOOD,
        f"Pass rate has risen for {streak} consecutive run(s)",
        f"Now {_pct(latest)}, up from {_pct(previous)} on the previous run"
        + (f" and {_pct(rates[-1 - streak])} {streak} runs ago." if streak >= 2 else "."),
        rule,
    )


def latest_config_change(model: DashboardModel) -> Optional[Insight]:
    latest = model.latest_point
    if not latest.config_changed or model.previous is None:
        if len(model.points) > 1:
            return Insight(
                "config_change", SEVERITY_INFO, "Latest run used the same config as the previous one",
                "Any difference between the last two runs is therefore not explained by a config change.",
                "Rule: compare the config fingerprint of the latest run with the run before it.",
            )
        return None
    previous_point = model.points[-2]
    delta = None
    if latest.pass_rate is not None and previous_point.pass_rate is not None:
        delta = latest.pass_rate - previous_point.pass_rate
    changes = "; ".join(latest.changes[:4]) + (" ..." if len(latest.changes) > 4 else "")
    if delta is None:
        effect = "Pass rate on either side is not recorded."
        severity = SEVERITY_INFO
    elif abs(delta) < 1e-9:
        effect = f"Pass rate did not move ({_pct(latest.pass_rate)})."
        severity = SEVERITY_INFO
    elif delta < 0:
        effect = f"Pass rate fell from {_pct(previous_point.pass_rate)} to {_pct(latest.pass_rate)}."
        severity = SEVERITY_WARN
    else:
        effect = f"Pass rate rose from {_pct(previous_point.pass_rate)} to {_pct(latest.pass_rate)}."
        severity = SEVERITY_GOOD
    return Insight(
        "config_change", severity, "The latest run followed a config change",
        f"Changed: {changes}. {effect}",
        "Rule: when the latest run's config fingerprint differs from the previous run's, list the "
        "settings that differ and report the pass-rate movement across that boundary. Correlation "
        "with the change, not proof of causation.",
    )


def advisory_disagreement(model: DashboardModel) -> Optional[Insight]:
    """Passing cases with a failing advisory check: green on the gate, off the reference."""
    hits: List[str] = []
    counter: Counter = Counter()
    for row in model.rows:
        if not row.passed:
            continue
        for check in row.case.get("checks") or []:
            meta = check.get("metadata") or {}
            advisory = bool(meta.get("advisory")) or any(
                c.name == check.get("name") and c.advisory for c in model.checks
            )
            if advisory and check.get("applicable", True) and not check.get("passed"):
                hits.append(row.id)
                counter[str(check.get("name"))] += 1
                break
    if not hits:
        return None
    top = counter.most_common(1)[0]
    return Insight(
        "advisory", SEVERITY_INFO,
        f"{len(hits)} passing case(s) fail an advisory check",
        f"{_join(hits)} pass every required check but fail at least one advisory check "
        f"(most often {top[0]}). They clear the gate; they may still be worth a look.",
        "Rule: passing cases with any applicable advisory check (one not in evaluation.required_checks) "
        "that failed. Advisory checks never gate, by design, so this is the only place they surface.",
        hits,
    )


def nondeterminism_warning(model: DashboardModel) -> Optional[Insight]:
    nondet = [p for p in model.points if not p.deterministic]
    if not nondet:
        return None
    return Insight(
        "nondeterministic", SEVERITY_WARN,
        f"{len(nondet)} of {len(model.points)} stored runs used a nondeterministic provider",
        "Trend movements that include those runs are partly noise. Compare like with like: "
        "stub runs against stub runs, live runs against repeated live runs.",
        "Rule: any stored run with deterministic = false.",
    )


RULES = (
    largest_drops,
    attribution,
    worst_category,
    most_common_failing_check,
    flaky_cases,
    pass_rate_trend,
    latest_config_change,
    advisory_disagreement,
    nondeterminism_warning,
)

_SEVERITY_ORDER = {SEVERITY_BAD: 0, SEVERITY_WARN: 1, SEVERITY_INFO: 2, SEVERITY_GOOD: 3}


def generate_insights(model: DashboardModel) -> List[Insight]:
    """Run every rule and return the findings, worst first (stable within a severity)."""
    findings = [insight for rule in RULES for insight in [rule(model)] if insight is not None]
    findings.sort(key=lambda i: _SEVERITY_ORDER.get(i.severity, 9))
    return findings
