from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ticktide.prolog_adapter import (
    PrologTransformer,
    legacy_json_to_prolog_terms,
    parse_prolog_edges,
    prolog_rule_sha256,
)


def test_original_prolog_rule_hash_is_preserved():
    assert prolog_rule_sha256(ROOT / "prolog/btsg.pl") == "98f88f8cc0a8e81b8f3301cf73542c4579023ae10038ed63e77edff83ea62ab0"


def test_parse_prolog_edges():
    parsed = parse_prolog_edges("[edge(b,a,sequence),edge(c,b,blackboard(result))]")
    assert parsed == [("b", "a", "sequence"), ("c", "b", "blackboard(result)")]


def test_legacy_json_to_terms_unwraps_repeat():
    data = {
        "trees": [{
            "root": "R",
            "nodes": {
                "R": {"name": "Sequence", "children": ["A", "REP"], "properties": {}},
                "A": {"name": "Alpha", "properties": {"bbwrite": "x"}},
                "REP": {"name": "RepeatUntilSuccess", "child": "B", "properties": {}},
                "B": {"name": "Beta", "properties": {"bbread": "x"}},
            },
        }]
    }
    root, keys = legacy_json_to_prolog_terms(data)
    assert root == "seq([task(alpha, [param(x, write(x))]),task(beta, [param(x, read(x))])])"
    assert keys == ["x"]


@pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog not installed")
def test_swipl_can_load_existing_rule():
    transformer = PrologTransformer(ROOT / "prolog/btsg.pl")
    transformer.assert_available()
