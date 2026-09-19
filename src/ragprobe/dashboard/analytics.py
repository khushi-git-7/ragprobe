"""Dashboard data model: from a list of results documents to numbers.

Everything here is a pure function of the stored JSON. Nothing renders, nothing
reads files. The model is what the insights engine reasons over and what the HTML
layer draws, and it is the layer the tests pin to hand-computed values.

Two conventions worth knowing:

* Retrieval metrics are stored under ``k``-suffixed names (``precision@3``). Runs
  in a history can have different ``top_k``, so trends are keyed by the metric
  *family* (``precision``) and labelled with the latest run's actual key.
* "Previous run" means the run immediately before the latest one in the history,
  whatever its configuration. The KPI delta is therefore "what changed since last
  time", not "what changed since the baseline" - the regression panel covers that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ragprobe.regression.diff import DEFAULT_EPSILON, DiffReport, diff_runs

#: Metric families in display order, with the prefix used in the results file.
RETRIEVAL_FAMILIES: Tuple[Tuple[str, str, str], ...] = (
    ("hit_rate", "hit_rate@", "Hit rate"),
    ("mrr", "mrr", "MRR"),
    ("precision", "precision@", "Precision"),
    ("recall", "recall@", "Recall"),
)

ATTRIBUTION_RETRIEVAL = "retrieval"
ATTRIBUTION_GENERATION = "generation"
ATTRIBUTION_REFUSAL = "refusal"
ATTRIBUTION_ERROR = "error"
ATTRIBUTION_MIXED = "mixed"
ATTRIBUTION_UNKNOWN = "unknown"


# ------------------------------------------------------------------ small utils


def flatten(mapping: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    """``{"a": {"b": 1}}`` -> ``{"a.b": 1}``. Lists are kept as values."""
    flat: Dict[str, Any] = {}
    for key, value in (mapping or {}).items():
        dotted = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, f"{dotted}."))
        else:
            flat[dotted] = value
    return flat


def config_changes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> List[str]:
    """Human-readable list of settings that differ, e.g. ``generation.max_sentences: 2 -> 1``."""
    before, after = flatten(previous), flatten(current)
    changes: List[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changes.append(f"{key}: {before.get(key, '-')} -> {after.get(key, '-')}")
    return changes


def normalise_retrieval(retrieval: Mapping[str, Any]) -> Dict[str, Tuple[str, Optional[float]]]:
    """Map metric families to ``(actual key, value)`` for one retrieval dict."""
    out: Dict[str, Tuple[str, Optional[float]]] = {}
    for family, prefix, _label in RETRIEVAL_FAMILIES:
        for key, value in (retrieval or {}).items():
            if str(key).startswith(prefix):
                out[family] = (str(key), value)
                break
    return out


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    defined = [float(v) for v in values if v is not None]
    return sum(defined) / len(defined) if defined else None


# ------------------------------------------------------------------ run points


@dataclass
class RunPoint:
    """One run reduced to what a trend line needs."""

    index: int
    started_at: str
    config_fingerprint: str
    dataset_fingerprint: str
    provider: str
    deterministic: bool
    total: int
    passed: int
    failed: int
    pass_rate: Optional[float]
    mean_score: Optional[float]
    #: family -> value (``None`` when the run did not define it)
    retrieval: Dict[str, Optional[float]] = field(default_factory=dict)
    #: family -> the key as stored, e.g. ``precision@3``
    retrieval_keys: Dict[str, str] = field(default_factory=dict)
    config_changed: bool = False
    dataset_changed: bool = False
    changes: List[str] = field(default_factory=list)
    label: str = ""
    source: str = ""

    def metric(self, key: str) -> Optional[float]:
        if key == "pass_rate":
            return self.pass_rate
        if key == "mean_score":
            return self.mean_score
        return self.retrieval.get(key)


def build_run_points(runs: Sequence[Mapping[str, Any]], sources: Optional[Sequence[str]] = None) -> List[RunPoint]:
    """Reduce each run (oldest first) to a :class:`RunPoint`, marking config and dataset changes."""
    points: List[RunPoint] = []
    previous: Optional[Mapping[str, Any]] = None
    for index, run in enumerate(runs):
        summary = run.get("summary") or {}
        retrieval = normalise_retrieval(summary.get("retrieval") or {})
        point = RunPoint(
            index=index,
            started_at=str(run.get("started_at") or ""),
            config_fingerprint=str(run.get("config_fingerprint") or ""),
            dataset_fingerprint=str(run.get("dataset_fingerprint") or ""),
            provider=str(run.get("provider") or ""),
            deterministic=bool(run.get("deterministic", True)),
            total=int(summary.get("total") or 0),
            passed=int(summary.get("passed") or 0),
            failed=int(summary.get("failed") or 0),
            pass_rate=summary.get("pass_rate"),
            mean_score=summary.get("mean_score"),
            retrieval={family: value for family, (_key, value) in retrieval.items()},
            retrieval_keys={family: key for family, (key, _value) in retrieval.items()},
            label=f"#{index + 1}",
            source=str(sources[index]) if sources and index < len(sources) else "",
        )
        if previous is not None:
            point.config_changed = point.config_fingerprint != str(previous.get("config_fingerprint") or "")
            point.dataset_changed = point.dataset_fingerprint != str(previous.get("dataset_fingerprint") or "")
            if point.config_changed:
                point.changes = config_changes(previous.get("config") or {}, run.get("config") or {})
                if not point.changes:
                    point.changes = ["config fingerprint changed (details not recorded)"]
        points.append(point)
        previous = run
    return points


# ------------------------------------------------------------------ KPIs


@dataclass
class Kpi:
    """One overview tile: the latest value, the change since the previous run, the series."""

    key: str
    label: str
    value: Optional[float]
    previous: Optional[float]
    delta: Optional[float]
    series: List[Optional[float]]
    #: "percent", "score" or "count"
    fmt: str
    #: Whether an increase is good. Every KPI here goes up when things improve.
    higher_is_better: bool = True
    note: str = ""

    @property
    def direction(self) -> str:
        """``up`` / ``down`` / ``flat`` / ``none``."""
        if self.delta is None:
            return "none"
        if abs(self.delta) < 1e-9:
            return "flat"
        return "up" if self.delta > 0 else "down"

    @property
    def sentiment(self) -> str:
        """``good`` / ``bad`` / ``neutral``, taking the metric's polarity into account."""
        direction = self.direction
        if direction in ("flat", "none") or self.fmt == "count":
            # A change in how many cases ran is information, not a verdict.
            return "neutral"
        good = (direction == "up") == self.higher_is_better
        return "good" if good else "bad"


