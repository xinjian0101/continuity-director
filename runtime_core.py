"""Deterministic task planning and dependency-wave scheduling."""

from __future__ import annotations

import copy
from typing import Any

from .continuity_core import ContinuityError, digest, normalize_id, parse_json


def dependency_waves(tasks: Any, max_parallel: int = 4) -> list[list[dict[str, Any]]]:
    task_list = parse_json(tasks, default=[], expected=list)
    max_parallel = max(1, min(64, int(max_parallel)))
    normalized: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, raw in enumerate(task_list):
        if not isinstance(raw, dict):
            raise ContinuityError(f"Task {index + 1} must be an object")
        task_id = normalize_id(raw.get("task_id") or raw.get("take_id") or raw.get("id") or f"task-{index + 1:03d}")
        if task_id in normalized:
            raise ContinuityError(f"Duplicate task id: {task_id}")
        item = copy.deepcopy(raw)
        item["task_id"] = task_id
        item["depends_on"] = [normalize_id(value) for value in raw.get("depends_on", [])]
        normalized[task_id] = item
        order.append(task_id)
    missing = sorted({dep for item in normalized.values() for dep in item["depends_on"] if dep not in normalized})
    if missing:
        raise ContinuityError(f"Unknown dependencies: {', '.join(missing)}")
    pending = set(order)
    completed: set[str] = set()
    waves: list[list[dict[str, Any]]] = []
    while pending:
        ready = [task_id for task_id in order if task_id in pending and set(normalized[task_id]["depends_on"]).issubset(completed)]
        if not ready:
            raise ContinuityError(f"Dependency cycle detected among: {', '.join(sorted(pending))}")
        for start in range(0, len(ready), max_parallel):
            batch_ids = ready[start:start + max_parallel]
            waves.append([copy.deepcopy(normalized[task_id]) for task_id in batch_ids])
            completed.update(batch_ids)
            pending.difference_update(batch_ids)
    return waves


def build_execution_plan(shot_chain: Any, max_parallel: int = 4) -> dict[str, Any]:
    chain = parse_json(shot_chain, default={}, expected=dict)
    waves = dependency_waves(chain.get("takes", []), max_parallel=max_parallel)
    plan = {"schema": "continuity-director/execution-plan@1.0", "source_hash": chain.get("hash", ""), "max_parallel": int(max_parallel), "task_count": sum(len(wave) for wave in waves), "wave_count": len(waves), "waves": [{"wave": index + 1, "tasks": wave} for index, wave in enumerate(waves)]}
    plan["hash"] = digest(plan)
    return plan
