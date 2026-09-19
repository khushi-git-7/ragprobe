"""Command line interface.

``argparse`` rather than a CLI framework, to keep the base install dependency-free.

Exit codes are part of the contract, because CI consumes them:

======  ==========================================================
  0     success, and any gate that ran passed
  1     the run completed but a gate failed (regressions, or the
        pass rate / score threshold was breached)
  2     usage error, bad config, or a missing or unusable file
======  ==========================================================

The distinction between 1 and 2 matters: exit 1 means "your change broke something",
exit 2 means "the harness could not run". Collapsing both into a nonzero exit makes
a broken config look like a regression.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ragprobe import __version__
from ragprobe.config import ConfigError, ProbeConfig
from ragprobe.dashboard import build_model, write_dashboard
from ragprobe.evaluation.dataset import DatasetError, load_dataset
from ragprobe.evaluation.runner import RunResult, run_suite
from ragprobe.history import DEFAULT_HISTORY_DIR, append_run, is_valid_run, load_history, merge_current
from ragprobe.pipeline.loader import CorpusError
from ragprobe.regression.diff import DEFAULT_EPSILON, DiffReport, diff_runs
from ragprobe.reporting.html import write_report
from ragprobe.reporting.terminal import render_diff_summary, render_gate, render_run_summary

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2

DEFAULT_RESULTS = "reports/results.json"
DEFAULT_BASELINE = "baselines/baseline.json"
DEFAULT_HTML = "reports/report.html"
DEFAULT_DIFF_JSON = "reports/diff.json"
DEFAULT_DASHBOARD = "reports/dashboard.html"


# --------------------------------------------------------------------- helpers


def _positive_int(text: str) -> int:
    """argparse type for counts where zero would silently mean "no limit"."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


