from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Sequence

from .executed_bt import build_executed_bt, build_executed_path_bt
from .factory import build_tree_from_dict, load_json
from .models import ExperimentResult, RunResult
from .nodes import ExecutionState
from .prolog_adapter import PrologTransformer, prolog_rule_sha256, to_prolog_compatible_bt
from .service_graph import build_service_nodes, topology_signature


def load_task_profiles(path: str | Path) -> Dict[str, Dict]:
    profiles: Dict[str, Dict] = {}
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            node_id = row["task_id"].strip()
            profiles[node_id] = {
                "task_id": node_id,
                "task_name": row["task_name"].strip(),
                "operations_per_invocation": int(row["operations_per_invocation"]),
                "reads": [value.strip() for value in row.get("reads", "").split(";") if value.strip()],
                "writes": [value.strip() for value in row.get("writes", "").split(";") if value.strip()],
                "workload_class": row.get("workload_class", "").strip(),
            }
    return profiles


class ExperimentRunner:
    def __init__(
        self,
        tree_path: str | Path,
        task_profiles_path: str | Path,
        experiment_config_path: str | Path,
        prolog_rule_path: str | Path,
        prolog_executable: str = "swipl",
    ) -> None:
        self.tree_spec = load_json(tree_path)
        self.task_profiles = load_task_profiles(task_profiles_path)
        self.config = load_json(experiment_config_path)
        self.prolog = PrologTransformer(prolog_rule_path, executable=prolog_executable)
        self._validate()

    def _validate(self) -> None:
        action_ids = {
            node_id
            for node_id, node in self.tree_spec["nodes"].items()
            if node["type"].lower() == "action"
        }
        profile_ids = set(self.task_profiles)
        if action_ids != profile_ids:
            raise ValueError(
                f"Task profile mismatch. Missing={sorted(action_ids-profile_ids)}, "
                f"extra={sorted(profile_ids-action_ids)}"
            )
        for key, probability in self.config["probabilities"].items():
            if not 0.0 <= float(probability) <= 1.0:
                raise ValueError(f"Probability {key} must be in [0,1], got {probability}")

    @property
    def probabilities(self) -> Dict[str, float]:
        return {key: float(value) for key, value in self.config["probabilities"].items()}

    @property
    def operations(self) -> Dict[str, int]:
        return {
            task_id: int(profile["operations_per_invocation"])
            for task_id, profile in self.task_profiles.items()
        }

    def run_once(self, run_id: int, rng: random.Random) -> RunResult:
        tree = build_tree_from_dict(deepcopy(self.tree_spec))
        state = ExecutionState(
            run_id=run_id,
            rng=rng,
            probabilities=self.probabilities,
            operations=self.operations,
            task_profiles=self.task_profiles,
            trace=[],
        )
        root_status = tree.execute(state)

        # Professor-aligned pipeline:
        # trace -> explanatory pruned BT + resolved executed-path BT ->
        # Prolog-compatible BT -> UNCHANGED existing Prolog BT->SG rule.
        executed_bt = build_executed_bt(self.tree_spec, state.trace, run_id)
        executed_path_bt = build_executed_path_bt(self.tree_spec, state.trace, run_id)
        prolog_input_bt = to_prolog_compatible_bt(executed_path_bt, self.task_profiles)
        sg_edges, raw_edges, cache_hit = self.prolog.transform(prolog_input_bt, self.task_profiles)

        service_nodes = build_service_nodes(state.trace, self.task_profiles)
        total_operations = sum(
            event.operations for event in state.trace if event.node_kind == "action"
        )
        signature = topology_signature(service_nodes, sg_edges)
        selected_strategy = state.selected_strategy or self._infer_strategy(service_nodes)

        return RunResult(
            run_id=run_id,
            root_status=root_status,
            selected_strategy=selected_strategy,
            trace=state.trace,
            executed_bt=executed_bt,
            executed_path_bt=executed_path_bt,
            prolog_input_bt=prolog_input_bt,
            service_nodes=service_nodes,
            sg_edges=sg_edges,
            prolog_raw_edges=raw_edges,
            total_operations=total_operations,
            topology_signature=signature,
            prolog_cache_hit=cache_hit,
        )

    @staticmethod
    def _infer_strategy(service_nodes: Dict[str, Dict]) -> str:
        if "F10" in service_nodes:
            return "Recovery"
        if "F8" in service_nodes:
            return "B"
        if "F5" in service_nodes:
            return "A"
        return "Unknown"

    def run(self, runs: int | None = None, seed: int | None = None) -> ExperimentResult:
        self.prolog.assert_available()
        runs = int(runs if runs is not None else self.config["runs"])
        seed = int(seed if seed is not None else self.config["seed"])
        if runs < 1:
            raise ValueError("runs must be >= 1")

        rng = random.Random(seed)
        run_results = [self.run_once(run_id, rng) for run_id in range(1, runs + 1)]
        result = ExperimentResult(
            runs=run_results,
            metadata={
                "runs": runs,
                "seed": seed,
                "probabilities": self.probabilities,
                "retry_max_attempts": self._retry_attempts(),
                "tree_name": self.tree_spec.get("name", "Generic BT"),
                "sg_generation_pipeline": "execution trace -> executed-path BT -> Prolog-compatible BT -> unchanged existing btsg.pl -> executed SG",
                "prolog_rule_sha256": prolog_rule_sha256(self.prolog.rule_path),
            },
        )
        result.service_summary = self._service_summary(run_results)
        result.dependency_summary = self._dependency_summary(run_results)
        result.topology_summary = self._topology_summary(run_results)
        result.convergence_summary = self._convergence_summary(run_results)
        result.metadata["unique_prolog_transformations"] = self.prolog.calls
        result.metadata["prolog_cache_hits"] = self.prolog.cache_hits
        return result

    def _retry_attempts(self) -> Dict[str, int]:
        return {
            node_id: int(node["max_attempts"])
            for node_id, node in self.tree_spec["nodes"].items()
            if node["type"].lower() == "retry"
        }

    def _service_summary(self, runs: Sequence[RunResult]) -> List[Dict]:
        run_presence = Counter()
        invocation_count = Counter()
        success_count = Counter()
        failure_count = Counter()
        total_operations = Counter()
        for run in runs:
            for task_id, service in run.service_nodes.items():
                run_presence[task_id] += 1
                invocation_count[task_id] += service["invocation_count"]
                success_count[task_id] += service["success_count"]
                failure_count[task_id] += service["failure_count"]
                total_operations[task_id] += service["total_operations"]

        n_runs = len(runs)
        rows = []
        for task_id in sorted(self.task_profiles, key=lambda item: int(item[1:])):
            profile = self.task_profiles[task_id]
            rows.append(
                {
                    "task_id": task_id,
                    "task_name": profile["task_name"],
                    "workload_class": profile["workload_class"],
                    "run_activation_count": run_presence[task_id],
                    "run_activation_rate": run_presence[task_id] / n_runs,
                    "invocation_count": invocation_count[task_id],
                    "success_count": success_count[task_id],
                    "failure_count": failure_count[task_id],
                    "operations_per_invocation": profile["operations_per_invocation"],
                    "total_operations": total_operations[task_id],
                }
            )
        return rows

    def _dependency_summary(self, runs: Sequence[RunResult]) -> List[Dict]:
        counts = Counter()
        for run in runs:
            seen = {
                (
                    edge["dependency_type"],
                    edge["source"],
                    edge["target"],
                    edge["reason"],
                    edge["data_key"],
                )
                for edge in run.sg_edges
            }
            for item in seen:
                counts[item] += 1

        n_runs = len(runs)
        rows = []
        for (kind, source, target, reason, data_key), count in sorted(counts.items()):
            rows.append(
                {
                    "dependency_type": kind,
                    "source": source,
                    "target": target,
                    "reason": reason,
                    "data_key": data_key,
                    "activation_count": count,
                    "activation_rate": count / n_runs,
                }
            )
        return rows

    def _topology_summary(self, runs: Sequence[RunResult]) -> List[Dict]:
        counts = Counter(run.topology_signature for run in runs)
        strategy_by_topology = defaultdict(Counter)
        representative = {}
        for run in runs:
            strategy_by_topology[run.topology_signature][run.selected_strategy] += 1
            representative.setdefault(run.topology_signature, run.run_id)

        n_runs = len(runs)
        return [
            {
                "topology_signature": signature,
                "count": count,
                "frequency": count / n_runs,
                "representative_run_id": representative[signature],
                "strategy_mix": dict(strategy_by_topology[signature]),
            }
            for signature, count in counts.most_common()
        ]

    def _convergence_summary(self, runs: Sequence[RunResult]) -> List[Dict]:
        requested = self.config.get(
            "convergence_checkpoints", [100, 500, 1000, 5000, 10000]
        )
        checkpoints = sorted(
            {int(value) for value in requested if 1 <= int(value) <= len(runs)}
            | {len(runs)}
        )
        rows = []
        for n in checkpoints:
            prefix = runs[:n]
            strategy = Counter(run.selected_strategy for run in prefix)
            mean_ops = sum(run.total_operations for run in prefix) / n
            unique_sg = len({run.topology_signature for run in prefix})
            rows.append(
                {
                    "runs": n,
                    "p_strategy_a": strategy["A"] / n,
                    "p_strategy_b": strategy["B"] / n,
                    "p_recovery": strategy["Recovery"] / n,
                    "mean_operations_per_run": mean_ops,
                    "unique_topologies": unique_sg,
                }
            )
        return rows
