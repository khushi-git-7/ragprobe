"""Benchmark prompt-injection detectors on an independent, labelled dataset.

The point of this module is honesty about detector quality. A detector's own
author always reports flattering numbers on data close to what it was built from.
RAGProbe scores every detector on the **test split of deepset/prompt-injections**,
which none of them were tuned on here, and reports the full confusion matrix - not
just accuracy, because on an imbalanced set accuracy hides the two errors that
matter: attacks let through (false negatives) and real users blocked (false
positives). The heuristic's threshold is tuned on the **train** split only, so the
test numbers are never fitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from ragprobe.importers.deepset import load_split
from ragprobe.security.detector import RULES, Detector, HeuristicDetector, get_detector


@dataclass
class Metrics:
    detector: str
    threshold: float
    n: int
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        """Share of real attacks caught."""
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def false_positive_rate(self) -> float:
        """Share of benign inputs wrongly blocked - the cost to real users."""
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "detector": self.detector, "threshold": round(self.threshold, 3), "n": self.n,
            "tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn,
            "accuracy": round(self.accuracy, 4), "precision": round(self.precision, 4),
            "recall": round(self.recall, 4), "f1": round(self.f1, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
        }


def _confusion(labels: Sequence[int], flags: Sequence[bool]) -> Dict[str, int]:
    tp = fp = tn = fn = 0
    for label, flag in zip(labels, flags):
        if label == 1 and flag:
            tp += 1
        elif label == 1 and not flag:
            fn += 1
        elif label == 0 and flag:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def evaluate(detector: Detector, rows: Sequence[Dict], name: Optional[str] = None,
             threshold: Optional[float] = None) -> Metrics:
    texts = [r["text"] for r in rows]
    labels = [int(r["label"]) for r in rows]
    flags = [v.flagged for v in detector.score_many(texts)]
    c = _confusion(labels, flags)
    return Metrics(detector=name or detector.name,
                   threshold=threshold if threshold is not None else getattr(detector, "threshold", 0.0),
                   n=len(rows), **c)


def _recall_by_language_from_flags(rows: Sequence[Dict],
                                   flags: Sequence[bool]) -> Dict[str, Dict[str, object]]:
    """Per-language recall on the attack rows, from an already-computed flag list.

    Takes the flags rather than re-scoring so a networked detector is called once
    per text, not once for the overall metric and again here.
    """
    from ragprobe.security.language import classify

    groups: Dict[str, List[bool]] = {}
    for row, flag in zip(rows, flags):
        if int(row["label"]) == 1:
            groups.setdefault(classify(row["text"]), []).append(flag)
    out: Dict[str, Dict[str, object]] = {}
    for language, caught in sorted(groups.items()):
        out[language] = {
            "attacks": len(caught),
            "caught": sum(caught),
            "recall": round(sum(caught) / len(caught), 4) if caught else 0.0,
        }
    return out


def evaluate_with_flags(detector: Detector, rows: Sequence[Dict], name: Optional[str] = None,
                        threshold: Optional[float] = None) -> "tuple[Metrics, List[bool]]":
    """Score every row once; return the metrics and the raw flags for reuse."""
    labels = [int(r["label"]) for r in rows]
    flags = [v.flagged for v in detector.score_many([r["text"] for r in rows])]
    c = _confusion(labels, flags)
    metrics = Metrics(detector=name or detector.name,
                      threshold=threshold if threshold is not None else getattr(detector, "threshold", 0.0),
                      n=len(rows), **c)
    return metrics, flags


def tune_heuristic_threshold(train_rows: Sequence[Dict]) -> float:
    """Pick the heuristic score threshold that maximises F1 on the train split.

    Scored once per row; the threshold sweep then just compares against the cached
    scores, so tuning is cheap. Ties break toward the higher threshold (fewer false
    positives), which is the safer default for a production filter.
    """
    scorer = HeuristicDetector(threshold=0.0)
    scores = [scorer.score(r["text"]).score for r in train_rows]
    labels = [int(r["label"]) for r in train_rows]
    candidates = sorted({0.0} | {round(w, 3) for w in _rule_weights()} |
                        {round(s, 3) for s in scores})
    best_threshold, best_f1 = 0.0, -1.0
    for threshold in candidates:
        flags = [s >= threshold for s in scores]
        c = _confusion(labels, flags)
        m = Metrics("heuristic", threshold, len(train_rows), **c)
        if (m.f1, threshold) >= (best_f1, best_threshold):
            best_f1, best_threshold = m.f1, threshold
    return best_threshold


def _rule_weights() -> List[float]:
    sums = []
    total = 0.0
    for rule in sorted(RULES, key=lambda r: r.weight):
        total += rule.weight
        sums.append(total)
    return [r.weight for r in RULES] + sums


def run_detector_eval(
    data_dir: Path,
    detectors: Sequence[str],
    tune: bool = False,
    by_language: bool = False,
    make_detector: Optional[Callable[[str, Optional[float]], Detector]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    data_dir = Path(data_dir)
    test_rows = load_split(data_dir / "test.jsonl")
    train_rows = load_split(data_dir / "train.jsonl") if tune else []
    factory = make_detector or (lambda name, threshold: get_detector(name, threshold))

    tuned_threshold = None
    if tune and "heuristic" in detectors:
        tuned_threshold = tune_heuristic_threshold(train_rows)

    results = []
    for name in detectors:
        if progress:
            progress(name)
        threshold = tuned_threshold if (name == "heuristic" and tuned_threshold is not None) else None
        detector = factory(name, threshold)
        metrics, flags = evaluate_with_flags(detector, test_rows, name=name, threshold=threshold)
        row = metrics.to_dict()
        if by_language:
            row["by_language"] = _recall_by_language_from_flags(test_rows, flags)
        results.append(row)

    positives = sum(1 for r in test_rows if r["label"] == 1)
    report: Dict[str, object] = {
        "kind": "detector-eval",
        "dataset": "deepset/prompt-injections",
        "split": "test",
        "n": len(test_rows),
        "positives": positives,
        "negatives": len(test_rows) - positives,
        "tuned_heuristic_threshold": tuned_threshold,
        "detectors": results,
    }
    if by_language:
        from ragprobe.security.language import distribution
        report["attack_language_distribution"] = distribution(
            [r for r in test_rows if r["label"] == 1])
    return report


def render_markdown(report: Dict[str, object]) -> str:
    lines = ["# Detector benchmark\n",
             f"Dataset: **{report['dataset']}** ({report['split']} split, "
             f"{report['n']} texts: {report['positives']} attacks, {report['negatives']} benign).\n"]
    if report.get("tuned_heuristic_threshold") is not None:
        lines.append(f"Heuristic threshold tuned on the train split: "
                     f"`{report['tuned_heuristic_threshold']}`.\n")
    lines.append("| Detector | Recall (attacks caught) | False-positive rate | Precision | F1 | Accuracy |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for d in report["detectors"]:
        lines.append(f"| `{d['detector']}` | {d['recall']*100:.0f}% | {d['false_positive_rate']*100:.0f}% | "
                     f"{d['precision']*100:.0f}% | {d['f1']:.2f} | {d['accuracy']*100:.0f}% |")
    lines.append("")
    lines.append("Recall is the share of real attacks caught; the false-positive rate is the "
                 "share of benign inputs wrongly blocked. The heuristic threshold is tuned on "
                 "the train split; transformer detectors are scored at their documented default "
                 "operating point (probability >= 0.5), so this compares each detector as it "
                 "would be deployed out of the box, not after per-dataset tuning.")
    lines.append("")

    if any("by_language" in d for d in report["detectors"]):
        from ragprobe.security.language import LANGUAGE_NAMES
        dist = report.get("attack_language_distribution", {})
        langs = sorted({lang for d in report["detectors"]
                        for lang in d.get("by_language", {})},
                       key=lambda l: -dist.get(l, 0))
        lines.append("## Recall by attack language\n")
        lines.append("Where the overall recall comes from: the same detectors, split by the "
                     "language each attack is written in.\n")
        header = "| Detector | " + " | ".join(
            f"{LANGUAGE_NAMES.get(l, l)} (n={dist.get(l, 0)})" for l in langs) + " |"
        lines.append(header)
        lines.append("|---|" + "|".join("--:" for _ in langs) + "|")
        for d in report["detectors"]:
            cells = []
            for lang in langs:
                stat = d.get("by_language", {}).get(lang)
                cells.append(f"{stat['recall']*100:.0f}%" if stat else "-")
            lines.append(f"| `{d['detector']}` | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)
