from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ticktide.experiment import ExperimentRunner
from ticktide.io_utils import export_experiment
from ticktide.visualization import execution_sg_to_dot, legacy_bt_to_dot, tree_to_dot

st.set_page_config(page_title="TickTide | Executed BT → Prolog → SG", page_icon="🌊", layout="wide")
st.title("TickTide — Professor-aligned Generic Experiment")
st.caption("Fixed BT → runtime trace → executed-path BT → unchanged Prolog BT→SG rule → executed Service Graph → workload")

if shutil.which("swipl") is None:
    st.error("SWI-Prolog (`swipl`) is not installed. On macOS with Homebrew run: `brew install swi-prolog`.")
    st.stop()

runner = ExperimentRunner(
    ROOT / "config/generic_bt.json",
    ROOT / "config/task_profiles.csv",
    ROOT / "config/experiment.json",
    ROOT / "prolog/btsg.pl",
)

with st.sidebar:
    st.header("Experiment controls")
    runs = st.number_input("Runs", min_value=1, max_value=100000, value=int(runner.config["runs"]), step=100)
    seed = st.number_input("Random seed", min_value=0, value=int(runner.config["seed"]), step=1)
    st.markdown("**Node outcome probabilities**")
    probabilities = {
        key: st.slider(key, 0.0, 1.0, float(value), 0.01)
        for key, value in runner.probabilities.items()
    }
    run_button = st.button("Run experiment", type="primary", use_container_width=True)

@st.cache_data(show_spinner=False)
def run_cached(runs_value: int, seed_value: int, probabilities_json: str):
    local = ExperimentRunner(
        ROOT / "config/generic_bt.json",
        ROOT / "config/task_profiles.csv",
        ROOT / "config/experiment.json",
        ROOT / "prolog/btsg.pl",
    )
    local.config["probabilities"] = json.loads(probabilities_json)
    return local.run(runs=runs_value, seed=seed_value)

if run_button or "result" not in st.session_state:
    with st.spinner("Executing BTs and transforming executed BTs with Prolog..."):
        st.session_state["result"] = run_cached(
            int(runs), int(seed), json.dumps(probabilities, sort_keys=True)
        )

result = st.session_state["result"]

tabs = st.tabs([
    "Original BT",
    "Run Explorer",
    "Executed BT (audit)",
    "Executed Path BT",
    "Prolog Input",
    "Executed SG",
    "Aggregate",
    "Convergence",
    "Export",
])

with tabs[0]:
    st.subheader("Frozen generic Behavior Tree")
    st.graphviz_chart(tree_to_dot(runner.tree_spec), use_container_width=True)
    st.info("The original BT stays fixed. Randomness is applied to node outcomes; BT semantics determine the valid path.")

with tabs[1]:
    st.subheader("One runtime execution")
    run_id = st.number_input("Run ID", min_value=1, max_value=len(result.runs), value=1, step=1)
    run = result.runs[int(run_id) - 1]
    cols = st.columns(5)
    cols[0].metric("Strategy", run.selected_strategy)
    cols[1].metric("Operations", f"{run.total_operations:,}")
    cols[2].metric("Services", len(run.service_nodes))
    cols[3].metric("SG topology", run.topology_signature)
    cols[4].metric("Prolog cache", "hit" if run.prolog_cache_hit else "new")
    st.dataframe(pd.DataFrame([event.to_dict() for event in run.trace]), use_container_width=True, hide_index=True)

with tabs[2]:
    run_id = st.number_input("Executed BT run", min_value=1, max_value=len(result.runs), value=1, step=1, key="bt_run")
    run = result.runs[int(run_id) - 1]
    st.graphviz_chart(tree_to_dot(run.executed_bt), use_container_width=True)
    st.json(run.executed_bt)

with tabs[3]:
    run_id = st.number_input("Executed-path BT run", min_value=1, max_value=len(result.runs), value=1, step=1, key="path_bt_run")
    run = result.runs[int(run_id) - 1]
    st.graphviz_chart(tree_to_dot(run.executed_path_bt), use_container_width=True)
    st.json(run.executed_path_bt)
    st.caption("This special BT is the resolved runtime service path. Consecutive retries are represented by invocation count, not duplicate SG nodes.")

with tabs[4]:
    run_id = st.number_input("Prolog-input run", min_value=1, max_value=len(result.runs), value=1, step=1, key="prolog_run")
    run = result.runs[int(run_id) - 1]
    st.graphviz_chart(legacy_bt_to_dot(run.prolog_input_bt), use_container_width=True)
    st.json(run.prolog_input_bt)
    st.caption("The unchanged Prolog rule receives the resolved executed-path BT, so failed alternatives cannot appear as downstream exits.")

with tabs[5]:
    run_id = st.number_input("Executed SG run", min_value=1, max_value=len(result.runs), value=1, step=1, key="sg_run")
    run = result.runs[int(run_id) - 1]
    st.graphviz_chart(execution_sg_to_dot(run), use_container_width=True)
    st.dataframe(pd.DataFrame(run.sg_edges), use_container_width=True, hide_index=True)
    st.code("\n".join(run.prolog_raw_edges) or "(no edges)")

with tabs[6]:
    st.subheader("Aggregate statistics")
    st.markdown("**Service activation and workload**")
    st.dataframe(pd.DataFrame(result.service_summary), use_container_width=True, hide_index=True)
    st.markdown("**Dependencies generated by Prolog**")
    st.dataframe(pd.DataFrame(result.dependency_summary), use_container_width=True, hide_index=True)
    st.markdown("**Distinct executed-SG topologies**")
    st.dataframe(pd.DataFrame(result.topology_summary), use_container_width=True, hide_index=True)

with tabs[7]:
    st.subheader("Convergence")
    convergence = pd.DataFrame(result.convergence_summary)
    st.dataframe(convergence, use_container_width=True, hide_index=True)
    if not convergence.empty:
        st.line_chart(convergence.set_index("runs")[["p_strategy_a", "p_strategy_b", "p_recovery"]])
        st.line_chart(convergence.set_index("runs")["mean_operations_per_run"])

with tabs[8]:
    st.subheader("Export")
    export_dir = export_experiment(result, ROOT / "outputs/dashboard_export")
    st.success(f"Exported to {export_dir}")
    st.code("\n".join(sorted(path.name for path in export_dir.iterdir())))
    st.info("Network Graph and solver are intentionally outside this phase.")
