"""Deterministic task planning and dependency-wave scheduling."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from .continuity_core import ContinuityError, digest, normalize_id, parse_json, split_csv


def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContinuityError(f"{field} must be an integer") from exc
    return max(minimum, min(maximum, number))


def _dependency_ids(value: Any, task_number: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = split_csv(value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        values = list(value)
    else:
        raise ContinuityError(f"Task {task_number} depends_on must be a string or list")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        dependency = normalize_id(raw, "")
        if dependency and dependency not in seen:
            seen.add(dependency)
            output.append(dependency)
    return output


def dependency_waves(tasks: Any, max_parallel: int = 4) -> list[list[dict[str, Any]]]:
    task_list = parse_json(tasks, default=[], expected=list)
    parallelism = _bounded_int(max_parallel, "max_parallel", 1, 64)
    normalized: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, raw in enumerate(task_list):
        task_number = index + 1
        if not isinstance(raw, dict):
            raise ContinuityError(f"Task {task_number} must be an object")
        task_id = normalize_id(raw.get("task_id") or raw.get("take_id") or raw.get("id") or f"task-{task_number:03d}")
        if task_id in normalized:
            raise ContinuityError(f"Duplicate task id: {task_id}")
        dependencies = _dependency_ids(raw.get("depends_on", []), task_number)
        if task_id in dependencies:
            raise ContinuityError(f"Task {task_id} cannot depend on itself")
        item = copy.deepcopy(raw)
        item["task_id"] = task_id
        item["depends_on"] = dependencies
        normalized[task_id] = item
        order.append(task_id)
    missing = sorted({dependency for item in normalized.values() for dependency in item["depends_on"] if dependency not in normalized})
    if missing:
        raise ContinuityError(f"Unknown dependencies: {', '.join(missing)}")
    pending = set(order)
    completed: set[str] = set()
    waves: list[list[dict[str, Any]]] = []
    while pending:
        ready = [task_id for task_id in order if task_id in pending and set(normalized[task_id]["depends_on"]).issubset(completed)]
        if not ready:
            raise ContinuityError(f"Dependency cycle detected among: {', '.join(sorted(pending))}")
        for start in range(0, len(ready), parallelism):
            batch_ids = ready[start:start + parallelism]
            waves.append([copy.deepcopy(normalized[task_id]) for task_id in batch_ids])
            completed.update(batch_ids)
            pending.difference_update(batch_ids)
    return waves


def build_execution_plan(shot_chain: Any, max_parallel: int = 4) -> dict[str, Any]:
    chain = parse_json(shot_chain, default={}, expected=dict)
    parallelism = _bounded_int(max_parallel, "max_parallel", 1, 64)
    tasks = chain.get("takes", [])
    if not isinstance(tasks, list):
        raise ContinuityError("Shot chain takes must be a list")
    waves = dependency_waves(tasks, max_parallel=parallelism)
    plan = {
        "schema": "continuity-director/execution-plan@1.0",
        "source_hash": str(chain.get("hash", "")),
        "max_parallel": parallelism,
        "task_count": sum(len(wave) for wave in waves),
        "wave_count": len(waves),
        "waves": [{"wave": index + 1, "tasks": wave} for index, wave in enumerate(waves)],
    }
    plan["hash"] = digest(plan)
    return plan