class InputError(Exception):
    """A results or baseline file that exists but cannot be used (exit code 2)."""


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    """Load a results/baseline document, or raise an actionable error.

    Every file this reads is either produced by RAGProbe or named explicitly by
    the user, so a file that is not a results document is a usage error, not a
    traceback and not something to render an empty page from.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{label} not found: {path}\n"
            f"Hint: create one with 'ragprobe baseline'."
        )
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except ValueError as exc:
        raise InputError(f"{label} is not valid JSON: {path}: {exc}") from None
    if not is_valid_run(payload):
        raise InputError(f"{label} is not a RAGProbe results document: {path}")
    return payload


def _build_config(args: argparse.Namespace) -> ProbeConfig:
    config = ProbeConfig.load(Path(args.config) if getattr(args, "config", None) else None)
    overrides: Dict[str, Any] = {}
    if getattr(args, "corpus", None):
        overrides["corpus_dir"] = args.corpus
    if getattr(args, "dataset", None):
        overrides["dataset_path"] = args.dataset
    if getattr(args, "top_k", None) is not None:
        overrides["retrieval.top_k"] = args.top_k
    if getattr(args, "provider", None):
        overrides["generation.provider"] = args.provider
    if getattr(args, "prompt_version", None):
        overrides["generation.prompt_version"] = args.prompt_version
    if getattr(args, "max_sentences", None) is not None:
        overrides["generation.max_sentences"] = args.max_sentences
    if getattr(args, "no_judge", False):
        overrides["evaluation.judge_enabled"] = False
    if overrides:
        config = config.apply_overrides(overrides)
    return config


def _base_dir(args: argparse.Namespace) -> Path:
    """``--root`` if given, else the working directory as a relative path.

    Relative rather than ``Path.cwd()`` so every path the CLI prints (results,
    history, baseline) keeps the short form the user typed.
    """
    return Path(args.root) if getattr(args, "root", None) else Path(".")


def _history_dir(args: argparse.Namespace) -> Optional[Path]:
    """Where to append this run, or ``None`` when history is disabled.

    A relative ``--history-dir`` resolves against ``--root`` (like the dataset and
    corpus paths do), so the history lives with the project it describes and a
    test running against a scratch copy never writes into the real one.
    """
    if getattr(args, "no_history", False):
        return None
    path = Path(getattr(args, "history_dir", None) or DEFAULT_HISTORY_DIR)
    return path if path.is_absolute() else _base_dir(args) / path


def _record_history(args: argparse.Namespace, payload: Mapping[str, Any]) -> Optional[Path]:
    history_dir = _history_dir(args)
    if history_dir is None:
        return None
    return append_run(history_dir, payload)


def _execute_run(args: argparse.Namespace) -> RunResult:
    config = _build_config(args)
    base_dir = _base_dir(args)
    dataset_path = base_dir / config.dataset_path
    cases = load_dataset(dataset_path)

    progress = None
    if not args.quiet:
        def progress(index: int, total: int, case) -> None:  # noqa: ANN001
            print(f"  [{index}/{total}] {case.id}", file=sys.stderr)
        print(
            f"RAGProbe {__version__}: running {len(cases)} case(s) "
            f"from {dataset_path}",
            file=sys.stderr,
        )

    return run_suite(cases, config, base_dir=base_dir, progress=progress)


# -------------------------------------------------------------------- commands


def cmd_run(args: argparse.Namespace) -> int:
    """Run the suite, write results, optionally gate on absolute thresholds."""
    result = _execute_run(args)
    payload = result.to_dict()

    results_path = _write_json(Path(args.out), payload)
    print(render_run_summary(payload))
    print(f"  results -> {results_path}")
    history_path = _record_history(args, payload)
    if history_path is not None:
        print(f"  history -> {history_path}")

    if args.html:
        html_path = write_report(Path(args.html), payload, title="RAGProbe run report")
        print(f"  report  -> {html_path}")

    # Absolute thresholds. These are distinct from the regression gate: they ask
    # "is the system good enough?", not "did it get worse?". A project usually wants
    # both, because a suite can be uniformly mediocre without ever regressing.
    failures: List[str] = []
    if args.fail_under is not None and result.pass_rate < args.fail_under:
        failures.append(
            f"pass rate {result.pass_rate:.1%} is below --fail-under {args.fail_under:.1%}"
        )
    if args.fail_under_score is not None and result.mean_score < args.fail_under_score:
        failures.append(
            f"mean score {result.mean_score:.3f} is below "
            f"--fail-under-score {args.fail_under_score:.3f}"
        )
    if failures:
        print()
        for reason in failures:
            print(f"  THRESHOLD FAILED: {reason}")
        return EXIT_GATE_FAILED
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    """Record a baseline: either from an existing results file, or by running now."""
    if args.from_results:
        payload = _read_json(Path(args.from_results), "results file")
        source = str(args.from_results)
    else:
        result = _execute_run(args)
        payload = result.to_dict()
        source = "a fresh run"

    if not payload.get("deterministic", False) and not args.allow_nondeterministic:
        print(
            "  REFUSED: this run used a nondeterministic provider, so it is not a\n"
            "  usable baseline - re-running the same commit would show phantom\n"
            "  regressions. Record baselines in stub mode, or pass\n"
            "  --allow-nondeterministic if you understand the consequences.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    baseline_path = _write_json(Path(args.out), payload)
    summary = payload.get("summary", {})
    print(render_run_summary(payload))
    print(f"  baseline recorded from {source} -> {baseline_path}")
    print(
        f"  {summary.get('passed', 0)}/{summary.get('total', 0)} passing at "
        f"config {payload.get('config_fingerprint')}"
    )
    print("  Commit this file. It is the contract your next prompt change is tested against.")
    return EXIT_OK


def _load_or_run_current(args: argparse.Namespace) -> Dict[str, Any]:
    if args.current:
        return _read_json(Path(args.current), "current results file")
    payload = _execute_run(args).to_dict()
    history_path = _record_history(args, payload)
    if history_path is not None:
        print(f"  history -> {history_path}", file=sys.stderr)
    return payload


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare a run against the baseline and apply the CI gate."""
    baseline = _read_json(Path(args.baseline), "baseline")
    current = _load_or_run_current(args)

    report: DiffReport = diff_runs(baseline, current, epsilon=args.epsilon)
    gate = report.gate(
        max_regressions=args.max_regressions,
        max_degraded=args.max_degraded,
        min_pass_rate=args.min_pass_rate,
        max_mean_score_drop=args.max_score_drop,
        fail_on_removed=not args.allow_removed,
    )

    print(render_diff_summary(report))
    print(render_gate(gate))

    if args.json:
        diff_path = _write_json(Path(args.json), {**report.to_dict(), "gate": gate.to_dict()})
        print(f"  diff    -> {diff_path}")
    if args.html:
        html_path = write_report(
            Path(args.html), current, diff=report, gate=gate, title="RAGProbe regression report"
        )
        print(f"  report  -> {html_path}")
    if args.save_current:
        saved = _write_json(Path(args.save_current), current)
        print(f"  results -> {saved}")

    return EXIT_OK if gate.ok else EXIT_GATE_FAILED