def _delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None:
        return None
    return float(current) - float(previous)


def kpi_tiles(points: Sequence[RunPoint]) -> List[Kpi]:
    """The overview tiles: each headline metric on the latest run, its delta and its series."""
    if not points:
        return []
    latest = points[-1]
    previous = points[-2] if len(points) > 1 else None

    def series(key: str) -> List[Optional[float]]:
        return [point.metric(key) for point in points]

    tiles = [
        Kpi("pass_rate", "Pass rate", latest.pass_rate, previous.pass_rate if previous else None,
            _delta(latest.pass_rate, previous.pass_rate if previous else None), series("pass_rate"), "percent"),
        Kpi("mean_score", "Mean score", latest.mean_score, previous.mean_score if previous else None,
            _delta(latest.mean_score, previous.mean_score if previous else None), series("mean_score"), "score"),
    ]
    for family, _prefix, label in RETRIEVAL_FAMILIES:
        key = latest.retrieval_keys.get(family, family)
        current_value = latest.retrieval.get(family)
        prev_value = previous.retrieval.get(family) if previous else None
        note = ""
        if previous and family in previous.retrieval_keys and previous.retrieval_keys[family] != key:
            note = f"k changed ({previous.retrieval_keys[family]} -> {key})"
        tile_label = f"{label}@{key.split('@', 1)[1]}" if "@" in key else label
        tiles.append(
            Kpi(family, tile_label, current_value, prev_value, _delta(current_value, prev_value),
                series(family), "score", note=note)
        )
    tiles.append(
        Kpi("cases", "Cases run", float(latest.total), float(previous.total) if previous else None,
            _delta(float(latest.total), float(previous.total) if previous else None),
            [float(point.total) for point in points], "count",
            note=f"{latest.passed} passed, {latest.failed} failed")
    )
    return tiles


