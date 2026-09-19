"""The SQuAD 2.0 importer, on a tiny in-memory file (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragprobe.cli import EXIT_OK, EXIT_USAGE, main
from ragprobe.config import ProbeConfig
from ragprobe.evaluation.dataset import load_dataset
from ragprobe.evaluation.runner import run_suite
from ragprobe.importers.squad import ImportError_, convert, doc_id_for, render_golden_set, write_example


def _qa(qid, question, answers=None, impossible=False):
    return {
        "id": qid,
        "question": question,
        "answers": [{"text": a, "answer_start": 0} for a in (answers or [])],
        "is_impossible": impossible,
    }


SAMPLE = {
    "version": "v2.0",
    "data": [
        {
            "title": "Normans",
            "paragraphs": [
                {
                    "context": "The Normans were the people who gave their name to Normandy, a region in France.",
                    "qas": [
                        _qa("n1", "In what country is Normandy located?", ["France", "France."]),
                        _qa("n2", "Who gave their name to Normandy in the 1000s?", ["The Normans", "Normans"]),
                        _qa("n3", "What was the Norman religion in 1100?", impossible=True),
                    ],
                },
                {
                    "context": "The Norman dynasty had a major political impact on medieval Europe.",
                    "qas": [_qa("n4", "What impact did the Normans have?", ["a major political impact"])],
                },
            ],
        },
        {
            "title": "Steam engine",
            "paragraphs": [
                {
                    "context": "A steam engine is a heat engine that performs mechanical work using steam.",
                    "qas": [
                        _qa("s1", "What kind of engine is a steam engine?", ["heat engine", "a heat engine"]),
                        _qa("s2", "Who invented the steam engine in 1600?", impossible=True),
                    ],
                },
            ],
        },
    ],
}


class TestConvert:
    def test_documents_are_one_section_per_paragraph(self):
        documents, _ = convert(SAMPLE, limit=10)
        assert set(documents) == {"normans", "steam_engine"}
        text = documents["normans"]
        assert text.startswith("# Normans\n")
        assert "## Paragraph 1\n" in text and "## Paragraph 2\n" in text
        assert "region in France." in text

    def test_cases_point_at_their_paragraph_and_shortest_answer(self):
        _, cases = convert(SAMPLE, limit=10, unanswerable_ratio=0.0)
        by_id = {c["id"]: c for c in cases}
        assert by_id["squad-n1"]["expected_chunks"] == ["normans#paragraph-1"]
        assert by_id["squad-n1"]["required_keywords"] == ["France"]  # trailing '.' stripped, shortest kept
        assert by_id["squad-n2"]["required_keywords"] == ["Normans"]
        assert by_id["squad-n4"]["expected_chunks"] == ["normans#paragraph-2"]
        assert by_id["squad-s1"]["category"] == "steam_engine"
        assert all(not c.get("should_refuse") for c in cases)

    def test_unanswerable_ratio_selects_refusals(self):
        _, cases = convert(SAMPLE, limit=4, unanswerable_ratio=0.5)
        refusals = [c for c in cases if c.get("should_refuse")]
        assert len(refusals) == 2 and len(cases) == 4
        assert all("expected_chunks" not in c for c in refusals)
        assert {c["id"] for c in refusals} == {"squad-n3", "squad-s2"}

    def test_sampling_is_deterministic_and_spreads_across_articles(self):
        _, first = convert(SAMPLE, limit=2, unanswerable_ratio=0.0, seed=3)
        _, again = convert(SAMPLE, limit=2, unanswerable_ratio=0.0, seed=3)
        assert [c["id"] for c in first] == [c["id"] for c in again]
        assert {c["category"] for c in first} == {"normans", "steam_engine"}

    def test_articles_cap(self):
        documents, cases = convert(SAMPLE, limit=10, articles=1)
        assert set(documents) == {"normans"}
        assert all(c["category"] == "normans" for c in cases)

    @pytest.mark.parametrize("bad", [{"data": "nope"}, [], {"nodata": 1}])
    def test_rejects_non_squad_input(self, bad):
        with pytest.raises(ImportError_):
            convert(bad)

    def test_rejects_bad_options(self):
        with pytest.raises(ImportError_):
            convert(SAMPLE, limit=0)
        with pytest.raises(ImportError_):
            convert(SAMPLE, unanswerable_ratio=1.5)

    def test_doc_ids(self):
        assert doc_id_for("Steam engine") == "steam_engine"
        assert doc_id_for("Genghis_Khan") == "genghis_khan"
        assert doc_id_for("!!!") == "article"


class TestWrittenExampleRunsEndToEnd:
    """The strongest check: the written files load, every expected chunk exists,
    and the suite runs on them offline."""

    def test_written_example_is_a_valid_project(self, tmp_path):
        documents, cases = convert(SAMPLE, limit=6, unanswerable_ratio=0.34)
        out = write_example(tmp_path / "squad", documents, cases, "dev", "sample.json", 7, 6, 0.34)
        assert (out / "corpus" / "normans.md").is_file()
        assert (out / "NOTICE.md").read_text(encoding="utf-8").startswith("# Source and license")

        config = ProbeConfig.from_yaml(out / "ragprobe.yaml")
        loaded = load_dataset(out / config.dataset_path)
        assert len(loaded) == 6
        run = run_suite(loaded, config.apply_overrides({"evaluation.judge_enabled": False}), base_dir=out)
        assert run.total == 6
        # The stub answers extractively, so the answerable cases retrieve their paragraph.
        answerable = [c for c in run.cases if c.expected_chunks]
        assert answerable and all(c.retrieval["hit_rate@3"] == 1.0 for c in answerable)

    def test_yaml_quoting_survives_awkward_text(self):
        cases = [{
            "id": "squad-x", "category": "c", "question": 'Why: "quotes", colons: and #hashes?',
            "expected_chunks": ["c#paragraph-1"], "required_keywords": ["a: b"], "notes": "n: {x}",
        }]
        text = render_golden_set(cases, "dev", "src")
        import yaml

        parsed = yaml.safe_load(text)["cases"][0]
        assert parsed["question"] == 'Why: "quotes", colons: and #hashes?'
        assert parsed["required_keywords"] == ["a: b"]


class TestCli:
    def test_import_squad_from_local_file(self, tmp_path, capsys):
        source = tmp_path / "dev.json"
        source.write_text(json.dumps(SAMPLE), encoding="utf-8")
        out = tmp_path / "out"
        code = main(["import", "squad", "--source", str(source), "--out", str(out), "--limit", "5"])
        assert code == EXIT_OK
        assert "imported 5 case(s)" in capsys.readouterr().out
        assert (out / "golden_set.yaml").is_file() and (out / "ragprobe.yaml").is_file()

    def test_bad_options_are_usage_errors(self, tmp_path, capsys):
        source = tmp_path / "dev.json"
        source.write_text(json.dumps({"data": "nope"}), encoding="utf-8")
        code = main(["import", "squad", "--source", str(source), "--out", str(tmp_path / "o")])
        assert code == EXIT_USAGE
        assert "not a SQuAD file" in capsys.readouterr().err
