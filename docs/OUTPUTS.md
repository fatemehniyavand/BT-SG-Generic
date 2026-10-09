# Output files

For each experiment directory:

- `execution_log.csv`: leaf-level runtime trace, including Conditions, Action status, Retry attempt and operations.
- `run_summary.csv`: one row per run.
- `service_activation_summary.csv`: service activation/invocation/workload statistics.
- `dependency_activation_summary.csv`: dependencies returned by Prolog and their activation frequency.
- `topology_summary.csv`: distinct executed-SG topology families.
- `convergence_summary.csv`: convergence checkpoints.
- `executed_bts.jsonl`: pruned original BT per run for audit/explanation.
- `executed_path_bts.jsonl`: resolved executed service path encoded as a BT per run.
- `prolog_inputs.jsonl`: exact legacy-compatible BT supplied to the Prolog adapter.
- `execution_service_graphs.jsonl`: Prolog-derived SG plus workload metadata.
- `experiment_metadata.json`: run configuration, transformation pipeline, cache statistics and Prolog rule hash.

`representative_topologies/` stores representative `executed_bt.json`, `executed_path_bt.json`, `prolog_input_bt.json`, and `executed_sg.json` for each distinct SG topology.
