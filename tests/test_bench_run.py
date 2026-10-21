"""The benchmark runner: manifest, reproducibility, response cache, committed run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragprobe.bench.cache import CachingVictim
from ragprobe.bench.run import render_markdown, run_bench, select_attacks
from ragprobe.bench.dataset import load_jsonl
from ragprobe.security.victims import get_victim

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "datasets" / "bench" / "v1" / "attacks.jsonl"


def _run(cache=None):
    return run_bench(CAT, get_victim("simulated"), split="test",
                     defenses=["none", "layered"], base_dir=ROOT, cache_dir=cache)


class TestSelect:
    def test_selects_only_runnable_attacks_in_the_split(self):
        items = load_jsonl(CAT)
        test = select_attacks(items, "test")
        assert test and all(i.kind == "attack" and i.split == "test" for i in test)
        assert len(select_attacks(items, None)) >= len(test)  # no filter >= one split


class TestManifest:
    def test_manifest_records_how_the_run_was_made(self):
        res = _run()
        m = res["manifest"]
        for key in ("ragprobe_version", "bench_version", "catalogue_fingerprint",
                    "split", "attack_count", "defenses", "seed", "victim", "created"):
            assert key in m
        assert m["split"] == "test" and m["attack_count"] > 0
        assert m["victim"]["name"] == "simulated"
        assert "by_defense" in res["summary"]

    def test_run_is_reproducible(self):
        a, b = _run(), _run()
        assert a["manifest"]["catalogue_fingerprint"] == b["manifest"]["catalogue_fingerprint"]
        # the measured rates are identical on a deterministic victim
        assert a["summary"]["by_defense"]["none"]["asr"] == \
               b["summary"]["by_defense"]["none"]["asr"]

    def test_empty_split_is_an_error(self, tmp_path):
        # a catalogue with only probes has no runnable attacks
        from ragprobe.bench.dataset import save_jsonl
        probes = [i for i in load_jsonl(CAT) if i.kind == "probe"][:5]
        thin = save_jsonl(probes, tmp_path / "thin.jsonl")
        with pytest.raises(ValueError):
            run_bench(thin, get_victim("simulated"), split="test", base_dir=ROOT)


class TestCache:
    def test_second_run_is_served_entirely_from_cache(self, tmp_path):
        cache = tmp_path / "cache"
        first = _run(cache=cache)
        assert first["manifest"]["cache"]["misses"] > 0  # cold cache: real calls
        second = _run(cache=cache)
        assert second["manifest"]["cache"]["misses"] == 0  # warm cache: no new calls
        assert second["manifest"]["cache"]["hits"] > 0

    def test_caching_victim_replays_a_stored_reply(self, tmp_path):
        calls = {"n": 0}
        inner = get_victim("simulated")
        original = inner.respond

        def counting(messages, tools=None):
            calls["n"] += 1
            return original(messages, tools)

        inner.respond = counting
        cv = CachingVictim(inner, tmp_path / "c")
        msg = [{"role": "user", "content": "hello"}]
        cv.respond(msg)
        cv.respond(msg)
        assert calls["n"] == 1 and cv.stats() == {"hits": 1, "misses": 1}


class TestReport:
    def test_markdown_has_the_manifest_and_a_defence_table(self):
        md = render_markdown(_run())
        assert "Bench v1 run" in md and "Attack-success" in md
        assert "Manifest" in md and "fingerprint" in md


class TestCommittedBaseline:
    def test_committed_run_reproduces(self):
        committed = json.loads((ROOT / "results" / "bench-v1-simulated.json").read_text(encoding="utf-8"))
        fresh = _run()
        assert committed["manifest"]["catalogue_fingerprint"] == \
               fresh["manifest"]["catalogue_fingerprint"]
        for defence in ("none", "layered"):
            assert committed["summary"]["by_defense"][defence]["asr"] == \
                   fresh["summary"]["by_defense"][defence]["asr"]