# ------------------------------------------------------------------ breakdowns


@dataclass
class CategoryStat:
    name: str
    total: int
    passed: int
    pass_rate: float
    mean_score: float
    #: pass rate on the previous run, when that run had the category
    previous_pass_rate: Optional[float] = None

    @property
    def failed(self) -> int:
        return self.total - self.passed


def category_breakdown(run: Mapping[str, Any], previous: Optional[Mapping[str, Any]] = None) -> List[CategoryStat]:
    """Per-category stats, worst pass rate first (this is a triage view)."""
    stats: List[CategoryStat] = []
    previous_categories = ((previous or {}).get("summary") or {}).get("by_category") or {}
    for name, bucket in ((run.get("summary") or {}).get("by_category") or {}).items():
        total = int(bucket.get("total") or 0)
        passed = int(bucket.get("passed") or 0)
        stats.append(
            CategoryStat(
                name=str(name),
                total=total,
                passed=passed,
                pass_rate=float(bucket.get("pass_rate") if bucket.get("pass_rate") is not None else (passed / total if total else 0.0)),
                mean_score=float(bucket.get("mean_score") or 0.0),
                previous_pass_rate=(previous_categories.get(name) or {}).get("pass_rate"),
            )
        )
    stats.sort(key=lambda s: (s.pass_rate, s.mean_score, s.name))
    return stats


@dataclass
class CheckOutcome:
    name: str
    passed: int
    failed: int
    skipped: int
    advisory: bool

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped

    @property
    def fail_rate(self) -> Optional[float]:
        applicable = self.passed + self.failed
        return self.failed / applicable if applicable else None


def check_outcomes(run: Mapping[str, Any]) -> List[CheckOutcome]:
    """Pass/fail/skip counts per check type, most failures first."""
    buckets: Dict[str, CheckOutcome] = {}
    order: List[str] = []
    required = set(((run.get("config") or {}).get("evaluation") or {}).get("required_checks") or [])
    for case in run.get("cases") or []:
        for check in case.get("checks") or []:
            name = str(check.get("name"))
            if name not in buckets:
                advisory = bool((check.get("metadata") or {}).get("advisory")) or (
                    bool(required) and name not in required
                )
                buckets[name] = CheckOutcome(name, 0, 0, 0, advisory)
                order.append(name)
            outcome = buckets[name]
            if not check.get("applicable", True):
                outcome.skipped += 1
            elif check.get("passed"):
                outcome.passed += 1
            else:
                outcome.failed += 1
    outcomes = [buckets[name] for name in order]
    outcomes.sort(key=lambda o: (-o.failed, o.advisory, o.name))
    return outcomes


@dataclass
class HistogramBin:
    low: float
    high: float
    count: int
    cases: List[str] = field(default_factory=list)


def score_histogram(run: Mapping[str, Any], bins: int = 10) -> List[HistogramBin]:
    """Case scores bucketed into equal-width bins on [0, 1]; 1.0 lands in the top bin."""
    if bins <= 0:
        raise ValueError("bins must be positive")
    width = 1.0 / bins
    result = [HistogramBin(round(i * width, 4), round((i + 1) * width, 4), 0) for i in range(bins)]
    for case in run.get("cases") or []:
        score = case.get("score")
        if score is None:
            continue
        score = min(max(float(score), 0.0), 1.0)
        index = min(int(score / width), bins - 1)
        result[index].count += 1
        result[index].cases.append(str(case.get("id")))
    return result


# ------------------------------------------------------------------ per-case history


@dataclass
class CaseSnapshot:
    passed: bool
    score: float


@dataclass
class CaseHistory:
    id: str
    #: one entry per run, ``None`` when the case was absent from that run
    snapshots: List[Optional[CaseSnapshot]]
    #: pass/fail flips between consecutive runs where the config was identical
    flips_same_config: int = 0
    #: pass/fail flips between consecutive runs where the config changed
    flips_config_change: int = 0

    @property
    def scores(self) -> List[Optional[float]]:
        return [snap.score if snap else None for snap in self.snapshots]

    @property
    def flips(self) -> int:
        return self.flips_same_config + self.flips_config_change

    @property
    def runs_present(self) -> int:
        return sum(1 for snap in self.snapshots if snap is not None)


