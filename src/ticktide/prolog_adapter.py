from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple



# This naming function is intentionally equivalent to the function in the
# original BT-SG-Orchestration prolog.py adapter.
def camel_to_snake(text: str) -> str:
    text = text.replace(" ", "")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    return text.lower()


def _properties_for_action(profile: Dict[str, Any]) -> Dict[str, str]:
    properties: Dict[str, str] = {}
    reads = profile.get("reads", [])
    writes = profile.get("writes", [])
    if reads:
        properties["bbread"] = ",".join(reads)
    if writes:
        properties["bbwrite"] = ",".join(writes)
    return properties


def to_prolog_compatible_bt(
    executed_path_bt: Dict[str, Any], task_profiles: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Convert the resolved executed-path BT to the existing adapter format.

    The special executed-path BT contains only Action services under a Sequence
    root, so the unchanged Prolog rule sees the exact runtime service order rather
    than unresolved selector alternatives. Runtime retry multiplicity remains in
    the trace/service statistics rather than being duplicated structurally.
    """
    converted_nodes: Dict[str, Dict[str, Any]] = {}

    for node_id, raw in executed_path_bt["nodes"].items():
        node_type = raw["type"].lower()
        if node_type == "sequence":
            converted_nodes[node_id] = {
                "name": "Sequence",
                "children": list(raw["children"]),
                "properties": {},
            }
        elif node_type == "action":
            profile = task_profiles[node_id]
            converted_nodes[node_id] = {
                "name": raw["name"],
                "properties": _properties_for_action(profile),
            }
        else:
            raise ValueError(
                f"Executed-path Prolog input must contain only sequence/action nodes; got {node_type!r}"
            )

    return {
        "trees": [
            {
                # Deliberately run-independent so identical executed paths share
                # a Prolog cache entry. source_run_id stays in outer metadata.
                "title": "Executed Service Path",
                "root": executed_path_bt["root"],
                "nodes": converted_nodes,
            }
        ],
        "metadata": {
            "source_run_id": executed_path_bt.get("source_run_id"),
            "note": (
                "Resolved execution path encoded as a Behavior Tree and transformed "
                "by the unchanged existing BT->SG Prolog rule."
            ),
        },
    }


def _legacy_traverse(tree: Dict[str, Any], node: Dict[str, Any]) -> Tuple[str | None, set[str]]:
    """Equivalent of the original prolog.py JSON-to-Prolog traversal."""
    name = node["name"]
    bb_keys: set[str] = set()

    if name in ["Sequence", "ReactiveSequence", "Subtree"]:
        result = "seq(["
    elif name in ["Selector", "Priority", "Fallback"]:
        result = "sel(["
    elif name.lower().startswith("repeat"):
        child = tree["nodes"][node["child"]]
        return _legacy_traverse(tree, child)
    elif name.lower().startswith("condition"):
        return None, bb_keys
    else:
        properties = node.get("properties", {})
        params: List[str] = []
        if "bbread" in properties:
            for key in properties["bbread"].split(","):
                key = key.strip()
                if key:
                    params.append(f"param({key}, read({key}))")
                    bb_keys.add(key)
        if "bbwrite" in properties:
            for key in properties["bbwrite"].split(","):
                key = key.strip()
                if key:
                    params.append(f"param({key}, write({key}))")
                    bb_keys.add(key)
        result = f"task({camel_to_snake(name)}, [{','.join(params)}])"

    if "children" in node:
        definitions: List[str] = []
        for child_id in node["children"]:
            definition, new_keys = _legacy_traverse(tree, tree["nodes"][child_id])
            if definition is not None:
                definitions.append(definition)
            bb_keys.update(new_keys)
        result += ",".join(definitions)

    if name in ["Sequence", "ReactiveSequence", "Subtree", "Selector", "Priority", "Fallback"]:
        result += "])"

    return result, bb_keys


def legacy_json_to_prolog_terms(data: Dict[str, Any]) -> Tuple[str, List[str]]:
    tree = data["trees"][0]
    root_node = tree["nodes"][tree["root"]]
    root_term, bb_keys = _legacy_traverse(tree, root_node)
    if not root_term:
        raise ValueError("Prolog-compatible executed BT contains no service task")
    return root_term, sorted(bb_keys)


def _prolog_quote_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _split_top_level_list(text: str) -> List[str]:
    text = text.strip()
    if text == "[]":
        return []
    if not (text.startswith("[") and text.endswith("]")):
        raise ValueError(f"Unexpected Prolog edge list: {text!r}")
    body = text[1:-1]
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def parse_prolog_edges(raw_list: str) -> List[Tuple[str, str, str]]:
    parsed: List[Tuple[str, str, str]] = []
    pattern = re.compile(r"^edge\(([^,]+),([^,]+),(.+)\)$")
    for item in _split_top_level_list(raw_list):
        match = pattern.match(item)
        if not match:
            raise ValueError(f"Could not parse Prolog edge: {item!r}")
        dependent, dependency, reason = [value.strip() for value in match.groups()]
        parsed.append((dependent, dependency, reason))
    return parsed


def prolog_rule_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PrologUnavailableError(RuntimeError):
    pass


class PrologTransformer:
    """Use the existing btsg.pl rule as the only SG-edge transformation engine."""

    def __init__(self, rule_path: str | Path, executable: str = "swipl") -> None:
        self.rule_path = Path(rule_path)
        self.executable = executable
        self._cache: Dict[str, Tuple[List[Dict[str, Any]], List[str]]] = {}
        self.calls = 0
        self.cache_hits = 0

    @property
    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def assert_available(self) -> None:
        if not self.rule_path.exists():
            raise FileNotFoundError(f"Prolog rule not found: {self.rule_path}")
        if not self.available:
            raise PrologUnavailableError(
                "SWI-Prolog executable 'swipl' was not found. On macOS with Homebrew run: "
                "brew install swi-prolog"
            )

    def transform(
        self,
        prolog_input_bt: Dict[str, Any],
        task_profiles: Dict[str, Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[str], bool]:
        canonical = json.dumps(prolog_input_bt["trees"][0], sort_keys=True, separators=(",", ":"))
        cache_key = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
        if cache_key in self._cache:
            self.cache_hits += 1
            edges, raw = self._cache[cache_key]
            return [dict(edge) for edge in edges], list(raw), True

        self.assert_available()
        root_term, bb_keys = legacy_json_to_prolog_terms(prolog_input_bt)
        bb_term = "[" + ",".join(f"bbkey({key}, string)" for key in bb_keys) + "]"
        driver = f"""
:- consult('{_prolog_quote_path(self.rule_path)}').
newTree(bt(Root, BB)) :-
    Root = {root_term},
    BB = {bb_term}.
main :-
    newTree(Tree),
    serviceGraph(Tree, Edges),
    write_canonical(Edges), nl,
    halt.
:- initialization(main).
""".strip()

        with tempfile.TemporaryDirectory(prefix="ticktide_prolog_") as tmp:
            driver_path = Path(tmp) / "driver.pl"
            driver_path.write_text(driver, encoding="utf-8")
            completed = subprocess.run(
                [self.executable, "-q", "-f", str(driver_path)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )

        if completed.returncode != 0:
            raise RuntimeError(
                "Prolog transformation failed.\n"
                f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )

        output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not output_lines:
            raise RuntimeError("Prolog transformation returned no edge list")
        raw_list = output_lines[-1]
        raw_tuples = parse_prolog_edges(raw_list)

        name_to_id = {
            camel_to_snake(profile["task_name"]): task_id
            for task_id, profile in task_profiles.items()
        }
        if len(name_to_id) != len(task_profiles):
            raise ValueError("Task names are not unique after Prolog snake_case normalization")

        edges: List[Dict[str, Any]] = []
        raw_edges: List[str] = []
        for dependent_name, dependency_name, reason in raw_tuples:
            if dependent_name not in name_to_id or dependency_name not in name_to_id:
                raise KeyError(
                    f"Prolog returned unknown task(s): {dependent_name}, {dependency_name}"
                )
            source_id = name_to_id[dependency_name]
            target_id = name_to_id[dependent_name]
            if reason.startswith("blackboard(") and reason.endswith(")"):
                dependency_type = "data"
                data_key = reason[len("blackboard(") : -1]
            else:
                dependency_type = "control"
                data_key = ""
            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "dependency_type": dependency_type,
                    "reason": reason,
                    "data_key": data_key,
                    "prolog_dependent": dependent_name,
                    "prolog_dependency": dependency_name,
                }
            )
            raw_edges.append(f"edge({dependent_name},{dependency_name},{reason})")

        edges.sort(key=lambda e: (e["source"], e["target"], e["reason"]))
        raw_edges.sort()
        self._cache[cache_key] = ([dict(edge) for edge in edges], list(raw_edges))
        self.calls += 1
        return edges, raw_edges, False
