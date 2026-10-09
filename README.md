# TickTide Generic Experiment — Corrected Executed-Path BT → Prolog → Executed SG

This version implements the professor-requested pipeline while keeping the existing `prolog/btsg.pl` rule unchanged.

## Scientific pipeline

```text
ONE FIXED GENERIC BEHAVIOR TREE
              |
              v
 stochastic node outcomes
              |
              v
 valid BT execution + trace
              |
      +-------+--------+
      |                |
      v                v
Pruned Executed BT   Resolved Executed-Path BT
(audit/explanation)  (special BT for Prolog)
                       |
                       v
               Prolog-compatible BT
                       |
                       v
              UNCHANGED btsg.pl
                       |
                       v
               Executed Service Graph
                       |
                + runtime trace
                       |
                       v
activation/dependency frequencies
+ invocation counts
+ operation-based workload
```

## Why there are two executed-BT representations

The **pruned Executed BT** keeps Conditions and original ancestors so a run can be audited and explained.

The **Executed-Path BT** represents the already-resolved runtime service path as a Behavior Tree `Sequence`. This is the BT supplied to the existing Prolog transformation. This distinction is necessary because the static Prolog selector rule correctly represents *possible* selector exits for a structural BT, but after runtime has resolved a failed branch, that failed branch must not also be treated as a possible exit to downstream services.

Example resolved run:

```text
A Prepare -> A Execute -> A Result invalid -> B Prepare -> B Execute -> B Commit
```

The Prolog-path BT structurally contains the executed service order:

```text
Sequence[
  Initialize,
  Preprocess,
  A Prepare,
  A Execute,
  B Prepare,
  B Execute,
  B Commit,
  Consolidate,
  Finalize
]
```

The unchanged Prolog rule therefore produces the actual executed control dependencies, including `A Execute -> B Prepare`, and cannot create the impossible `A Execute -> Consolidate` edge for that failed A branch.

Retry multiplicity is a runtime property: repeated consecutive invocations of the same service are collapsed to one structural SG node, while `invocation_count` preserves the number of attempts for workload calculation.

## Terminal-only setup and run

The core experiment uses the Python standard library plus SWI-Prolog; Streamlit is optional.

```bash
python3 -m venv .venv
source .venv/bin/activate
brew install swi-prolog
python3 verify_setup.py
python3 run_experiment.py --runs 1000 --seed 42 --output outputs/n1000_seed42
python3 validate_terminal.py outputs/n1000_seed42
```

The terminal validator checks **every run** and requires the Prolog control edges to match the exact executed service path. It also guards against the previously detected impossible edges `F4 -> F11` and `F7 -> F11` after failed branches.

## Optional dashboard

Only install UI dependencies if you have disk space:

```bash
python3 -m pip install --no-cache-dir -r requirements.txt
python3 -m streamlit run app.py
```

## Expected 1000-run baseline

With seed 42 and the frozen probability configuration, the stochastic execution statistics should remain the same as before (strategy counts/workload), while the SG control-edge semantics are corrected.

The benchmark is expected to produce seven executed-SG topology families.

## Network Graph / Solver

Still intentionally outside this phase. First validate:

```text
execution -> executed-path BT -> unchanged Prolog -> executed SG -> workload
```

Only after this is correct should operation-based workload be mapped to solver resource units and combined with the Network Graph.
