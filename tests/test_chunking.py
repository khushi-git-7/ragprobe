"""Unit tests for chunking.

Chunk IDs are the join key between the corpus and the golden dataset, so their
stability is a correctness property, not a cosmetic one. Several tests below exist
purely to pin that stability.
"""

from __future__ import annotations

import pytest

from ragprobe.config import ChunkConfig, ConfigError
from ragprobe.pipeline.chunking import Chunk, chunk_document, slugify

DOC = """# Sample Policy

Intro paragraph that is long enough to survive the minimum word filter easily.

## First Section

The first section body text goes here and has a reasonable number of words in it.

## Second Section

The second section body text is also present and similarly sized for testing.
"""


class TestSlugify:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Data Retention", "data-retention"),
            ("  Paid Time Off  ", "paid-time-off"),
            ("API Rate Limits", "api-rate-limits"),
            ("Section 1.2: Scope", "section-1-2-scope"),
            ("Ends with punctuation!!!", "ends-with-punctuation"),
        ],
    )
    def test_slugs(self, text, expected):
        assert slugify(text) == expected

    def test_empty_falls_back(self):
        assert slugify("   ") == "section"
        assert slugify("!!!") == "section"


class TestHeadingChunking:
    def test_produces_one_chunk_per_h2_plus_intro(self):
        chunks = chunk_document("sample", DOC)
        assert [chunk.chunk_id for chunk in chunks] == [
            "sample#intro",
            "sample#first-section",
            "sample#second-section",
        ]

    def test_h1_is_title_not_a_chunk(self):
        chunks = chunk_document("sample", DOC)
        assert all(chunk.doc_title == "Sample Policy" for chunk in chunks)
        # The literal "# Sample Policy" line must not appear in any chunk body.
        assert all("# Sample Policy" not in chunk.text for chunk in chunks)

    def test_heading_is_recorded(self):
        chunks = {chunk.chunk_id: chunk for chunk in chunk_document("sample", DOC)}
        assert chunks["sample#first-section"].heading == "First Section"

    def test_order_is_sequential(self):
        chunks = chunk_document("sample", DOC)
        assert [chunk.order for chunk in chunks] == [0, 1, 2]

    def test_chunk_ids_are_stable_across_calls(self):
        first = [chunk.chunk_id for chunk in chunk_document("sample", DOC)]
        second = [chunk.chunk_id for chunk in chunk_document("sample", DOC)]
        assert first == second

    def test_chunk_ids_survive_max_words_change(self):
        """The whole point of heading anchors: re-tuning chunk size must not
        invalidate every expected_chunks entry in the golden dataset."""
        small = chunk_document("sample", DOC, ChunkConfig(max_words=60))
        large = chunk_document("sample", DOC, ChunkConfig(max_words=400))
        assert [chunk.chunk_id for chunk in small] == [chunk.chunk_id for chunk in large]

    def test_source_line_wrapping_is_collapsed(self):
        wrapped = "## Heading\n\nA sentence that the author\nhard wrapped across lines here.\n"
        chunk = chunk_document("doc", wrapped)[0]
        assert "\n" not in chunk.text
        assert "author hard wrapped" in chunk.text

    def test_short_sections_are_dropped(self):
        doc = "## Tiny\n\nToo short.\n\n## Real Section\n\n" + " ".join(["word"] * 40)
        ids = [chunk.chunk_id for chunk in chunk_document("doc", doc, ChunkConfig(min_words=5))]
        assert "doc#tiny" not in ids
        assert "doc#real-section" in ids

    def test_duplicate_headings_do_not_collide(self):
        body = " ".join(["filler"] * 20)
        doc = f"## Scope\n\n{body}\n\n## Scope\n\n{body}\n"
        ids = [chunk.chunk_id for chunk in chunk_document("doc", doc)]
        assert ids == ["doc#scope", "doc#scope-2"]
        assert len(set(ids)) == len(ids)

    def test_document_without_headings_yields_intro_only(self):
        chunks = chunk_document("doc", "Just a paragraph with enough words to be kept here.")
        assert [chunk.chunk_id for chunk in chunks] == ["doc#intro"]

    def test_empty_document_yields_nothing(self):
        assert chunk_document("doc", "") == []


class TestLongSectionSplitting:
    def test_long_section_splits_with_suffixes(self):
        body = " ".join(f"w{index}" for index in range(300))
        chunks = chunk_document(
            "doc", f"## Big\n\n{body}", ChunkConfig(max_words=100, overlap_words=20)
        )
        ids = [chunk.chunk_id for chunk in chunks]
        assert ids[0] == "doc#big", "the first part must keep the bare anchor"
        assert all(part.startswith("doc#big~") for part in ids[1:])
        assert len(ids) > 1

    def test_split_parts_overlap(self):
        body = " ".join(f"w{index}" for index in range(300))
        chunks = chunk_document(
            "doc", f"## Big\n\n{body}", ChunkConfig(max_words=100, overlap_words=20)
        )
        first_words = chunks[0].text.split()
        second_words = chunks[1].text.split()
        assert first_words[-20:] == second_words[:20]

    def test_no_words_are_lost(self):
        body = " ".join(f"w{index}" for index in range(250))
        chunks = chunk_document(
            "doc", f"## Big\n\n{body}", ChunkConfig(max_words=100, overlap_words=20)
        )
        recovered = set()
        for chunk in chunks:
            recovered.update(chunk.text.split())
        assert recovered == set(body.split())

    def test_anchor_property_strips_split_suffix(self):
        chunk = Chunk("doc#big~3", "doc", "Doc", "Big", "text", 2)
        assert chunk.anchor == "doc#big"


class TestFixedStrategy:
    def test_fixed_strategy_uses_positional_ids(self):
        body = " ".join(f"w{index}" for index in range(250))
        chunks = chunk_document(
            "doc", f"## A\n\n{body}", ChunkConfig(strategy="fixed", max_words=100, overlap_words=20)
        )
        assert [chunk.chunk_id for chunk in chunks][0] == "doc#w1"
        assert all(chunk.chunk_id.startswith("doc#w") for chunk in chunks)


class TestConfigValidation:
    def test_rejects_unknown_strategy(self):
        with pytest.raises(ConfigError):
            chunk_document("doc", DOC, ChunkConfig(strategy="semantic"))

    def test_rejects_overlap_larger_than_window(self):
        with pytest.raises(ConfigError):
            chunk_document("doc", DOC, ChunkConfig(max_words=50, overlap_words=50))

    def test_rejects_zero_max_words(self):
        with pytest.raises(ConfigError):
            chunk_document("doc", DOC, ChunkConfig(max_words=0))
