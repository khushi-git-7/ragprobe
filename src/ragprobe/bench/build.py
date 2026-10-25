"""Assemble Bench v1 from its sources and freeze it to disk.

Sources, with their licences:

- our hand-written seed attacks        (RAGProbe, MIT)
- generated technique x language items (RAGProbe, MIT)
- deepset/prompt-injections probes      (Apache-2.0)

Later PRs add vetted garak (Apache-2.0) and PyRIT (MIT) imports behind the same
schema. Splits are assigned by hashing each id, so a rebuild reproduces exactly
and nothing silently moves between train/dev/test.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ragprobe.bench.dataset import save_jsonl, stats, validate_all
from ragprobe.bench.generate import generate_attacks
from ragprobe.bench.generate_v2 import generate_v2_attacks
from ragprobe.bench.schema import (
    SEED_TECHNIQUE_MAP,
    TECHNIQUES,
    BenchItem,
    assign_split,
)
from ragprobe.security.attacks import load_attacks
from ragprobe.security.language import classify

VERSION = "v1"
DEFAULT_ROOT = Path("datasets/bench")


def _seed_items(attacks_path: Path) -> List[BenchItem]:
    out: List[BenchItem] = []
    for a in load_attacks(attacks_path):
        technique = a.technique if a.technique in TECHNIQUES else \
            SEED_TECHNIQUE_MAP.get(a.technique, "external")
        out.append(BenchItem(
            id=f"seed-{a.id}", kind="attack", owasp=a.owasp, technique=technique,
            language=a.language, source="ragprobe-seed", licence="MIT", split="train",
            vector=a.vector, goal=a.goal, payload=a.payload, question=a.question,
            cover=a.cover, description=a.description, expect=tuple(a.expect)))
    return out


def _deepset_probes(deepset_dir: Path) -> List[BenchItem]:
    from ragprobe.importers.deepset import load_split

    out: List[BenchItem] = []
    for split_name in ("train", "test"):
        path = deepset_dir / f"{split_name}.jsonl"
        if not path.is_file():
            continue
        for n, row in enumerate(load_split(path)):
            text = row["text"]
            label = int(row["label"])
            lang = classify(text) if label == 1 else "other"
            lang = lang if lang in {"en", "de", "es", "fr"} else "other"
            out.append(BenchItem(
                id=f"deepset-{split_name}-{n:04d}", kind="probe", owasp="LLM01",
                technique="external", language=lang, source="deepset",
                licence="Apache-2.0", split="train", text=text, label=label))
    return out


def build_v1(attacks_path: Path = Path("datasets/security/attacks.yaml"),
             deepset_dir: Path = Path("datasets/security/deepset")) -> List[BenchItem]:
    """Build the full Bench v1 item list, splits assigned, validated."""
    items = _seed_items(attacks_path) + generate_attacks() + _deepset_probes(deepset_dir)
    for item in items:
        item.split = assign_split(item.id)
    validate_all(items)
    return items


def build_v2(attacks_path: Path = Path("datasets/security/attacks.yaml"),
             deepset_dir: Path = Path("datasets/security/deepset")) -> List[BenchItem]:
    """Bench v2: every v1 item exactly as it was (same ids, same splits), plus new families.

    Splits come from hashing each id, so v1 items keep their split and v1 results stay
    comparable; the new items are spread across train/dev/test the same way.
    """
    items = build_v1(attacks_path, deepset_dir) + generate_v2_attacks()
    for item in items:
        item.split = assign_split(item.id)
    validate_all(items)
    return items


def _write(items: List[BenchItem], root: Path, version: str) -> dict:
    out_dir = Path(root) / version
    save_jsonl(items, out_dir / "attacks.jsonl")
    summary = stats(items)
    (out_dir / "datasheet.md").write_text(_datasheet(summary, version), encoding="utf-8")
    (out_dir / "NOTICE.md").write_text(_notice(summary, version), encoding="utf-8")
    return summary


def write_v1(root: Path = DEFAULT_ROOT, **kwargs) -> dict:
    """Build Bench v1 and write the catalogue, datasheet and NOTICE under ``root/v1``."""
    return _write(build_v1(**kwargs), root, VERSION)


def write_v2(root: Path = DEFAULT_ROOT, **kwargs) -> dict:
    """Build Bench v2 and write it under ``root/v2``; v1 is left untouched."""
    return _write(build_v2(**kwargs), root, "v2")


V2_NOTE = """- **v2 families** - seven more techniques (hypothetical framing, completion prefix,
  emotional pressure, delimiter injection, authorised-test claims, format hijacking,
  task deflection), each hand-written in four languages and crossed with the same two
  goals. Every v1 item is kept exactly as it was, with the same split, so v1 results
  remain comparable.
