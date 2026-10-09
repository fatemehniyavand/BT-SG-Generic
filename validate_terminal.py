from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_PROLOG_SHA = "98f88f8cc0a8e81b8f3301cf73542c4579023ae10038ed63e77edff83ea62ab0"


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate TickTide terminal experiment outputs")
    ap.add_argument("output", type=Path, help="Experiment output directory")
    args = ap.parse_args()
    base = args.output

    with (base / "run_summary.csv").open(encoding="utf-8") as f:
        runs = list(csv.DictReader(f))
    with (base / "execution_log.csv").open(encoding="utf-8") as f:
        trace_rows = list(csv.DictReader(f))
    with (base / "topology_summary.csv").open(encoding="utf-8") as f:
        topologies = list(csv.DictReader(f))

    audit_bts = read_jsonl(base / "executed_bts.jsonl")
    path_bts = read_jsonl(base / "executed_path_bts.jsonl")
    prolog_inputs = read_jsonl(base / "prolog_inputs.jsonl")
    sgs = read_jsonl(base / "execution_service_graphs.jsonl")
    metadata = json.loads((base / "experiment_metadata.json").read_text(encoding="utf-8"))

    n = len(runs)
    print("\n=== TICKTIDE EXECUTED-PATH / PROLOG VALIDATION ===\n")
    print(f"Runs: {n}")
    print(f"Audit executed BTs: {len(audit_bts)}")
    print(f"Executed-path BTs: {len(path_bts)}")
    print(f"Prolog inputs: {len(prolog_inputs)}")
    print(f"Executed SGs: {len(sgs)}")
    print(f"Distinct SG topologies: {len(topologies)}")

    assert len(audit_bts) == len(path_bts) == len(prolog_inputs) == len(sgs) == n

    # Exact pipeline alignment.
    for a, p, pi, sg in zip(audit_bts, path_bts, prolog_inputs, sgs):
        rid = a["run_id"]
        assert p["run_id"] == pi["run_id"] == sg["run_id"] == rid
        assert a["executed_bt"]["source_run_id"] == rid
        assert p["executed_path_bt"]["source_run_id"] == rid
        assert pi["prolog_input_bt"]["metadata"]["source_run_id"] == rid
    print("Run-ID alignment: PASS")

    # Build exact expected action path from runtime trace, collapsing only
    # consecutive retry repetitions of the same service.
    actions_by_run = defaultdict(list)
    for row in trace_rows:
        if row["node_kind"] == "action":
            rid = int(row["run_id"])
            node_id = row["node_id"]
            if not actions_by_run[rid] or actions_by_run[rid][-1] != node_id:
                actions_by_run[rid].append(node_id)

    path_by_run = {
        item["run_id"]: item["executed_path_bt"]["execution_metadata"]["path_action_ids"]
        for item in path_bts
    }
    sg_by_run = {item["run_id"]: item for item in sgs}

    for rid in range(1, n + 1):
        expected_path = actions_by_run[rid]
        assert path_by_run[rid] == expected_path, (rid, path_by_run[rid], expected_path)

        expected_control = set(zip(expected_path, expected_path[1:]))
        actual_control = {
            (e["source"], e["target"])
            for e in sg_by_run[rid]["sg_edges"]
            if e["dependency_type"] == "control"
        }
        assert actual_control == expected_control, (
            f"Run {rid} control-path mismatch",
            expected_control,
            actual_control,
        )

    print("Every Prolog control graph exactly matches the executed service path: PASS")

    # Explicit regression guards for the previously detected impossible edges.
    dependency_rows = list(csv.DictReader((base / "dependency_activation_summary.csv").open(encoding="utf-8")))
    control_counts = {
        (row["source"], row["target"]): int(row["activation_count"])
        for row in dependency_rows if row["dependency_type"] == "control"
    }
    assert ("F4", "F11") not in control_counts, "Impossible A-failure -> Consolidate edge returned"
    assert ("F7", "F11") not in control_counts, "Impossible B-failure -> Consolidate edge returned"
    print("Impossible failed-branch -> Consolidate edges absent: PASS")

    # The seven expected execution families should remain for the frozen benchmark.
    assert len(topologies) == 7, f"Expected 7 topologies, got {len(topologies)}"
    print("Seven expected executed-SG topology families: PASS")

    strategies = Counter(row["selected_strategy"] for row in runs)
    print("\nStrategy counts:")
    for k in ["A", "B", "Recovery"]:
        print(f"  {k:8s}: {strategies[k]:5d} ({strategies[k]/n:.2%})")

    mean_ops = sum(int(row["total_operations"]) for row in runs) / n
    print(f"\nMean operations/run: {mean_ops:,.1f}")

    print(f"Unique Prolog transformations: {metadata.get('unique_prolog_transformations')}")
    print(f"Prolog cache hits: {metadata.get('prolog_cache_hits')}")

    rule = Path(__file__).resolve().parent / "prolog" / "btsg.pl"
    sha = hashlib.sha256(rule.read_bytes()).hexdigest()
    assert sha == EXPECTED_PROLOG_SHA
    assert metadata["prolog_rule_sha256"] == EXPECTED_PROLOG_SHA
    print("Original btsg.pl unchanged: PASS")

    print("\nPipeline:")
    print(metadata["sg_generation_pipeline"])
    print("\nALL SCIENTIFIC CORE CHECKS: PASS")


if __name__ == "__main__":
    main()
