"""Tests for golden-dataset loading and validation.

The validation tests are as important as the loading tests. A golden set that
silently accepts a typo'd field name reports a case as present while it asserts
nothing, which is the worst possible outcome for test data.
"""

from __future__ import annotations

import json

import pytest

from ragprobe.evaluation.dataset import (
    DatasetError,
    dataset_fingerprint,
    load_dataset,
    parse_cases,
)

VALID = {
    "id": "case-1",
    "question": "How long is telemetry retained?",
    "expected_chunks": ["security_policy#data-retention"],
    "required_keywords": ["13 months"],
}


class TestParsing:
    def test_minimal_case(self):
        cases = parse_cases([VALID])
        assert len(cases) == 1
        assert cases[0].id == "case-1"
        assert cases[0].category == "general"
        assert cases[0].should_refuse is False

    def test_string_is_coerced_to_a_list(self):
        case = parse_cases([{**VALID, "required_keywords": "13 months"}])[0]
        assert case.required_keywords == ["13 months"]

    def test_refusal_case_needs_no_expected_chunks(self):
        case = parse_cases(
            [{"id": "r", "question": "capital of France?", "should_refuse": True}]
        )[0]
        assert case.should_refuse
        assert case.expected_chunks == []


class TestValidation:
    def test_rejects_unknown_field(self):
        """A typo'd field must be an error, not a silently ignored assertion."""
        with pytest.raises(DatasetError, match="unknown field"):
            parse_cases([{**VALID, "required_keyword": ["x"]}])

    def test_rejects_missing_id(self):
        with pytest.raises(DatasetError, match="missing a non-empty 'id'"):
            parse_cases([{k: v for k, v in VALID.items() if k != "id"}])

    def test_rejects_empty_question(self):
        with pytest.raises(DatasetError, match="question"):
            parse_cases([{**VALID, "question": "   "}])

    def test_rejects_duplicate_ids(self):
        """Case IDs are the join key for the regression diff."""
        with pytest.raises(DatasetError, match="duplicate case id"):
            parse_cases([VALID, VALID])

    def test_rejects_non_boolean_should_refuse(self):
        with pytest.raises(DatasetError, match="should_refuse"):
            parse_cases([{**VALID, "should_refuse": "yes"}])

    def test_rejects_refusal_case_with_expected_chunks(self):
        with pytest.raises(DatasetError, match="must not declare expected_chunks"):
            parse_cases([{**VALID, "should_refuse": True}])

    def test_rejects_answer_case_without_expected_chunks(self):
        """Otherwise retrieval quality is not asserted at all for that case."""
        with pytest.raises(DatasetError, match="at least one expected chunk"):
            parse_cases([{k: v for k, v in VALID.items() if k != "expected_chunks"}])

    def test_rejects_empty_dataset(self):
        with pytest.raises(DatasetError, match="no cases"):
            parse_cases([])


class TestFileLoading:
    def test_loads_yaml(self, tmp_path):
        import yaml

        path = tmp_path / "golden.yaml"
        path.write_text(yaml.safe_dump({"cases": [VALID]}), encoding="utf-8")
        assert len(load_dataset(path)) == 1

    def test_loads_a_bare_yaml_list(self, tmp_path):
        import yaml

        path = tmp_path / "golden.yaml"
        path.write_text(yaml.safe_dump([VALID]), encoding="utf-8")
        assert len(load_dataset(path)) == 1

    def test_loads_jsonl(self, tmp_path):
        path = tmp_path / "golden.jsonl"
        path.write_text(json.dumps(VALID) + "\n", encoding="utf-8")
        assert len(load_dataset(path)) == 1

    def test_jsonl_skips_blank_and_comment_lines(self, tmp_path):
        path = tmp_path / "golden.jsonl"
        path.write_text(f"# a comment\n\n{json.dumps(VALID)}\n", encoding="utf-8")
        assert len(load_dataset(path)) == 1

    def test_jsonl_error_reports_the_line_number(self, tmp_path):
        path = tmp_path / "golden.jsonl"
        path.write_text(json.dumps(VALID) + "\n{not json}\n", encoding="utf-8")
        with pytest.raises(DatasetError, match=":2:"):
            load_dataset(path)

    def test_missing_file(self, tmp_path):
        with pytest.raises(DatasetError, match="not found"):
            load_dataset(tmp_path / "nope.yaml")

    def test_unsupported_extension(self, tmp_path):
        path = tmp_path / "golden.csv"
        path.write_text("id,question\n", encoding="utf-8")
        with pytest.raises(DatasetError, match="unsupported dataset format"):
            load_dataset(path)


class TestFingerprint:
    def test_is_stable(self):
        cases = parse_cases([VALID])
        assert dataset_fingerprint(cases) == dataset_fingerprint(cases)

    def test_changes_when_a_question_changes(self):
        original = parse_cases([VALID])
        modified = parse_cases([{**VALID, "question": "A different question?"}])
        assert dataset_fingerprint(original) != dataset_fingerprint(modified)

    def test_changes_when_an_assertion_changes(self):
        original = parse_cases([VALID])
        modified = parse_cases([{**VALID, "required_keywords": ["90 days"]}])
        assert dataset_fingerprint(original) != dataset_fingerprint(modified)


class TestShippedGoldenSet:
    """The real dataset must stay consistent with the real corpus.

    This is the test that catches someone renaming a section heading in a sample
    document without updating the dataset that references it.
    """

    def test_loads(self, config, project_root):
        cases = load_dataset(project_root / config.dataset_path)
        assert len(cases) >= 10

    def test_every_expected_chunk_exists_in_the_corpus(self, config, project_root, pipeline):
        cases = load_dataset(project_root / config.dataset_path)
        available = set(pipeline.chunk_ids())
        missing = {
            f"{case.id} -> {chunk}"
            for case in cases
            for chunk in case.expected_chunks
            if chunk not in available
        }
        assert not missing, f"dataset references chunk ids that do not exist: {sorted(missing)}"

    def test_has_refusal_coverage(self, config, project_root):
        cases = load_dataset(project_root / config.dataset_path)
        assert any(case.should_refuse for case in cases), (
            "a RAG golden set without refusal cases cannot detect a system that "
            "answers everything confidently"
        )

    def test_has_multiple_categories(self, config, project_root):
        cases = load_dataset(project_root / config.dataset_path)
        assert len({case.category for case in cases}) >= 3
