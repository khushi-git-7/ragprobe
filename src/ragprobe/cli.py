"""Command line interface.

``argparse`` rather than a CLI framework, to keep the base install dependency-free.

Exit codes are part of the contract, because CI consumes them:

======  ==========================================================
  0     success, and any gate that ran passed
  1     the run completed but a gate failed (regressions, or the
        pass rate / score threshold was breached)
  2     usage error, bad config, or a missing file
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
from ragprobe.evaluation.dataset import DatasetError, load_dataset
from ragprobe.evaluation.runner import RunResult, run_suite
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


# --------------------------------------------------------------------- helpers


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{label} not found: {path}\n"
            f"Hint: create one with 'ragprobe baseline'."
        )
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def _execute_run(args: argparse.Namespace) -> RunResult:
    config = _build_config(args)
    base_dir = Path(args.root) if getattr(args, "root", None) else Path.cwd()
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
    return _execute_run(args).to_dict()


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
            "  2  usage error, bad config, or missing file\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"ragprobe {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run ------------------------------------------------------------------
    run_parser = subparsers.add_parser("run", help="run the golden set and write results")
    _add_pipeline_args(run_parser)
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

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, DatasetError, CorpusError, FileNotFoundError) as exc:
        # Expected, actionable failures: print the message, not a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
