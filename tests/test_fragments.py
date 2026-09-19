"""Tests for the HTML fragments shared by the run report and the dashboard.

Both pages render checks and retrieved chunks through these functions, so a
mistake here shows up twice. The escaping contract in particular is pinned:
every string that comes from a results file passes through ``esc``.
"""

from __future__ import annotations

from ragprobe.reporting.fragments import check_pill, checks_table, chunk_list, esc, fmt_pct, fmt_score


class TestFormatting:
    def test_esc_handles_none_quotes_and_tags(self):
        assert esc(None) == ""
        assert esc('<a href="x">&</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;"

    def test_numbers_render_with_n_a_for_missing(self):
        assert fmt_score(0.87654) == "0.877"
        assert fmt_score(0.5, 1) == "0.5"
        assert fmt_score(None) == "n/a"
        assert fmt_pct(0.875) == "87.5%"
        assert fmt_pct(None) == "n/a"


class TestChecks:
    def test_pill_reflects_applicability_before_verdict(self):
        assert "skip" in check_pill({"applicable": False, "passed": True})
        assert "pass" in check_pill({"passed": True})
        assert "fail" in check_pill({"passed": False})

    def test_table_marks_advisory_checks_and_escapes_detail(self):
        out = checks_table([
            {"name": "fuzzy_match", "passed": False, "score": 0.4, "detail": "a < b", "metadata": {"advisory": True}},
            {"name": "keyword_presence", "passed": True, "score": 1.0, "detail": ""},
        ])
        assert out.count("<tr>") == 3  # header plus two rows
        assert "fuzzy_match <span class=\"muted\">(advisory)</span>" in out
        assert "keyword_presence <span" not in out
        assert "a &lt; b" in out

    def test_empty_checks_explain_why(self):
        assert "errored before evaluation" in checks_table([])


class TestChunks:
    def test_matches_on_the_anchor_and_lists_what_was_missed(self):
        retrieved = [
            {"chunk_id": "refund_policy#annual~abc123", "rank": 1, "score": 0.9, "text": "Annual plans..."},
            {"chunk_id": "product_faq#tiers~def456", "rank": 2, "score": 0.5, "text": "<b>Growth</b>"},
        ]
        out = chunk_list(retrieved, ["refund_policy#annual", "support_sla#sev1"])
        assert out.count('class="chunk expected"') == 1
        assert out.count("not in golden set") == 1
        assert "Expected but not retrieved: <code>support_sla#sev1</code>" in out
        assert "&lt;b&gt;Growth&lt;/b&gt;" in out

    def test_nothing_retrieved(self):
        assert "Nothing was retrieved" in chunk_list([], ["x"])
