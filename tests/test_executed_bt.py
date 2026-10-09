from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ticktide.executed_bt import build_executed_bt, build_executed_path_bt
from ticktide.models import Status, TraceEvent
from ticktide.prolog_adapter import to_prolog_compatible_bt
from ticktide.experiment import load_task_profiles


def event(i, node_id, name, kind, status=Status.SUCCESS, attempt=None):
    return TraceEvent(1, i, node_id, name, kind, status, attempt, 0, "test")


def load_tree():
    return json.loads((ROOT / "config/generic_bt.json").read_text())


def profiles():
    return load_task_profiles(ROOT / "config/task_profiles.csv")


def test_a_direct_execution_pruned_audit_tree_keeps_only_a_branch():
    trace = [
        event(1, "F1", "Initialize", "action"),
        event(2, "F2", "Preprocess", "action"),
        event(3, "C1", "A Applicable?", "condition"),
        event(4, "F3", "A Prepare", "action"),
        event(5, "F4", "A Execute", "action", attempt=1),
        event(6, "C2", "A Result OK?", "condition"),
        event(7, "F5", "A Commit", "action"),
        event(8, "F11", "Consolidate", "action"),
        event(9, "F12", "Finalize", "action"),
    ]
    executed = build_executed_bt(load_tree(), trace, 1)
    assert "SEQ_A" in executed["nodes"]
    assert "SEQ_B" not in executed["nodes"]
    assert "SEQ_R" not in executed["nodes"]


def test_executed_path_bt_is_exact_resolved_service_order():
    # A does work, then fails validation; B succeeds.
    trace = [
        event(1, "F1", "Initialize", "action"),
        event(2, "F2", "Preprocess", "action"),
        event(3, "C1", "A Applicable?", "condition"),
        event(4, "F3", "A Prepare", "action"),
        event(5, "F4", "A Execute", "action", Status.SUCCESS, attempt=1),
        event(6, "C2", "A Result OK?", "condition", Status.FAILURE),
        event(7, "C3", "B Applicable?", "condition"),
        event(8, "F6", "B Prepare", "action"),
        event(9, "F7", "B Execute", "action", Status.SUCCESS, attempt=1),
        event(10, "C4", "B Result OK?", "condition"),
        event(11, "F8", "B Commit", "action"),
        event(12, "F11", "Consolidate", "action"),
        event(13, "F12", "Finalize", "action"),
    ]
    path_bt = build_executed_path_bt(load_tree(), trace, 1)
    assert path_bt["nodes"][path_bt["root"]]["children"] == [
        "F1", "F2", "F3", "F4", "F6", "F7", "F8", "F11", "F12"
    ]
    prolog_input = to_prolog_compatible_bt(path_bt, profiles())
    root = prolog_input["trees"][0]["nodes"]["EXEC_PATH_ROOT"]
    assert root["name"] == "Sequence"
    assert root["children"] == [
        "F1", "F2", "F3", "F4", "F6", "F7", "F8", "F11", "F12"
    ]


def test_b_failure_then_recovery_has_no_direct_b_to_consolidate_path():
    trace = [
        event(1, "F1", "Initialize", "action"),
        event(2, "F2", "Preprocess", "action"),
        event(3, "C1", "A Applicable?", "condition", Status.FAILURE),
        event(4, "C3", "B Applicable?", "condition"),
        event(5, "F6", "B Prepare", "action"),
        event(6, "F7", "B Execute", "action", Status.FAILURE, attempt=1),
        event(7, "F7", "B Execute", "action", Status.FAILURE, attempt=2),
        event(8, "F9", "Recovery Prepare", "action"),
        event(9, "F10", "Recovery Execute", "action"),
        event(10, "F11", "Consolidate", "action"),
        event(11, "F12", "Finalize", "action"),
    ]
    path_bt = build_executed_path_bt(load_tree(), trace, 1)
    # Retry duplicates are collapsed structurally but retained as multiplicity.
    assert path_bt["nodes"][path_bt["root"]]["children"] == [
        "F1", "F2", "F6", "F7", "F9", "F10", "F11", "F12"
    ]
    assert path_bt["execution_metadata"]["action_invocation_counts"]["F7"] == 2


def test_retry_is_one_path_service_but_two_runtime_invocations():
    trace = [
        event(1, "F1", "Initialize", "action"),
        event(2, "F2", "Preprocess", "action"),
        event(3, "C1", "A Applicable?", "condition"),
        event(4, "F3", "A Prepare", "action"),
        event(5, "F4", "A Execute", "action", Status.FAILURE, attempt=1),
        event(6, "F4", "A Execute", "action", Status.SUCCESS, attempt=2),
        event(7, "C2", "A Result OK?", "condition"),
        event(8, "F5", "A Commit", "action"),
        event(9, "F11", "Consolidate", "action"),
        event(10, "F12", "Finalize", "action"),
    ]
    path_bt = build_executed_path_bt(load_tree(), trace, 1)
    children = path_bt["nodes"][path_bt["root"]]["children"]
    assert children.count("F4") == 1
    assert path_bt["execution_metadata"]["action_invocation_counts"]["F4"] == 2
