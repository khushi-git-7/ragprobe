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
from ragprobe.evaluation.runner import RunResult, rescore, run_suite
from ragprobe.targets import TargetError, parse_target_spec
from ragprobe.history import DEFAULT_HISTORY_DIR, append_run, is_valid_run, load_history, merge_current
from ragprobe.pipeline.loader import CorpusError
from ragprobe.providers import get_provider
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
    if getattr(args, "embedder", None):
        overrides["retrieval.embedder"] = args.embedder
    if getattr(args, "provider", None):
        overrides["generation.provider"] = args.provider
    if getattr(args, "model", None):
        overrides["generation.model"] = args.model
    if getattr(args, "base_url", None):
        overrides["generation.base_url"] = args.base_url
    if getattr(args, "prompt_version", None):
        overrides["generation.prompt_version"] = args.prompt_version
    if getattr(args, "max_sentences", None) is not None:
        overrides["generation.max_sentences"] = args.max_sentences
    if getattr(args, "no_judge", False):
        overrides["evaluation.judge_enabled"] = False
    if getattr(args, "target", None):
        for key, value in parse_target_spec(args.target).items():
            overrides["target." + key] = value
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
        target = config.target
        where = {
            "http": f"against {target.url}",
            "python": f"against {target.entry}",
        }.get(target.kind, "against the built-in pipeline")
        print(
            f"RAGProbe {__version__}: running {len(cases)} case(s) "
            f"from {dataset_path} {where}",
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
    parser.add_argument(
        "--target", metavar="URL|module:name|builtin",
        help="system under test: an HTTP endpoint, a Python entry point, or the built-in "
        "pipeline (default: the 'target' block in the config, else builtin)",
    )
    parser.add_argument("--top-k", type=int, help="override retrieval.top_k")
    parser.add_argument(
        "--embedder", choices=["tfidf", "fastembed", "sentence-transformers"],
        help="override retrieval.embedder (default: tfidf, no extra dependencies)",
    )
    parser.add_argument(
        "--provider",
        choices=["stub", "anthropic", "openai"],
        help="override generation.provider (default: stub, no API key required; "
        "'openai' is any OpenAI-compatible endpoint, e.g. Gemini, Groq, Ollama)",
    )
    parser.add_argument("--model", help="override generation.model")
    parser.add_argument("--base-url", help="override generation.base_url (openai provider)")
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

    # rescore --------------------------------------------------------------
    rescore_parser = subparsers.add_parser(
        "rescore",
        help="re-run the evaluators over the answers saved in a results file (no model calls)",
    )
    rescore_parser.add_argument("--results", default=DEFAULT_RESULTS, help="results JSON to re-score")
    rescore_parser.add_argument("--out", default=DEFAULT_RESULTS, help="where to write the re-scored results")
    rescore_parser.add_argument("--config", help="config to score with (default: the one saved in the results)")
    rescore_parser.add_argument("--root", help="project root that relative paths resolve against")
    _add_history_args(rescore_parser)
    rescore_parser.set_defaults(func=cmd_rescore)

    # import ---------------------------------------------------------------
    import_parser = subparsers.add_parser(
        "import", help="build a corpus and golden set from a public dataset (SQuAD 2.0)"
    )
    import_parser.add_argument("dataset_name", choices=["squad"], help="dataset to import")
    import_parser.add_argument("--out", required=True, metavar="DIR", help="directory to write into")
    import_parser.add_argument("--split", default="dev", choices=["dev", "train"], help="SQuAD split (default: dev)")
    import_parser.add_argument("--source", help="local copy of the dataset JSON instead of downloading it")
    import_parser.add_argument("--limit", type=int, default=100, help="number of questions (default: 100)")
    import_parser.add_argument(
        "--unanswerable-ratio", type=float, default=0.25,
        help="fraction of questions that must be refused (default: 0.25)",
    )
    import_parser.add_argument("--articles", type=int, help="cap the number of articles in the corpus (default: all)")
    import_parser.add_argument("--seed", type=int, default=7, help="sampling seed (default: 7)")
    import_parser.set_defaults(func=cmd_import)

    # security -------------------------------------------------------------
    security_parser = subparsers.add_parser(
        "security",
        help="run the LLM security suite (prompt injection, leakage, agent misuse)",
    )
    sec_sub = security_parser.add_subparsers(dest="security_command", required=True)

    sec_run = sec_sub.add_parser("run", help="run attacks x defences and score them")
    sec_run.add_argument("--attacks", default="datasets/security/attacks.yaml",
                         help="attack corpus YAML")
    sec_run.add_argument("--root", help="project root that relative paths resolve against")
    sec_run.add_argument("--corpus", default="datasets/docs", help="corpus for the RAG scenario")
    sec_run.add_argument("--victim", default="simulated", choices=["simulated", "live"],
                         help="simulated (offline, deterministic) or live (an API model)")
    sec_run.add_argument("--provider", default="openai",
                         help="live victim provider: openai (default), anthropic")
    sec_run.add_argument("--model", help="live victim model id")
    sec_run.add_argument("--base-url", help="live victim endpoint (OpenAI-compatible)")
    sec_run.add_argument("--defenses", default="none,layered",
                         help="comma-separated defences or presets (default: none,layered)")
    sec_run.add_argument("--vectors", help="limit to these attack vectors (user,document,tool)")
    sec_run.add_argument("--trials", type=_positive_int, default=1,
                         help="trials per cell for a live victim (default: 1)")
    sec_run.add_argument("--seed", type=int, default=7, help="canary seed (default: 7)")
    sec_run.add_argument("--out", default="reports/security.json", help="results JSON output")
    sec_run.add_argument("--md", nargs="?", const="reports/security.md",
                         help="also write a Markdown scorecard report")
    sec_run.add_argument("--html", nargs="?", const="reports/security.html",
                         help="also write a self-contained HTML report")
    sec_run.add_argument("--fail-over", type=float, metavar="ASR",
                         help="exit 1 if the best defence's attack-success rate exceeds this")
    sec_run.add_argument("--min-reduction", type=float, metavar="FRACTION",
                         help="exit 1 if the best defence does not cut the undefended "
                              "attack-success rate by at least this fraction (e.g. 0.5)")
    sec_run.add_argument("--benign", nargs="?", const="datasets/security/benign.jsonl",
                         metavar="JSONL",
                         help="also measure each defence's false-block rate on harmless "
                              "requests from this corpus (default: datasets/security/benign.jsonl)")
    sec_run.set_defaults(func=cmd_security_run)

    sec_eval = sec_sub.add_parser(
        "detector-eval", help="benchmark injection detectors on the deepset test split"
    )
    sec_eval.add_argument("--data", default="datasets/security/deepset",
                          help="directory with train.jsonl and test.jsonl")
    sec_eval.add_argument("--detectors", default="heuristic",
                          help="comma-separated: heuristic, groq-guard, protectai")
    sec_eval.add_argument("--tune", action="store_true",
                          help="tune the heuristic threshold on the train split")
    sec_eval.add_argument("--by-language", action="store_true",
                          help="also break recall down by the language of each attack")
    sec_eval.add_argument("--out", default="reports/detector_eval.json", help="results JSON output")
    sec_eval.add_argument("--md", nargs="?", const="reports/detector_eval.md",
                          help="also write a Markdown table")
    sec_eval.set_defaults(func=cmd_security_detector_eval)

    sec_compare = sec_sub.add_parser(
        "compare", help="attack several models with the same suite and compare them"
    )
    sec_compare.add_argument("--models", default="groq-qwen,groq-gptoss",
                             help="comma-separated model shortnames (see security/models.py)")
    sec_compare.add_argument("--attacks", default="datasets/security/attacks.yaml")
    sec_compare.add_argument("--root", help="project root that relative paths resolve against")
    sec_compare.add_argument("--corpus", default="datasets/docs")
    sec_compare.add_argument("--defenses", default="none,layered")
    sec_compare.add_argument("--vectors", help="limit to these attack vectors")
    sec_compare.add_argument("--trials", type=_positive_int, default=1,
                             help="trials per cell per model (default: 1)")
    sec_compare.add_argument("--seed", type=int, default=7)
    sec_compare.add_argument("--out", default="reports/security_compare.json")
    sec_compare.add_argument("--md", nargs="?", const="reports/security_compare.md")
    sec_compare.set_defaults(func=cmd_security_compare)

    sec_import = sec_sub.add_parser(
        "import-deepset", help="download the deepset/prompt-injections benchmark"
    )
    sec_import.add_argument("--out", default="datasets/security/deepset", help="directory to write into")
    sec_import.set_defaults(func=cmd_security_import_deepset)

    sec_pkg = sec_sub.add_parser(
        "packages", help="audit a model for hallucinated package recommendations (LLM09)"
    )
    sec_pkg.add_argument("--model", default="groq-qwen",
                         help="model shortname to audit (see security/models.py)")
    sec_pkg.add_argument("--out", default="reports/package_audit.json", help="results JSON output")
    sec_pkg.add_argument("--md", nargs="?", const="reports/package_audit.md",
                         help="also write a Markdown report")
    sec_pkg.add_argument("--max-tokens", type=int, default=400, help="answer length cap")
    sec_pkg.set_defaults(func=cmd_security_packages)

    sec_benign = sec_sub.add_parser(
        "benign", help="measure each defence's false-block rate on harmless requests")
    sec_benign.add_argument("--benign", default="datasets/security/benign.jsonl",
                            help="JSONL of harmless requests")
    sec_benign.add_argument("--defenses", default="none,hardened,detector,layered",
                            help="comma-separated defences or presets to measure")
    sec_benign.add_argument("--with-deepset", action="store_true",
                            help="also include the real-world deepset benign rows")
    sec_benign.add_argument("--deepset", default="datasets/security/deepset",
                            help="directory with the deepset probes (for --with-deepset)")
    sec_benign.add_argument("--out", default="reports/benign.json", help="results JSON output")
    sec_benign.add_argument("--md", nargs="?", const="reports/benign.md",
                            help="also write a Markdown report")
    sec_benign.add_argument("--max-false-block", type=float, metavar="RATE",
                            help="exit 1 if any defence's false-block rate exceeds this")
    sec_benign.set_defaults(func=cmd_security_benign)

    sec_mcp = sec_sub.add_parser(
        "mcp", help="test MCP / tool-poisoning (description poisoning, rug-pull, cross-tool)")
    sec_mcp.add_argument("--defenses", default="none,detector,tool-policy,layered",
                         help="comma-separated defences or presets to measure")
    sec_mcp.add_argument("--seed", type=int, default=7, help="canary seed (default: 7)")
    sec_mcp.add_argument("--out", default="reports/mcp.json", help="results JSON output")
    sec_mcp.add_argument("--md", nargs="?", const="reports/mcp.md",
                         help="also write a Markdown report")
    sec_mcp.add_argument("--fail-over", type=float, metavar="RATE",
                         help="exit 1 if the best defence's exfiltration rate exceeds this")
    sec_mcp.set_defaults(func=cmd_security_mcp)

    sec_mt = sec_sub.add_parser(
        "multiturn", help="test multi-turn / crescendo attacks that build over several turns")
    sec_mt.add_argument("--defenses", default="none,detector,layered",
                        help="comma-separated defences or presets to measure")
    sec_mt.add_argument("--seed", type=int, default=7, help="canary seed (default: 7)")
    sec_mt.add_argument("--out", default="reports/multiturn.json", help="results JSON output")
    sec_mt.add_argument("--md", nargs="?", const="reports/multiturn.md",
                        help="also write a Markdown report")
    sec_mt.set_defaults(func=cmd_security_multiturn)

    sec_obf = sec_sub.add_parser(
        "obfuscation", help="measure detector evasion by obfuscation, and normalization's fix")
    sec_obf.add_argument("--detector", default="heuristic",
                         help="detector to test (heuristic, groq-guard, protectai)")
    sec_obf.add_argument("--out", default="reports/obfuscation.json", help="results JSON output")
    sec_obf.add_argument("--md", nargs="?", const="reports/obfuscation.md",
                         help="also write a Markdown report")
    sec_obf.set_defaults(func=cmd_security_obfuscation)

    sec_lab = sec_sub.add_parser(
        "lab", help="run every 'beyond one prompt' test and build the attack-lab page")
    sec_lab.add_argument("--attacks", default="datasets/security/attacks.yaml",
                         help="attack corpus YAML (for the demo)")
    sec_lab.add_argument("--root", help="project root that relative paths resolve against")
    sec_lab.add_argument("--out", default="reports/lab.json", help="results JSON output")
    sec_lab.add_argument("--html", nargs="?", const="reports/lab.html",
                         help="also write the self-contained attack-lab page")
    sec_lab.set_defaults(func=cmd_security_lab)

    # bench ----------------------------------------------------------------
    bench_parser = subparsers.add_parser(
        "bench", help="build and inspect the frozen, versioned attack benchmark (Bench v1)",
    )
    bench_sub = bench_parser.add_subparsers(dest="bench_command", required=True)

    bench_build = bench_sub.add_parser("build", help="rebuild the benchmark from its sources")
    bench_build.add_argument("--root", default="datasets/bench",
                             help="where the versioned dataset is written")
    bench_build.add_argument("--attacks", default="datasets/security/attacks.yaml",
                             help="seed attack corpus")
    bench_build.add_argument("--deepset", default="datasets/security/deepset",
                             help="directory with the deepset train/test probes")
    bench_build.set_defaults(func=cmd_bench_build)

    bench_stats = bench_sub.add_parser("stats", help="print a breakdown of the frozen benchmark")
    bench_stats.add_argument("--catalogue", default="datasets/bench/v1/attacks.jsonl",
                             help="the benchmark JSONL to summarise")
    bench_stats.set_defaults(func=cmd_bench_stats)

    bench_run = bench_sub.add_parser(
        "run", help="run the benchmark's verifiable attacks and record a manifest")
    bench_run.add_argument("--catalogue", default="datasets/bench/v1/attacks.jsonl",
                           help="the benchmark JSONL to run")
    bench_run.add_argument("--split", default="test", choices=["train", "dev", "test", "all"],
                           help="which split to run (default: test, the held-out set)")
    bench_run.add_argument("--victim", default="simulated", choices=["simulated", "live"],
                           help="simulated (offline, deterministic) or live (an API model)")
    bench_run.add_argument("--provider", default="openai", help="live victim provider")
    bench_run.add_argument("--model", help="live victim model id")
    bench_run.add_argument("--base-url", help="live victim endpoint (OpenAI-compatible)")
    bench_run.add_argument("--defenses", default="none,layered",
                           help="comma-separated defences or presets (default: none,layered)")
    bench_run.add_argument("--trials", type=_positive_int, default=1,
                           help="trials per cell for a live victim (default: 1)")
    bench_run.add_argument("--seed", type=int, default=42, help="canary seed (default: 42)")
    bench_run.add_argument("--max-tokens", type=_positive_int, default=512,
                           help="reply length cap for a live victim (default: 512); raise it "
                                "for reasoning models, which can spend it all thinking")
    bench_run.add_argument("--cache", nargs="?", const="reports/bench_cache",
                           help="cache model replies here so reruns are free and exact")
    bench_run.add_argument("--root", help="project root that relative paths resolve against")
    bench_run.add_argument("--corpus", default="datasets/docs", help="corpus for the RAG scenario")
    bench_run.add_argument("--out", default="reports/bench_run.json", help="results JSON output")
    bench_run.add_argument("--md", nargs="?", const="reports/bench_run.md",
                           help="also write a Markdown report")
    bench_run.set_defaults(func=cmd_bench_run)

    bench_lb = bench_sub.add_parser(
        "leaderboard", help="run the benchmark against several models and rank them")
    bench_lb.add_argument("--catalogue", default="datasets/bench/v1/attacks.jsonl",
                          help="the benchmark JSONL to run")
    bench_lb.add_argument("--models", default="groq-qwen,groq-gptoss",
                          help="comma-separated model shortnames (see security/models.py)")
    bench_lb.add_argument("--split", default="test", choices=["train", "dev", "test", "all"],
                          help="which split to run (default: test)")
    bench_lb.add_argument("--defenses", default="none,layered",
                          help="comma-separated defences or presets (default: none,layered)")
    bench_lb.add_argument("--trials", type=_positive_int, default=1, help="trials per cell")
    bench_lb.add_argument("--seed", type=int, default=42, help="canary seed (default: 42)")
    bench_lb.add_argument("--max-tokens", type=_positive_int, default=512,
                          help="reply length cap per model (default: 512); raise it for "
                               "reasoning models, which can spend it all thinking")
    bench_lb.add_argument("--cache", nargs="?", const="reports/bench_cache",
                          help="cache model replies here so reruns are free and resumable")
    bench_lb.add_argument("--root", help="project root that relative paths resolve against")
    bench_lb.add_argument("--corpus", default="datasets/docs", help="corpus for the RAG scenario")
    bench_lb.add_argument("--out", default="reports/leaderboard.json", help="results JSON output")
    bench_lb.add_argument("--md", nargs="?", const="reports/leaderboard.md",
                          help="also write a Markdown leaderboard")
    bench_lb.set_defaults(func=cmd_bench_leaderboard)

    # doctor ---------------------------------------------------------------
    doctor_parser = subparsers.add_parser(
        "doctor", help="check the install, datasets and API keys are in order")
    doctor_parser.add_argument("--root", help="project root that relative paths resolve against")
    doctor_parser.set_defaults(func=cmd_doctor)

    # demo -----------------------------------------------------------------
    demo_parser = subparsers.add_parser(
        "demo", help="a guided, offline walkthrough: scan a vulnerable app, add defences, rescan")
    demo_parser.add_argument("--root", help="project root that relative paths resolve against")
    demo_parser.add_argument("--attacks", default="datasets/security/attacks.yaml",
                             help="attack corpus YAML")
    demo_parser.add_argument("--out", help="also write the demo's results JSON here")
    demo_parser.set_defaults(func=cmd_demo)

    return parser


def cmd_security_run(args: argparse.Namespace) -> int:
    """Run the security suite and gate on the best defence's attack-success rate."""
    from ragprobe.security.report import render_markdown, render_terminal, scorecard
    from ragprobe.security.suite import run_suite
    from ragprobe.security.victims import get_victim

    base_dir = Path(args.root) if args.root else Path.cwd()
    if args.victim == "live":
        gen = ProbeConfig().generation
        if args.model:
            gen.model = args.model
        if args.base_url:
            gen.base_url = args.base_url
        provider = get_provider(gen, override=args.provider)
        victim = get_victim("live", provider=provider)
    else:
        victim = get_victim("simulated")

    vectors = [v.strip() for v in args.vectors.split(",")] if args.vectors else None
    defenses = [d.strip() for d in args.defenses.split(",") if d.strip()]

    def progress(done: int, total: int) -> None:
        if not sys.stderr.isatty():
            return
        print(f"\r  running {done}/{total} trials", end="", file=sys.stderr)

    try:
        results = run_suite(
            Path(args.attacks), victim, defenses=defenses, trials=args.trials,
            seed=args.seed, base_dir=base_dir, corpus_dir=args.corpus,
            vectors=vectors, progress=progress,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise InputError(str(exc)) from exc
    if sys.stderr.isatty():
        print("", file=sys.stderr)

    if getattr(args, "benign", None):
        from ragprobe.security.benign import false_block_rates, load_benign
        benign_path = base_dir / args.benign
        if benign_path.is_file():
            results["benign"] = false_block_rates(defenses, load_benign(benign_path))
        else:
            print(f"  (benign corpus not found at {benign_path}; skipping false-block)",
                  file=sys.stderr)

    _write_json(Path(args.out), results)
    print(render_terminal(results))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(results), encoding="utf-8")
        print(f"  wrote {args.md}")
    if args.html:
        from ragprobe.security.report_html import write_report
        write_report(results, Path(args.html))
        print(f"  wrote {args.html}")

    by_defense = results["summary"]["by_defense"]
    if args.fail_over is not None:
        card = scorecard(results)
        worst = max((r["asr_defended"] for r in card["rows"]), default=0.0)
        if worst > args.fail_over:
            print(f"\nGATE FAILED: best-defence attack-success rate {worst:.2f} "
                  f"exceeds the limit of {args.fail_over:.2f}", file=sys.stderr)
            return EXIT_GATE_FAILED
    if args.min_reduction is not None and by_defense:
        undefended = max(b["asr"] for b in by_defense.values())
        best = min(b["asr"] for b in by_defense.values())
        reduction = (undefended - best) / undefended if undefended else 1.0
        if reduction < args.min_reduction:
            print(f"\nGATE FAILED: best defence cut attack-success by only "
                  f"{reduction*100:.0f}% ({undefended*100:.0f}% -> {best*100:.0f}%), "
                  f"below the required {args.min_reduction*100:.0f}%", file=sys.stderr)
            return EXIT_GATE_FAILED
    return EXIT_OK


def cmd_security_detector_eval(args: argparse.Namespace) -> int:
    """Benchmark one or more injection detectors on the deepset test split."""
    from ragprobe.security.detector_eval import render_markdown, run_detector_eval

    detectors = [d.strip() for d in args.detectors.split(",") if d.strip()]
    data_dir = Path(args.data)
    if not (data_dir / "test.jsonl").is_file():
        raise InputError(
            f"no test.jsonl in {data_dir}. Run: ragprobe security import-deepset --out {data_dir}"
        )

    def progress(name: str) -> None:
        if sys.stderr.isatty():
            print(f"  scoring with {name} ...", file=sys.stderr)

    try:
        report = run_detector_eval(data_dir, detectors, tune=args.tune,
                                   by_language=args.by_language, progress=progress)
    except (ValueError, FileNotFoundError) as exc:
        raise InputError(str(exc)) from exc

    _write_json(Path(args.out), report)
    print(render_markdown(report))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
        print(f"  wrote {args.md}")
    return EXIT_OK


def cmd_security_compare(args: argparse.Namespace) -> int:
    """Attack several models with the same suite and write a comparison."""
    from ragprobe.security.compare import compare_models, render_markdown

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    defenses = [d.strip() for d in args.defenses.split(",") if d.strip()]
    vectors = [v.strip() for v in args.vectors.split(",")] if args.vectors else None
    base_dir = Path(args.root) if args.root else Path.cwd()

    def progress(name: str) -> None:
        if sys.stderr.isatty():
            print(f"  attacking {name} ...", file=sys.stderr)

    try:
        report = compare_models(
            Path(args.attacks), models, defenses=defenses, trials=args.trials,
            seed=args.seed, base_dir=base_dir, corpus_dir=args.corpus, vectors=vectors,
            progress=progress,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise InputError(str(exc)) from exc

    _write_json(Path(args.out), report)
    print(render_markdown(report))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
        print(f"  wrote {args.md}")
    return EXIT_OK


# Minimal free-model map for the package audit (kept local so this command stands
# alone). provider -> (base_url, key environment variable).
_PKG_MODELS = {
    "groq-qwen": ("https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", "GROQ_API_KEY"),
    "groq-gptoss": ("https://api.groq.com/openai/v1", "openai/gpt-oss-20b", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai",
               "gemini-flash-latest", "GEMINI_API_KEY"),
}


def cmd_security_packages(args: argparse.Namespace) -> int:
    """Audit a model for hallucinated (non-existent) package recommendations."""
    import os

    from ragprobe.security.packages import PyPIChecker, render_markdown, run_package_audit

    if args.model not in _PKG_MODELS:
        raise InputError(f"unknown model {args.model!r}; expected one of {', '.join(_PKG_MODELS)}")
    base_url, model_id, key_env = _PKG_MODELS[args.model]
    key = os.environ.get(key_env)
    if not key:
        raise InputError(f"no API key for {args.model}: set {key_env}")

    from ragprobe.providers.openai_compat import OpenAICompatibleProvider
    provider = OpenAICompatibleProvider(model=model_id, base_url=base_url, api_key=key)

    def ask(prompt: str) -> str:
        return provider.chat([{"role": "user", "content": prompt}],
                             max_tokens=args.max_tokens).get("content", "")

    def progress(done: int, total: int) -> None:
        if sys.stderr.isatty():
            print(f"\r  asking {done}/{total}", end="", file=sys.stderr)

    audit = run_package_audit(ask, PyPIChecker(), model_name=args.model, progress=progress).to_dict()
    if sys.stderr.isatty():
        print("", file=sys.stderr)
    _write_json(Path(args.out), audit)
    print(render_markdown(audit))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(audit), encoding="utf-8")
        print(f"  wrote {args.md}")
    return EXIT_OK


def cmd_security_benign(args: argparse.Namespace) -> int:
    """Measure how often each defence wrongly blocks harmless requests."""
    from ragprobe.security.benign import (
        deepset_benign,
        false_block_rates,
        load_benign,
        render_markdown,
    )

    benign = load_benign(Path(args.benign))
    if args.with_deepset:
        benign = benign + deepset_benign(Path(args.deepset))
    defenses = [d.strip() for d in args.defenses.split(",") if d.strip()]
    report = false_block_rates(defenses, benign)

    _write_json(Path(args.out), report)
    print(render_markdown(report))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
        print(f"  wrote {args.md}")

    if args.max_false_block is not None:
        worst = max((d["false_block_rate"] for d in report["defenses"]), default=0.0)
        if worst > args.max_false_block:
            print(f"\nGATE FAILED: a defence wrongly blocks {worst*100:.0f}% of benign "
                  f"requests, above the limit of {args.max_false_block*100:.0f}%", file=sys.stderr)
            return EXIT_GATE_FAILED
    return EXIT_OK


def cmd_security_mcp(args: argparse.Namespace) -> int:
    """Run the MCP / tool-poisoning scenarios and gate on the best defence."""
    from ragprobe.security.mcp import render_markdown, run_mcp

    defenses = [d.strip() for d in args.defenses.split(",") if d.strip()]
    report = run_mcp(defenses=defenses, seed=args.seed)
    _write_json(Path(args.out), report)
    print(render_markdown(report))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
        print(f"  wrote {args.md}")
    if args.fail_over is not None:
        best = min((b["asr"] for b in report["by_defense"].values()), default=0.0)
        if best > args.fail_over:
            print(f"\nGATE FAILED: best-defence exfiltration rate {best:.2f} exceeds "
                  f"the limit of {args.fail_over:.2f}", file=sys.stderr)
            return EXIT_GATE_FAILED
    return EXIT_OK


def cmd_security_multiturn(args: argparse.Namespace) -> int:
    """Run the multi-turn / crescendo scenarios and report success per defence."""
    from ragprobe.security.multiturn import render_markdown, run_multiturn

    defenses = [d.strip() for d in args.defenses.split(",") if d.strip()]
    report = run_multiturn(defenses=defenses, seed=args.seed)
    _write_json(Path(args.out), report)
    print(render_markdown(report))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
        print(f"  wrote {args.md}")
    return EXIT_OK


def cmd_security_obfuscation(args: argparse.Namespace) -> int:
    """Measure how obfuscation evades a detector, and that normalizing restores it."""
    from ragprobe.security.detector import get_detector
    from ragprobe.security.obfuscation import evaluate, render_markdown

    report = evaluate(get_detector(args.detector))
    _write_json(Path(args.out), report)
    print(render_markdown(report))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
        print(f"  wrote {args.md}")
    return EXIT_OK


def cmd_security_lab(args: argparse.Namespace) -> int:
    """Run the demo, MCP, multi-turn and obfuscation tests and build the lab page."""
    from ragprobe.security.lab import run_lab

    base_dir = Path(args.root) if args.root else Path.cwd()
    try:
        lab = run_lab(Path(args.attacks), base_dir=base_dir)
    except (ValueError, FileNotFoundError) as exc:
        raise InputError(str(exc)) from exc
    _write_json(Path(args.out), lab)
    f = lab["facts"]
    print(f"attack lab: demo grade {f['demo_grade_before']} -> {f['demo_grade_after']}, "
          f"poisoned tools {f['mcp_undefended']*100:.0f}% -> {f['mcp_policy']*100:.0f}% "
          f"(tool policy), multi-turn {f['multiturn_undefended']*100:.0f}% -> "
          f"{f['multiturn_layered']*100:.0f}% (layered)")
    print(f"  wrote {args.out}")
    if args.html:
        from ragprobe.security.lab_html import render
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(render(lab), encoding="utf-8")
        print(f"  wrote {args.html}")
    return EXIT_OK


def cmd_security_import_deepset(args: argparse.Namespace) -> int:
    """Download the deepset/prompt-injections dataset."""
    from ragprobe.importers.deepset import import_deepset

    counts = import_deepset(Path(args.out))
    print(f"wrote {counts} to {args.out}")
    return EXIT_OK


def cmd_bench_build(args: argparse.Namespace) -> int:
    """Rebuild the frozen benchmark from its sources and print the breakdown."""
    from ragprobe.bench.build import VERSION, write_v1

    summary = write_v1(root=Path(args.root), attacks_path=Path(args.attacks),
                       deepset_dir=Path(args.deepset))
    out_dir = Path(args.root) / VERSION
    print(f"built Bench {VERSION}: {summary['total']} items "
          f"({summary['attacks']} attacks, {summary['probes']} probes) -> {out_dir}")
    print(f"  catalogue -> {out_dir / 'attacks.jsonl'}")
    print(f"  datasheet -> {out_dir / 'datasheet.md'}")
    print(f"  notice    -> {out_dir / 'NOTICE.md'}")
    return EXIT_OK


def _warn_if_truncated(counts) -> None:
    """Say so loudly when replies were cut off at the token limit (they score as safe)."""
    total = sum(counts)
    if total:
        print(f"WARNING: {total} reply(ies) hit the token limit and were cut off or empty; they "
              "are scored as 'no attack succeeded', so the rates may be too low. "
              "Re-run with a larger --max-tokens.", file=sys.stderr)


def cmd_bench_run(args: argparse.Namespace) -> int:
    """Run the benchmark's verifiable attacks with a reproducibility manifest."""
    from ragprobe.bench.run import render_markdown, run_bench
    from ragprobe.security.victims import get_victim

    base_dir = Path(args.root) if args.root else Path.cwd()
    if args.victim == "live":
        gen = ProbeConfig().generation
        if args.model:
            gen.model = args.model
        if args.base_url:
            gen.base_url = args.base_url
        provider = get_provider(gen, override=args.provider)
        victim = get_victim("live", provider=provider, max_tokens=args.max_tokens)
    else:
        victim = get_victim("simulated")

    defenses = [d.strip() for d in args.defenses.split(",") if d.strip()]
    split = None if args.split == "all" else args.split
    try:
        result = run_bench(
            Path(args.catalogue), victim, split=split, defenses=defenses,
            trials=args.trials, seed=args.seed,
            cache_dir=Path(args.cache) if args.cache else None,
            base_dir=base_dir, corpus_dir=args.corpus,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise InputError(str(exc)) from exc

    _write_json(Path(args.out), result)
    _warn_if_truncated([result["manifest"].get("truncated_replies", 0)])
    print(render_markdown(result))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(result), encoding="utf-8")
        print(f"  wrote {args.md}")
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    """Walk through scan -> defend -> rescan on the fictional Acme Helpdesk."""
    from ragprobe.demo import passes, render, run_demo

    base_dir = Path(args.root) if args.root else Path.cwd()
    try:
        report = run_demo(Path(args.attacks), base_dir=base_dir)
    except (ValueError, FileNotFoundError) as exc:
        raise InputError(str(exc)) from exc
    print(render(report))
    if args.out:
        _write_json(Path(args.out), report)
        print(f"  wrote {args.out}")
    return EXIT_OK if passes(report) else EXIT_GATE_FAILED


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check the install, datasets and keys; exit non-zero only on real problems."""
    from ragprobe.doctor import has_failures, render, run_checks

    checks = run_checks(Path(args.root) if args.root else Path.cwd())
    print(render(checks))
    return EXIT_USAGE if has_failures(checks) else EXIT_OK


def cmd_bench_leaderboard(args: argparse.Namespace) -> int:
    """Run the benchmark against several models and rank them."""
    from ragprobe.bench.leaderboard import render_markdown, run_leaderboard

    base_dir = Path(args.root) if args.root else Path.cwd()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    defenses = [d.strip() for d in args.defenses.split(",") if d.strip()]
    split = None if args.split == "all" else args.split

    def progress(name: str) -> None:
        if sys.stderr.isatty():
            print(f"\r  running {name} ...", end="", file=sys.stderr)

    try:
        report = run_leaderboard(
            Path(args.catalogue), models, split=split, defenses=defenses,
            trials=args.trials, seed=args.seed,
            cache_dir=Path(args.cache) if args.cache else None,
            base_dir=base_dir, corpus_dir=args.corpus, max_tokens=args.max_tokens,
            progress=progress)
    except (ValueError, FileNotFoundError) as exc:
        raise InputError(str(exc)) from exc
    if sys.stderr.isatty():
        print("", file=sys.stderr)

    _write_json(Path(args.out), report)
    _warn_if_truncated([m["manifest"].get("truncated_replies", 0) for m in report["models"]])
    print(render_markdown(report))
    print(f"  wrote {args.out}")
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(report), encoding="utf-8")
        print(f"  wrote {args.md}")
    return EXIT_OK


def cmd_bench_stats(args: argparse.Namespace) -> int:
    """Summarise a frozen benchmark catalogue."""
    from ragprobe.bench.dataset import load_jsonl, stats, validate_all

    items = load_jsonl(Path(args.catalogue))
    validate_all(items)
    s = stats(items)
    print(f"Bench catalogue: {s['total']} items "
          f"({s['attacks']} attacks, {s['probes']} probes)")
    for dim in ("by_owasp", "by_technique", "by_language", "by_source", "by_split"):
        label = dim[3:].replace("_", " ")
        pairs = ", ".join(f"{k}={v}" for k, v in s[dim].items())
        print(f"  {label:10} {pairs}")
    return EXIT_OK


def cmd_rescore(args: argparse.Namespace) -> int:
    """Re-apply the evaluators to saved answers; no model calls."""
    payload = _read_json(Path(args.results), "results")
    config = _build_config(args) if args.config else None
    base_dir = _base_dir(args)
    dataset_path = base_dir / (config.dataset_path if config else payload["config"]["dataset_path"])
    cases = load_dataset(dataset_path)
    result = rescore(payload, cases, config)
    out = result.to_dict()
    results_path = _write_json(Path(args.out), out)
    print(render_run_summary(out))
    print(f"  rescored {payload.get('started_at')} -> {results_path}")
    history_path = _record_history(args, out)
    if history_path is not None:
        print(f"  history -> {history_path}")
    return EXIT_OK


def cmd_import(args: argparse.Namespace) -> int:
    """Turn a public dataset into a corpus + golden set + config directory."""
    if args.dataset_name != "squad":
        raise InputError(f"unknown dataset {args.dataset_name!r}; expected 'squad'")
    from ragprobe.importers import squad

    try:
        data, source = squad.load_source(Path(args.source) if args.source else None, args.split)
        documents, cases = squad.convert(
            data,
            limit=args.limit,
            unanswerable_ratio=args.unanswerable_ratio,
            seed=args.seed,
            articles=args.articles,
        )
        out = squad.write_example(
            Path(args.out), documents, cases, args.split, source,
            args.seed, args.limit, args.unanswerable_ratio,
        )
    except squad.ImportError_ as exc:
        raise InputError(str(exc)) from exc
    refusals = sum(1 for case in cases if case.get("should_refuse"))
    print(
        f"imported {len(cases)} case(s) ({refusals} unanswerable) over "
        f"{len(documents)} article(s) into {out}"
    )
    print(f"  next: ragprobe run --config {out / 'ragprobe.yaml'} --root {out} --html")
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, DatasetError, CorpusError, FileNotFoundError, InputError, TargetError) as exc:
        # Expected, actionable failures: print the message, not a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:  # pragma: no cover
        print("interrupted", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