"""


def _table(title: str, counts: dict) -> str:
    rows = "\n".join(f"| {k} | {v} |" for k, v in counts.items())
    return f"\n**{title}**\n\n| value | count |\n|---|--:|\n{rows}\n"


def _datasheet(s: dict, version: str = VERSION) -> str:
    extra = V2_NOTE if version == "v2" else ""
    return f"""# Bench {version} - datasheet

A versioned benchmark for testing LLM / RAG / agent applications against the
OWASP Top 10 for LLM Applications. Written in the spirit of *Datasheets for
Datasets* (Gebru et al.).

## What it is

**{s['total']} items**: **{s['attacks']} verifiable attacks** (canary-structured,
scored automatically by the suite's oracles) and **{s['probes']} detection probes**
(labelled injection / benign strings for benchmarking detectors and measuring
false positives). The two kinds are tagged by `kind` so the runner selects only
what it can actually score, while totals stay honest.

## Composition
{_table("By kind", s['by_kind'])}{_table("By OWASP risk", s['by_owasp'])}
{_table("By technique", s['by_technique'])}{_table("By language", s['by_language'])}
{_table("By source", s['by_source'])}{_table("By split", s['by_split'])}

Of the {s['probes']} probes, {s['probe_positives']} are injections (label 1) and
the rest benign (label 0).

## How it was made

- **Seed attacks** - hand-written technique templates (`datasets/security/attacks.yaml`).
- **Generated attacks** - every injection technique crossed with four languages
  (English, German, Spanish, French) and two checkable goals; non-English
  wrappers are hand-written, not machine-translated, so the language axis is clean.
- **Detection probes** - the deepset/prompt-injections dataset.
{extra}
Splits are assigned by hashing each item id (train / dev / test ~ 60 / 15 / 25),
so the assignment is deterministic and reproducible and nothing moves between
splits on a rebuild. **Detectors are tuned on dev and reported only on test.**

## Intended use

Defensive testing of systems you own or are authorised to test: measure attack
success per OWASP risk and per defence, and benchmark detectors. **Not** for
attacking third-party systems.

## Known gaps

- Verifiable attacks use planted canaries, so they measure *obedience to an
  injected instruction*, not every possible harm.
- Four languages so far; more are planned.
- garak and PyRIT imports are added in a later version.

## Licence and provenance

Each item records its `source` and `licence`; see `NOTICE.md`. RAGProbe-authored
items are MIT; imported items keep their upstream licence.

## Reproduce

`ragprobe bench build` (add `--version v2` for v2) rebuilds this catalogue from the sources above; the result
is byte-for-byte stable given the same inputs.
"""


def _notice(s: dict, version: str = VERSION) -> str:
    return f"""# Bench {version} - sources and licences

This benchmark bundles material from several sources. Each item in
`attacks.jsonl` records its own `source` and `licence`. Summary:

| source | items | licence |
|---|--:|---|
| RAGProbe (seed + generated) | {s['by_source'].get('ragprobe-seed', 0) + s['by_source'].get('ragprobe-generated', 0)} | MIT |
| deepset/prompt-injections | {s['by_source'].get('deepset', 0)} | Apache-2.0 |

## deepset/prompt-injections (Apache-2.0)

Prompt-injection / benign text classification dataset. Used here as detection
probes. Copyright its authors; distributed under the Apache License 2.0. See the
dataset's own licence for full terms.

## RAGProbe items (MIT)

Seed and generated attacks are authored by this project and released under the
repository's MIT licence. They are generic, public prompt-injection techniques
and target only RAGProbe's own simulated victims.
"""
