from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable

from .models import ExperimentResult


def write_csv(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def export_experiment(result: ExperimentResult, output_dir: str | Path) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    trace_rows = []
    for run in result.runs:
        trace_rows.extend(event.to_dict() for event in run.trace)
    write_csv(out / "execution_log.csv", trace_rows)

    run_rows = [
        {
            "run_id": run.run_id,
            "root_status": run.root_status.value,
            "selected_strategy": run.selected_strategy,
            "total_operations": run.total_operations,
            "topology_signature": run.topology_signature,
            "num_services": len(run.service_nodes),
            "num_prolog_edges": len(run.sg_edges),
            "prolog_cache_hit": run.prolog_cache_hit,
        }
        for run in result.runs
    ]
    write_csv(out / "run_summary.csv", run_rows)
    write_csv(out / "service_activation_summary.csv", result.service_summary)
    write_csv(out / "dependency_activation_summary.csv", result.dependency_summary)
    write_csv(out / "topology_summary.csv", result.topology_summary)
    write_csv(out / "convergence_summary.csv", result.convergence_summary)

    _write_jsonl(
        out / "executed_bts.jsonl",
        ({"run_id": run.run_id, "executed_bt": run.executed_bt} for run in result.runs),
    )
    _write_jsonl(
        out / "executed_path_bts.jsonl",
        ({"run_id": run.run_id, "executed_path_bt": run.executed_path_bt} for run in result.runs),
    )
    _write_jsonl(
        out / "prolog_inputs.jsonl",
        ({"run_id": run.run_id, "prolog_input_bt": run.prolog_input_bt} for run in result.runs),
    )
    _write_jsonl(
        out / "execution_service_graphs.jsonl",
        (
            {
                "run_id": run.run_id,
                "topology_signature": run.topology_signature,
                "service_nodes": run.service_nodes,
                "sg_edges": run.sg_edges,
                "prolog_raw_edges": run.prolog_raw_edges,
                "total_operations": run.total_operations,
            }
            for run in result.runs
        ),
    )

    representatives_dir = out / "representative_topologies"
    representatives_dir.mkdir(exist_ok=True)
    by_id = {run.run_id: run for run in result.runs}
    for index, row in enumerate(result.topology_summary, start=1):
        run = by_id[int(row["representative_run_id"])]
        target = representatives_dir / f"T{index}_{run.topology_signature}"
        target.mkdir(exist_ok=True)
        (target / "executed_bt.json").write_text(
            json.dumps(run.executed_bt, indent=2), encoding="utf-8"
        )
        (target / "executed_path_bt.json").write_text(
            json.dumps(run.executed_path_bt, indent=2), encoding="utf-8"
        )
        (target / "prolog_input_bt.json").write_text(
            json.dumps(run.prolog_input_bt, indent=2), encoding="utf-8"
        )
        (target / "executed_sg.json").write_text(
            json.dumps(
                {
                    "run_id": run.run_id,
                    "service_nodes": run.service_nodes,
                    "sg_edges": run.sg_edges,
                    "prolog_raw_edges": run.prolog_raw_edges,
                    "total_operations": run.total_operations,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    (out / "experiment_metadata.json").write_text(
        json.dumps(result.metadata, indent=2), encoding="utf-8"
    )
    return out
