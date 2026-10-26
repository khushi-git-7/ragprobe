"""Bench v2 is v1 plus new families; v1 itself must never move."""

from pathlib import Path

from ragprobe.resources import bundled_path
from ragprobe.bench.build import build_v1, build_v2
from ragprobe.bench.dataset import load_jsonl
from ragprobe.bench.generate_v2 import WRAPPERS_V2, generate_v2_attacks
from ragprobe.bench.run import run_bench, select_attacks
from ragprobe.bench.schema import TECHNIQUES, to_attack
from ragprobe.security.canary import make_canaries
from ragprobe.security.victims import get_victim

ROOT = Path(__file__).resolve().parents[1]
V1 = bundled_path("bench/v1/attacks.jsonl")
V2 = bundled_path("bench/v2/attacks.jsonl")


def test_every_new_family_is_in_the_documented_vocabulary():
    assert set(WRAPPERS_V2) <= set(TECHNIQUES)


def test_families_cover_four_languages_and_two_goals():
    items = generate_v2_attacks()
    assert len(items) == len(WRAPPERS_V2) * 4 * 2
    assert {i.language for i in items} == {"en", "de", "es", "fr"}
    assert {i.goal for i in items} == {"say_marker", "leak_secret"}
    assert len({i.id for i in items}) == len(items)


def test_every_new_attack_renders_with_canaries():
    for item in generate_v2_attacks():
        attack = to_attack(item)
        text = attack.rendered_payload(make_canaries(3, attack.id, 0))
        assert "{marker" not in text
        if item.goal == "say_marker":
            assert "ZQ" in text


def test_v2_keeps_every_v1_item_and_its_split():
    v1 = {i.id: i for i in build_v1()}
    v2 = {i.id: i for i in build_v2()}
    assert set(v1) < set(v2)
    for id_, item in v1.items():
        assert v2[id_].to_dict() == item.to_dict()


def test_committed_files_match_a_rebuild():
    assert [i.to_dict() for i in load_jsonl(V1)] == [i.to_dict() for i in build_v1()]
    assert [i.to_dict() for i in load_jsonl(V2)] == [i.to_dict() for i in build_v2()]


def test_v2_has_more_runnable_attacks_than_v1():
    assert len(select_attacks(load_jsonl(V2))) == len(select_attacks(load_jsonl(V1))) + 56


def test_a_v2_run_records_its_version_and_all_attacks_land_on_the_obedient_victim():
    result = run_bench(V2, get_victim("simulated"), split=None, defenses=["none"], base_dir=ROOT)
    assert result["manifest"]["bench_version"] == "v2"
    assert result["manifest"]["attack_count"] == 138
    assert result["summary"]["by_defense"]["none"]["asr"] > 0.8