def case_histories(runs: Sequence[Mapping[str, Any]], points: Sequence[RunPoint]) -> Dict[str, CaseHistory]:
    """Per-case score/pass series across the history, plus flip counts.

    A flip is counted only between *consecutive runs in which the case exists*.
    Flips are split by whether the configuration changed between those two runs,
    because a case that flips under an identical config is nondeterministic
    (flaky), while one that flips when the prompt changes is merely sensitive.
    """
    ids: List[str] = []
    for run in runs:
        for case in run.get("cases") or []:
            case_id = str(case.get("id"))
            if case_id not in ids:
                ids.append(case_id)

    indexed = [{str(c.get("id")): c for c in (run.get("cases") or [])} for run in runs]
    histories: Dict[str, CaseHistory] = {}
    for case_id in ids:
        snapshots: List[Optional[CaseSnapshot]] = []
        for cases in indexed:
            case = cases.get(case_id)
            snapshots.append(
                CaseSnapshot(bool(case.get("passed")), float(case.get("score") or 0.0)) if case else None
            )
        history = CaseHistory(case_id, snapshots)
        last_seen: Optional[int] = None
        for index, snap in enumerate(snapshots):
            if snap is None:
                continue
            if last_seen is not None and snapshots[last_seen].passed != snap.passed:  # type: ignore[union-attr]
                same_config = all(
                    not points[i].config_changed for i in range(last_seen + 1, index + 1)
                ) if index < len(points) else True
                if same_config:
                    history.flips_same_config += 1
                else:
                    history.flips_config_change += 1
            last_seen = index
        histories[case_id] = history
    return histories


# ------------------------------------------------------------------ attribution


@dataclass
class Attribution:
    kind: str
    reason: str


def attribute_failure(case: Mapping[str, Any]) -> Attribution:
    """Decide which stage a failing case most plausibly failed in.

    The rule is deliberately simple and stated in the reason:

    * an exception -> ``error``
    * a refusal case (no expected chunks) -> ``refusal`` (the policy, not retrieval)
    * every expected chunk retrieved (recall 1.0) but the case still fails ->
      ``generation``: the evidence was on the table and the answer was still wrong
    * no expected chunk retrieved (hit rate 0) -> ``retrieval``: the generator
      never saw the evidence, so its output is not the first thing to fix
    * anything in between -> ``mixed``
    * no retrieval metrics recorded at all -> ``unknown``, rather than a guess
    """
    if case.get("error"):
        return Attribution(ATTRIBUTION_ERROR, "the case raised an exception before evaluation")
    failing = [str(name) for name in case.get("failed_checks") or []]
    if not failing:
        failing = [
            str(check.get("name"))
            for check in case.get("checks") or []
            if check.get("applicable", True) and not check.get("passed", True)
        ]
    failing_text = ", ".join(failing) if failing else "no recorded check"
    if not case.get("expected_chunks"):
        return Attribution(
            ATTRIBUTION_REFUSAL,
            f"no expected chunks, so this is a refusal-policy case; failing: {failing_text}",
        )
    retrieval = case.get("retrieval") or {}
    recall = next((v for k, v in retrieval.items() if str(k).startswith("recall@")), None)
    hit = next((v for k, v in retrieval.items() if str(k).startswith("hit_rate@")), None)
    if recall is not None and float(recall) >= 1.0:
        return Attribution(
            ATTRIBUTION_GENERATION,
            f"every expected chunk was retrieved (recall 1.0) yet the case fails on {failing_text}",
        )
    if hit is not None and float(hit) <= 0.0:
        return Attribution(
            ATTRIBUTION_RETRIEVAL,
            "no expected chunk was retrieved (hit rate 0), so the generator never saw the evidence",
        )
    if recall is None and hit is None:
        return Attribution(
            ATTRIBUTION_UNKNOWN,
            f"no retrieval metrics were recorded for this case; failing: {failing_text}",
        )
    return Attribution(
        ATTRIBUTION_MIXED,
        f"retrieval was partial (recall {recall if recall is not None else 'n/a'}); failing: {failing_text}",
    )


