from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .nodes import Action, Condition, Fallback, Node, Retry, Sequence


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_tree_from_dict(spec: Dict[str, Any]) -> Node:
    nodes = spec["nodes"]

    def build(node_id: str) -> Node:
        raw = nodes[node_id]
        node_type = raw["type"].lower()
        name = raw["name"]

        if node_type == "sequence":
            return Sequence(node_id, name, [build(child_id) for child_id in raw["children"]])
        if node_type == "fallback":
            return Fallback(node_id, name, [build(child_id) for child_id in raw["children"]])
        if node_type == "condition":
            return Condition(node_id, name, raw["probability_key"])
        if node_type == "action":
            return Action(
                node_id=node_id,
                name=name,
                outcome_probability_key=raw.get("outcome_probability_key"),
                strategy_label=raw.get("strategy_label"),
            )
        if node_type == "retry":
            return Retry(
                node_id=node_id,
                name=name,
                child=build(raw["child"]),
                max_attempts=int(raw["max_attempts"]),
            )
        raise ValueError(f"Unsupported node type {node_type!r} for {node_id}")

    return build(spec["root"])