def cmd_report(args: argparse.Namespace) -> int:
    """Render an HTML report from stored JSON, without re-running anything."""
    current = _read_json(Path(args.results), "results file")
    report = None
    gate = None
    if args.baseline:
        baseline = _read_json(Path(args.baseline), "baseline")
        report = diff_runs(baseline, current, epsilon=args.epsilon)
        gate = report.gate(max_regressions=args.max_regressions)
    html_path = write_report(Path(args.out), current, diff=report, gate=gate, title=args.title)
    print(f"  report  -> {html_path}")
    return EXIT_OK


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Render the analytics dashboard from the run history (plus an optional baseline)."""
    history_dir = _history_dir(args) or Path(DEFAULT_HISTORY_DIR)
    history = load_history(history_dir)
    if args.results:
        current = _read_json(Path(args.results), "results file")
        merge_current(history, current, Path(args.results))
    if args.limit is not None:
        # After the merge, so "the most recent N" counts the --results file too.
        history.entries = history.entries[-args.limit:]
    if not history.entries:
        raise FileNotFoundError(
            f"no runs found in {history_dir}\n"
            f"Hint: 'ragprobe run' appends each run there, or pass --results FILE."
        )

    baseline = None
    baseline_path = Path(args.baseline) if args.baseline else _base_dir(args) / DEFAULT_BASELINE
    if args.baseline or baseline_path.exists():
        baseline = _read_json(baseline_path, "baseline")

    warnings: List[str] = [f"Skipped {item}" for item in history.skipped]
    model = build_model(
        history.runs,
        baseline=baseline,
        epsilon=args.epsilon,
        sources=[str(entry.path) for entry in history.entries],
        warnings=warnings,
    )
    out = write_dashboard(Path(args.out), model, title=args.title)
    latest = model.latest_point
    print(f"  dashboard -> {out}")
    print(
        f"  {len(model.points)} run(s) from {history_dir}"
        + (f", baseline {baseline_path}" if baseline is not None else ", no baseline")
    )
    if latest.pass_rate is not None and latest.mean_score is not None:
        print(f"  latest: pass rate {latest.pass_rate:.1%}, mean score {latest.mean_score:.3f}")
    for warning in warnings:
        print(f"  WARNING: {warning}", file=sys.stderr)
    return EXIT_OK


# --------------------------------------------------------------------- parsing


def _add_pipeline_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="path to a ragprobe.yaml config file")
    parser.add_argument("--root", help="project root that relative paths resolve against")
    parser.add_argument("--corpus", help="override corpus_dir")
    parser.add_argument("--dataset", help="override dataset_path")
    parser.add_argument("--top-k", type=int, help="override retrieval.top_k")
    parser.add_argument(
        "--provider",
        choices=["stub", "anthropic"],
        help="override generation.provider (default: stub, no API key required)",
    )
    parser.add_argument("--prompt-version", help="override generation.prompt_version")
    parser.add_argument(
        "--max-sentences", type=int, help="override generation.max_sentences"
    )
    parser.add_argument(
        "--no-judge", action="store_true", help="skip the LLM-as-judge evaluator"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")


def _add_history_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--history-dir", default=DEFAULT_HISTORY_DIR, metavar="DIR",
        help=f"append this run's results here for 'ragprobe dashboard' "
        f"(default: {DEFAULT_HISTORY_DIR}, relative to --root)",
    )
    parser.add_argument(
        "--no-history", action="store_true", help="do not record this run in the history directory"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ragprobe",
        description=(
            "Evaluation and regression-testing harness for RAG pipelines and LLM features. "
            "Runs offline against a deterministic stub provider by default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exit codes:\n"
            "  0  success\n"
            "  1  a gate failed (regressions or threshold breach)\n"
            "  2  usage error, bad config, or a missing or unusable file\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"ragprobe {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run ------------------------------------------------------------------
    run_parser = subparsers.add_parser("run", help="run the golden set and write results")
    _add_pipeline_args(run_parser)
    _add_history_args(run_parser)
    run_parser.add_argument("--out", default=DEFAULT_RESULTS, help="results JSON output path")
    run_parser.add_argument("--html", nargs="?", const=DEFAULT_HTML, help="also write an HTML report")
    run_parser.add_argument(
        "--fail-under", type=float, metavar="RATE",
        help="exit 1 if the pass rate falls below this fraction (e.g. 0.9)",
    )
    run_parser.add_argument(
        "--fail-under-score", type=float, metavar="SCORE",
        help="exit 1 if the mean case score falls below this value",
    )
    run_parser.set_defaults(func=cmd_run)

    # baseline -------------------------------------------------------------
    baseline_parser = subparsers.add_parser(
        "baseline", help="record the current behaviour as the regression baseline"
    )
    _add_pipeline_args(baseline_parser)
    baseline_parser.add_argument("--out", default=DEFAULT_BASELINE, help="baseline output path")
    baseline_parser.add_argument(
        "--from-results", help="promote an existing results JSON instead of re-running"
    )
    baseline_parser.add_argument(
        "--allow-nondeterministic", action="store_true",
        help="permit recording a baseline from a live provider (not recommended)",
    )
    baseline_parser.set_defaults(func=cmd_baseline)

    # diff -----------------------------------------------------------------
    diff_parser = subparsers.add_parser(
        "diff", help="compare a run against the baseline and gate the build"
    )
    _add_pipeline_args(diff_parser)
    _add_history_args(diff_parser)
    diff_parser.add_argument("--baseline", default=DEFAULT_BASELINE, help="baseline JSON path")
    diff_parser.add_argument(
        "--current", help="results JSON to compare (default: run the suite now)"
    )
    diff_parser.add_argument("--save-current", help="write the freshly produced results here")
    diff_parser.add_argument("--json", nargs="?", const=DEFAULT_DIFF_JSON, help="write the diff as JSON")
    diff_parser.add_argument("--html", nargs="?", const=DEFAULT_HTML, help="write an HTML diff report")
    diff_parser.add_argument(
        "--max-regressions", type=int, default=0,
        help="number of regressed cases tolerated before failing (default: 0)",
    )
    diff_parser.add_argument(
        "--max-degraded", type=int, metavar="N",
        help="also fail if more than N cases dropped in score while still passing "
        "(default: report only)",
    )
    diff_parser.add_argument(
        "--min-pass-rate", type=float, help="fail if the current pass rate is below this"
    )
    diff_parser.add_argument(
        "--max-score-drop", type=float, help="fail if the mean score drops by more than this"
    )
    diff_parser.add_argument(
        "--epsilon", type=float, default=DEFAULT_EPSILON,
        help=f"score change treated as noise (default: {DEFAULT_EPSILON})",
    )
    diff_parser.add_argument(
        "--allow-removed", action="store_true",
        help="do not fail when baseline cases are missing from the run",
    )
    diff_parser.set_defaults(func=cmd_diff)

    # report ---------------------------------------------------------------
    report_parser = subparsers.add_parser(
        "report", help="render an HTML report from stored JSON"
    )
    report_parser.add_argument("--results", default=DEFAULT_RESULTS, help="results JSON path")
    report_parser.add_argument("--baseline", help="also render a diff against this baseline")
    report_parser.add_argument("--out", default=DEFAULT_HTML, help="HTML output path")
    report_parser.add_argument("--title", default="RAGProbe report", help="report title")
    report_parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    report_parser.add_argument("--max-regressions", type=int, default=0)
    report_parser.set_defaults(func=cmd_report)

    # dashboard ------------------------------------------------------------
    dashboard_parser = subparsers.add_parser(
        "dashboard", help="render the analytics dashboard from the run history"
    )
    dashboard_parser.add_argument("--root", help="project root that relative paths resolve against")
    dashboard_parser.add_argument(
        "--history-dir", default=DEFAULT_HISTORY_DIR, metavar="DIR",
        help=f"directory of stored runs (default: {DEFAULT_HISTORY_DIR}, relative to --root)",
    )
    dashboard_parser.add_argument(
        "--results", help="also include this results JSON as the latest run if it is not in the history"
    )
    dashboard_parser.add_argument(
        "--baseline", help=f"baseline JSON for the regression panel (default: {DEFAULT_BASELINE} if present)"
    )
    dashboard_parser.add_argument("--out", default=DEFAULT_DASHBOARD, help="HTML output path")
    dashboard_parser.add_argument("--title", default="RAGProbe Dashboard", help="page title")
    dashboard_parser.add_argument(
        "--limit", type=_positive_int, metavar="N", help="only use the most recent N runs"
    )
    dashboard_parser.add_argument(
        "--epsilon", type=float, default=DEFAULT_EPSILON,
        help=f"score change treated as noise (default: {DEFAULT_EPSILON})",
    )
    dashboard_parser.set_defaults(func=cmd_dashboard)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, DatasetError, CorpusError, FileNotFoundError, InputError) as exc:
        # Expected, actionable failures: print the message, not a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
