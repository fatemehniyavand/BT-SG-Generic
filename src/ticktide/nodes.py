from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .models import Status


@dataclass
class ExecutionState:
    run_id: int
    rng: object
    probabilities: Dict[str, float]
    operations: Dict[str, int]
    task_profiles: Dict[str, Dict]
    trace: list
    event_index: int = 0
    selected_strategy: str = ""

    def record(
        self,
        node_id: str,
        node_name: str,
        node_kind: str,
        status: Status,
        attempt: Optional[int] = None,
        operations: int = 0,
        detail: str = "",
    ) -> None:
        from .models import TraceEvent

        self.event_index += 1
        self.trace.append(
            TraceEvent(
                run_id=self.run_id,
                event_index=self.event_index,
                node_id=node_id,
                node_name=node_name,
                node_kind=node_kind,
                status=status,
                attempt=attempt,
                operations=operations,
                detail=detail,
            )
        )


class Node:
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name

    def execute(self, state: ExecutionState) -> Status:
        raise NotImplementedError


class Sequence(Node):
    """One-shot, memory-style left-to-right sequence."""

    def __init__(self, node_id: str, name: str, children: List[Node]):
        super().__init__(node_id, name)
        self.children = children

    def execute(self, state: ExecutionState) -> Status:
        for child in self.children:
            status = child.execute(state)
            if status == Status.FAILURE:
                return Status.FAILURE
        return Status.SUCCESS


class Fallback(Node):
    """Priority fallback: try children left-to-right until one succeeds."""

    def __init__(self, node_id: str, name: str, children: List[Node]):
        super().__init__(node_id, name)
        self.children = children

    def execute(self, state: ExecutionState) -> Status:
        for child in self.children:
            status = child.execute(state)
            if status == Status.SUCCESS:
                return Status.SUCCESS
        return Status.FAILURE


class Condition(Node):
    def __init__(self, node_id: str, name: str, probability_key: str):
        super().__init__(node_id, name)
        self.probability_key = probability_key

    def execute(self, state: ExecutionState) -> Status:
        probability = float(state.probabilities[self.probability_key])
        ok = state.rng.random() < probability
        status = Status.SUCCESS if ok else Status.FAILURE
        state.record(
            self.node_id,
            self.name,
            "condition",
            status,
            operations=0,
            detail=f"Bernoulli(p={probability:.4f})",
        )
        return status


class Action(Node):
    def __init__(
        self,
        node_id: str,
        name: str,
        outcome_probability_key: Optional[str] = None,
        strategy_label: Optional[str] = None,
    ):
        super().__init__(node_id, name)
        self.outcome_probability_key = outcome_probability_key
        self.strategy_label = strategy_label

    def execute(self, state: ExecutionState, attempt: Optional[int] = None) -> Status:
        if self.outcome_probability_key:
            probability = float(state.probabilities[self.outcome_probability_key])
            ok = state.rng.random() < probability
            status = Status.SUCCESS if ok else Status.FAILURE
            detail = f"Bernoulli(p={probability:.4f})"
        else:
            status = Status.SUCCESS
            detail = "deterministic"

        operations = int(state.operations[self.node_id])
        state.record(
            self.node_id,
            self.name,
            "action",
            status,
            attempt=attempt,
            operations=operations,
            detail=detail,
        )

        if self.strategy_label and status == Status.SUCCESS:
            state.selected_strategy = self.strategy_label

        return status


class Retry(Node):
    """Bounded retry decorator. Retry multiplicity remains a runtime property."""

    def __init__(self, node_id: str, name: str, child: Node, max_attempts: int):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        super().__init__(node_id, name)
        self.child = child
        self.max_attempts = max_attempts

    def execute(self, state: ExecutionState) -> Status:
        for attempt in range(1, self.max_attempts + 1):
            if isinstance(self.child, Action):
                status = self.child.execute(state, attempt=attempt)
            else:
                status = self.child.execute(state)
            if status == Status.SUCCESS:
                return Status.SUCCESS
        return Status.FAILURE
