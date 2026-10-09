from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

from .models import TraceEvent


def action_events(trace: Iterable[TraceEvent]) -> List[TraceEvent]:
    return [event for event in trace if event.node_kind == "action"]


def build_service_nodes(trace: Iterable[TraceEvent], task_profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    events = action_events(trace)
    counts = Counter(event.node_id for event in events)
    statuses = defaultdict(Counter)
    for event in events:
        statuses[event.node_id][event.status.value] += 1

    result: Dict[str, Dict[str, Any]] = {}
    for node_id, count in counts.items():
        profile = task_profiles[node_id]
        ops_per = int(profile["operations_per_invocation"])
        result[node_id] = {
            "id": node_id,
            "name": profile["task_name"],
            "invocation_count": count,
            "operations_per_invocation": ops_per,
            "total_operations": count * ops_per,
            "success_count": statuses[node_id]["SUCCESS"],
            "failure_count": statuses[node_id]["FAILURE"],
        }
    return result


def topology_signature(service_nodes: Dict[str, Dict[str, Any]], sg_edges: List[Dict[str, Any]]) -> str:
    """Topology excludes invocation multiplicity by design.

    Retry counts affect workload, while Prolog determines the structural SG.
    """
    payload = {
        "nodes": sorted(service_nodes.keys()),
        "edges": sorted(
            [
                [edge["source"], edge["target"], edge["reason"]]
                for edge in sg_edges
            ]
        ),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]
