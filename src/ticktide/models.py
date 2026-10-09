from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class TraceEvent:
    run_id: int
    event_index: int
    node_id: str
    node_name: str
    node_kind: str
    status: Status
    attempt: Optional[int] = None
    operations: int = 0
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class RunResult:
    run_id: int
    root_status: Status
    selected_strategy: str
    trace: List[TraceEvent]
    executed_bt: Dict[str, Any]
    executed_path_bt: Dict[str, Any]
    prolog_input_bt: Dict[str, Any]
    service_nodes: Dict[str, Dict[str, Any]]
    sg_edges: List[Dict[str, Any]]
    prolog_raw_edges: List[str]
    total_operations: int
    topology_signature: str
    prolog_cache_hit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "root_status": self.root_status.value,
            "selected_strategy": self.selected_strategy,
            "trace": [event.to_dict() for event in self.trace],
            "executed_bt": self.executed_bt,
            "executed_path_bt": self.executed_path_bt,
            "prolog_input_bt": self.prolog_input_bt,
            "service_nodes": self.service_nodes,
            "sg_edges": self.sg_edges,
            "prolog_raw_edges": self.prolog_raw_edges,
            "total_operations": self.total_operations,
            "topology_signature": self.topology_signature,
            "prolog_cache_hit": self.prolog_cache_hit,
        }


@dataclass
class ExperimentResult:
    runs: List[RunResult] = field(default_factory=list)
    service_summary: List[Dict[str, Any]] = field(default_factory=list)
    dependency_summary: List[Dict[str, Any]] = field(default_factory=list)
    topology_summary: List[Dict[str, Any]] = field(default_factory=list)
    convergence_summary: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
