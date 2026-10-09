from __future__ import annotations

from typing import Any, Dict

from .models import RunResult


def _escape(text: str) -> str:
    return str(text).replace('"', '\\"')


def tree_to_dot(tree_spec: Dict[str, Any]) -> str:
    nodes = tree_spec["nodes"]
    lines = ["digraph BT {", 'rankdir="TB";', 'node [shape=box, style="rounded"];']
    for node_id, node in nodes.items():
        node_type = node["type"].lower()
        shape = {
            "sequence": "box",
            "fallback": "diamond",
            "retry": "hexagon",
            "condition": "ellipse",
            "action": "box",
        }.get(node_type, "box")
        label = f"{node_id}: {_escape(node['name'])}\\n[{node['type']}]"
        lines.append(f'"{node_id}" [label="{label}", shape={shape}];')
        for child in node.get("children", []):
            lines.append(f'"{node_id}" -> "{child}";')
        if "child" in node:
            lines.append(f'"{node_id}" -> "{node["child"]}" [label="retry"];')
    lines.append("}")
    return "\n".join(lines)


def legacy_bt_to_dot(prolog_input_bt: Dict[str, Any]) -> str:
    tree = prolog_input_bt["trees"][0]
    nodes = tree["nodes"]
    lines = ["digraph PBT {", 'rankdir="TB";', 'node [shape=box, style="rounded"];']
    for node_id, node in nodes.items():
        label = f"{node_id}: {_escape(node['name'])}"
        shape = "diamond" if node["name"] in {"Fallback", "Selector", "Priority"} else "box"
        lines.append(f'"{node_id}" [label="{label}", shape={shape}];')
        for child in node.get("children", []):
            lines.append(f'"{node_id}" -> "{child}";')
        if "child" in node:
            lines.append(f'"{node_id}" -> "{node["child"]}" [label="unwrap in adapter"];')
    lines.append("}")
    return "\n".join(lines)


def execution_sg_to_dot(run: RunResult) -> str:
    lines = ["digraph SG {", 'rankdir="LR";', 'node [shape=box, style="rounded"];']
    for node_id, node in run.service_nodes.items():
        label = (
            f"{node_id}: {_escape(node['name'])}\\n"
            f"inv={node['invocation_count']} | ops={node['total_operations']:,}"
        )
        lines.append(f'"{node_id}" [label="{label}"];')
    for edge in run.sg_edges:
        style = "dashed" if edge["dependency_type"] == "data" else "solid"
        label = edge["reason"]
        lines.append(
            f'"{edge["source"]}" -> "{edge["target"]}" '
            f'[style={style}, label="{_escape(label)}"];'
        )
    lines.append("}")
    return "\n".join(lines)
