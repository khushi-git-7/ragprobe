"""Reading a garak report and lining it up with RAGProbe's results by OWASP risk.

The report below has the shape garak 0.17 writes (``report.jsonl``): an ``init``
line, the run's setup, a ``plugin_cache`` with each probe's tags, then one
``eval`` line per probe and detector. It is trimmed to the fields RAGProbe reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragprobe.cli import EXIT_OK, EXIT_USAGE, main
from ragprobe.security.garak_report import (
    GarakReportError, combine, owasp_risks, read_report, render_markdown, summarise)

TAGS = {
    # web_injection: v1.1 LLM02 (insecure output handling) and LLM06 (sensitive information)
    "web_injection.TaskXSS": ["avid-effect:security:S0301", "owasp:llm02", "owasp:llm06"],
    "web_injection.MarkdownImageExfil": ["owasp:llm02", "owasp:llm06"],
    "dan.Dan_11_0": ["owasp:llm01"],
    "malwaregen.Evasion": ["owasp:llm07"],   # no 2025 entry
    "lmrc.Profanity": ["avid-effect:ethics:E0301"],   # no OWASP tag
}


def _report(tmp_path: Path, evals, extra_lines=()) -> Path:
    lines = [
        {"entry_type": "start_run setup", "plugins.target_type": "openai",
         "plugins.target_name": "gpt-4o-mini"},
        {"entry_type": "init", "garak_version": "0.17.2", "start_time": "2026-11-11T19:44:31",
         "run": "1f72424d"},
        {"entry_type": "plugin_cache", "plugin_cache": {"probes": {
            f"probes.{name}": {"tags": tags} for name, tags in TAGS.items()}}},
        *[{"entry_type": "eval", **e} for e in evals],
        {"entry_type": "completion", "end_time": "2026-11-11T19:50:00", "run": "1f72424d"},
    ]
    path = tmp_path / "garak.report.jsonl"
    path.write_text("\n".join([json.dumps(x) for x in lines] + list(extra_lines)) + "\n",
                    encoding="utf-8")
    return path


def _eval(probe, detector, fails, total, nones=0):
    return {"probe": probe, "detector": detector, "passed": total - fails, "fails": fails,
            "nones": nones, "total_evaluated": total, "total_processed": total + nones}


def test_garaks_v11_tags_map_to_the_2025_risks():
    assert owasp_risks(["owasp:llm02", "owasp:llm06"]) == ["LLM05", "LLM02"]
    assert owasp_risks(["owasp:llm01", "OWASP:LLM08", "owasp:llm09"]) == ["LLM01", "LLM06", "LLM09"]
    assert owasp_risks(["owasp:llm07", "owasp:llm10"]) == ["v1.1-LLM07", "v1.1-LLM10"]
    assert owasp_risks(["avid-effect:security:S0301", "owasp:llm99", 5]) == []


def test_a_probe_counts_once_by_its_worst_detector(tmp_path):
    """Two detectors read the same 12 outputs: the probe is 6/12, not 6/24 or 12/24."""
    summary = summarise(read_report(_report(tmp_path, [
        _eval("web_injection.MarkdownImageExfil", "web_injection.MarkdownExfilBasic", 6, 12),
        _eval("web_injection.MarkdownImageExfil", "web_injection.MarkdownExfilContent", 2, 12),
        _eval("web_injection.TaskXSS", "web_injection.XSS", 85, 85),
        _eval("dan.Dan_11_0", "dan.DAN", 0, 10, nones=3),
        _eval("malwaregen.Evasion", "malwaregen.AnyCode", 4, 8),
        _eval("lmrc.Profanity", "unsafe_content.SurgeProfanityAnimalReferences", 1, 4),
    ])))
    assert summary["by_owasp"]["LLM02"]["hits"] == 91 and summary["by_owasp"]["LLM02"]["total"] == 97
    assert summary["by_owasp"]["LLM05"]["total"] == 97   # the same probes, both tags
    assert summary["by_owasp"]["LLM01"] == {**summary["by_owasp"]["LLM01"], "hits": 0, "total": 10}
    assert summary["by_owasp"]["v1.1-LLM07"]["name"] == "Insecure Plugin Design (OWASP v1.1)"
    assert (summary["untagged"]["hits"], summary["untagged"]["total"]) == (1, 4)
    exfil = next(p for p in summary["probes"] if p["probe"] == "web_injection.MarkdownImageExfil")
    assert (exfil["detector"], exfil["hits"], exfil["total"]) == (
        "web_injection.MarkdownExfilBasic", 6, 12)
    assert summary["probes"][0]["probe"] == "web_injection.TaskXSS"   # most hits first
    assert summary["target"] == "openai gpt-4o-mini" and summary["garak_version"] == "0.17.2"


def test_an_older_report_without_fails_and_a_bad_line_are_read(tmp_path):
    """garak before 0.13 wrote passed and total only; a line that isn't JSON is counted."""
    path = _report(tmp_path, [{"probe": "dan.Dan_11_0", "detector": "detector.dan.DAN",
                               "passed": 7, "total": 10}], extra_lines=["{not json"])
    report = read_report(path)
    assert report["rows"][0]["hits"] == 3 and report["rows"][0]["detector"] == "dan.DAN"
    assert report["malformed"] == 1


