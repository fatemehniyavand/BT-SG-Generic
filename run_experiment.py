from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ticktide.experiment import ExperimentRunner
from ticktide.io_utils import export_experiment
from ticktide.prolog_adapter import PrologUnavailableError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the professor-aligned TickTide generic BT experiment."
    )
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output", default="outputs/latest")
    parser.add_argument("--swipl", default="swipl", help="SWI-Prolog executable")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = ExperimentRunner(
        ROOT / "config/generic_bt.json",
        ROOT / "config/task_profiles.csv",
        ROOT / "config/experiment.json",
        ROOT / "prolog/btsg.pl",
        prolog_executable=args.swipl,
    )
    try:
        result = runner.run(runs=args.runs, seed=args.seed)
    except PrologUnavailableError as exc:
        print(f"\nERROR: {exc}\n")
        print("This version intentionally does not bypass Prolog, because the professor requested the existing Prolog BT->SG rule to remain in the pipeline.")
        return 2

    out = export_experiment(result, ROOT / args.output)
    print("\nTickTide Generic Experiment — Prolog executed-BT pipeline")
    print("=" * 58)
    print(f"Runs: {result.metadata['runs']}")
    print(f"Seed: {result.metadata['seed']}")
    print(f"Distinct executed-SG topologies: {len(result.topology_summary)}")
    print(f"Unique Prolog transformations: {result.metadata['unique_prolog_transformations']}")
    print(f"Prolog cache hits: {result.metadata['prolog_cache_hits']}")

    by_strategy = {"A": 0, "B": 0, "Recovery": 0}
    for run in result.runs:
        by_strategy[run.selected_strategy] = by_strategy.get(run.selected_strategy, 0) + 1
    print("Strategy selection:")
    for strategy in ["A", "B", "Recovery"]:
        count = by_strategy.get(strategy, 0)
        print(f"  {strategy:8s}: {count:6d} ({count/len(result.runs):.2%})")

    mean_ops = sum(run.total_operations for run in result.runs) / len(result.runs)
    print(f"Mean operations/run: {mean_ops:,.1f}")
    print(f"Outputs written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