# ------------------------------------------------------------------ case rows


@dataclass
class CaseRow:
    """Everything the cases table needs for one case in the latest run."""

    case: Dict[str, Any]
    history: CaseHistory
    previous_score: Optional[float]
    score_delta_prev: Optional[float]
    #: status versus the comparison run: regressed / improved / degraded / flat / new / removed
    change_status: Optional[str]
    attribution: Optional[Attribution]

    @property
    def id(self) -> str:
        return str(self.case.get("id"))

    @property
    def passed(self) -> bool:
        return bool(self.case.get("passed"))


# ------------------------------------------------------------------ the model


@dataclass
class DashboardModel:
    """Everything the page shows, computed once from the stored runs and an optional baseline."""

    runs: List[Dict[str, Any]]
    points: List[RunPoint]
    kpis: List[Kpi]
    categories: List[CategoryStat]
    checks: List[CheckOutcome]
    histogram: List[HistogramBin]
    case_histories: Dict[str, CaseHistory]
    rows: List[CaseRow]
    diff: Optional[DiffReport]
    gate: Optional[Any]
    #: what the cases table's regressed/improved chips compare against
    comparison_label: str
    baseline: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    epsilon: float = DEFAULT_EPSILON

    @property
    def latest(self) -> Dict[str, Any]:
        return self.runs[-1]

    @property
    def previous(self) -> Optional[Dict[str, Any]]:
        return self.runs[-2] if len(self.runs) > 1 else None

    @property
    def latest_point(self) -> RunPoint:
        return self.points[-1]

    def trend(self, key: str) -> List[Optional[float]]:
        return [point.metric(key) for point in self.points]

    def retrieval_key(self, family: str) -> str:
        return self.latest_point.retrieval_keys.get(family, family)


def build_model(
    runs: Sequence[Mapping[str, Any]],
    baseline: Optional[Mapping[str, Any]] = None,
    epsilon: float = DEFAULT_EPSILON,
    sources: Optional[Sequence[str]] = None,
    warnings: Optional[Sequence[str]] = None,
) -> DashboardModel:
    """Assemble the whole dashboard model from stored runs (oldest first)."""
    if not runs:
        raise ValueError("at least one run is required to build a dashboard")
    runs = [dict(run) for run in runs]
    points = build_run_points(runs, sources)
    latest, previous = runs[-1], (runs[-2] if len(runs) > 1 else None)
    histories = case_histories(runs, points)

    diff: Optional[DiffReport] = None
    gate = None
    comparison_label = "previous run"
    change_by_id: Dict[str, str] = {}
    if baseline is not None:
        diff = diff_runs(baseline, latest, epsilon=epsilon)
        gate = diff.gate()
        comparison_label = "baseline"
        change_by_id = {case.id: case.status for case in diff.cases}
    elif previous is not None:
        change_by_id = {case.id: case.status for case in diff_runs(previous, latest, epsilon=epsilon).cases}
    else:
        comparison_label = ""

    previous_cases = {str(c.get("id")): c for c in (previous.get("cases") if previous else []) or []}
    rows: List[CaseRow] = []
    for case in latest.get("cases") or []:
        case_id = str(case.get("id"))
        prev_case = previous_cases.get(case_id)
        prev_score = float(prev_case.get("score") or 0.0) if prev_case else None
        rows.append(
            CaseRow(
                case=dict(case),
                history=histories[case_id],
                previous_score=prev_score,
                score_delta_prev=_delta(case.get("score"), prev_score),
                change_status=change_by_id.get(case_id),
                attribution=attribute_failure(case) if not case.get("passed") else None,
            )
        )

    return DashboardModel(
        runs=runs,
        points=points,
        kpis=kpi_tiles(points),
        categories=category_breakdown(latest, previous),
        checks=check_outcomes(latest),
        histogram=score_histogram(latest),
        case_histories=histories,
        rows=rows,
        diff=diff,
        gate=gate,
        comparison_label=comparison_label,
        baseline=dict(baseline) if baseline is not None else None,
        warnings=list(warnings or []),
        epsilon=epsilon,
    )