def test_a_report_without_results_is_refused(tmp_path):
    with pytest.raises(GarakReportError, match="no garak results"):
        read_report(_report(tmp_path, []))
    path = tmp_path / "x.jsonl"
    path.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(GarakReportError, match="cannot read"):
        read_report(path)


RAGPROBE = {
    "victim": {"name": "simulated", "model": "gullible-v1"},
    "summary": {
        "by_defense": {"none": {"asr": 1.0}, "layered": {"asr": 0.1}},
        "by_defense_owasp": {
            "none": {"LLM01": {"asr": 1.0, "trials": 10}, "LLM02": {"asr": 0.5, "trials": 4}},
            "layered": {"LLM01": {"asr": 0.1, "trials": 10}, "LLM02": {"asr": 0.0, "trials": 4}},
        },
    },
}


def test_garak_and_ragprobe_side_by_side(tmp_path):
    summary = summarise(read_report(_report(tmp_path, [
        _eval("web_injection.TaskXSS", "web_injection.XSS", 5, 10)])))
    rows = {r["owasp"]: r for r in combine(summary, RAGPROBE)["rows"]}
    assert rows["LLM02"]["garak"]["asr"] == 0.5 and rows["LLM02"]["ragprobe"]["grade"] == "A"
    assert rows["LLM05"]["ragprobe"] is None   # garak probed it, RAGProbe didn't
    assert rows["LLM01"]["garak"] is None      # and the other way round
    md = render_markdown(summary, combine(summary, RAGPROBE))
    assert "| LLM01 | Prompt Injection | - | not probed | 100% | 10% | B |" in md
    assert "| LLM05 | Improper Output Handling | 5/10 | 50% (24%-76%) | - | - | not probed |" in md


def test_the_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    report = _report(tmp_path, [_eval("web_injection.TaskXSS", "web_injection.XSS", 85, 85)])
    (tmp_path / "rp.json").write_text(json.dumps(RAGPROBE), encoding="utf-8")
    code = main(["security", "garak", str(report), "--with", "rp.json", "--md"])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "garak 0.17.2 against openai gpt-4o-mini" in out
    saved = json.loads((tmp_path / "reports" / "garak.json").read_text(encoding="utf-8"))
    assert saved["garak"]["by_owasp"]["LLM02"]["hits"] == 85
    assert saved["combined"]["ragprobe_defense"] == "layered"
    assert (tmp_path / "reports" / "garak.md").read_text(encoding="utf-8").startswith(
        "# garak results, by OWASP risk")
    (tmp_path / "other.json").write_text(json.dumps({"runs": []}), encoding="utf-8")
    code = main(["security", "garak", str(report), "--with", "other.json"])
    err = capsys.readouterr().err
    assert code == EXIT_USAGE and err.startswith("error: ") and "security results JSON" in err
