from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Dict, Iterable, Optional, Set

from .models import TraceEvent


def build_executed_bt(full_spec: Dict[str, Any], trace: Iterable[TraceEvent], run_id: int) -> Dict[str, Any]:
    """Prune the original BT to the leaves visited in one execution.

    This is the *audit/explanation* representation of the run. Conditions remain
    because they explain why the traversal took the observed path. Composite and
    decorator ancestors are retained so the result is still recognisably a pruned
    version of the original Behavior Tree.

    IMPORTANT: this pruned tree is not used directly as Prolog input. Static
    selector exit-set semantics can create impossible post-failure edges once an
    execution has already resolved which branch failed/succeeded. The Prolog input
    is instead produced from ``build_executed_path_bt`` below.
    """
    trace = list(trace)
    visited_leaf_ids: Set[str] = {event.node_id for event in trace}
    source_nodes = full_spec["nodes"]
    kept_nodes: Dict[str, Dict[str, Any]] = {}

    def prune(node_id: str) -> Optional[str]:
        raw = source_nodes[node_id]
        node_type = raw["type"].lower()

        if node_type in {"action", "condition"}:
            if node_id not in visited_leaf_ids:
                return None
            kept_nodes[node_id] = deepcopy(raw)
            return node_id

        if node_type in {"sequence", "fallback"}:
            kept_children = []
            for child_id in raw.get("children", []):
                kept = prune(child_id)
                if kept is not None:
                    kept_children.append(kept)
            if not kept_children:
                return None
            copied = deepcopy(raw)
            copied["children"] = kept_children
            kept_nodes[node_id] = copied
            return node_id

        if node_type == "retry":
            kept_child = prune(raw["child"])
            if kept_child is None:
                return None
            copied = deepcopy(raw)
            copied["child"] = kept_child
            kept_nodes[node_id] = copied
            return node_id

        raise ValueError(f"Unsupported node type {node_type!r} for {node_id}")

    root_id = prune(full_spec["root"])
    if root_id is None:
        raise ValueError("Execution trace contains no node reachable from the BT root")

    invocation_counts = Counter(
        event.node_id for event in trace if event.node_kind == "action"
    )
    return {
        "name": f"Executed BT - run {run_id}",
        "source_tree_name": full_spec.get("name", "Generic BT"),
        "source_run_id": run_id,
        "root": root_id,
        "nodes": kept_nodes,
        "execution_metadata": {
            "visited_leaf_ids": [event.node_id for event in trace],
            "action_invocation_counts": dict(invocation_counts),
        },
    }


def build_executed_path_bt(
    full_spec: Dict[str, Any], trace: Iterable[TraceEvent], run_id: int
) -> Dict[str, Any]:
    """Represent the *resolved executed service path* as a Behavior Tree.

    The professor's requested pipeline is:

        execution -> executed path as BT -> existing Prolog BT->SG rule -> executed SG

    Once a run has happened, selector/fallback alternatives are no longer
    hypothetical: the runtime trace tells us the exact chronological service path.
    Feeding a merely-pruned original Fallback tree to a static Prolog transform can
    incorrectly treat failed branches as possible exits and connect them directly
    to downstream services. Therefore this special BT encodes the resolved path as
    a Sequence of the Action services that actually executed.

    Consecutive duplicate action ids caused by bounded Retry are collapsed to one
    structural service node. Their multiplicity remains in ``invocation_counts``
    and is used for workload accounting. This keeps topology and runtime workload
    intentionally separate.
    """
    trace = list(trace)
    source_nodes = full_spec["nodes"]

    action_events = [event for event in trace if event.node_kind == "action"]
    if not action_events:
        raise ValueError("Execution trace contains no executed actions")

    # Service-level path: retries of the same service do not create a second SG node.
    path_action_ids: list[str] = []
    for event in action_events:
        if not path_action_ids or path_action_ids[-1] != event.node_id:
            path_action_ids.append(event.node_id)

    # Current generic benchmark only repeats a service consecutively via Retry.
    # Guard against silently misrepresenting a future loop that revisits the same
    # service after other services have run.
    if len(set(path_action_ids)) != len(path_action_ids):
        raise ValueError(
            "The executed path revisits a service non-consecutively. The current "
            "generic path-BT encoder supports consecutive Retry multiplicity only; "
            "use occurrence-level path nodes before evaluating looped workflows."
        )

    invocation_counts = Counter(event.node_id for event in action_events)
    nodes: Dict[str, Dict[str, Any]] = {}
    for action_id in path_action_ids:
        raw = source_nodes[action_id]
        if raw["type"].lower() != "action":
            raise ValueError(f"Expected action node for {action_id}")
        nodes[action_id] = deepcopy(raw)

    path_root = "EXEC_PATH_ROOT"
    nodes[path_root] = {
        "type": "sequence",
        "name": "Executed Service Path",
        "children": path_action_ids,
    }

    return {
        "name": f"Executed Path BT - run {run_id}",
        "source_tree_name": full_spec.get("name", "Generic BT"),
        "source_run_id": run_id,
        "root": path_root,
        "nodes": nodes,
        "execution_metadata": {
            "path_action_ids": path_action_ids,
            "action_invocation_counts": dict(invocation_counts),
            "representation": (
                "Resolved runtime service path encoded as a Sequence BT; "
                "consecutive retries are represented by invocation multiplicity."
            ),
        },
    }
