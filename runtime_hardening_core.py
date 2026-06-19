"""Strict execution planning and dependency diagnostics."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .strict_json_core import StrictJSONError, validate_json_value


class RuntimeHardeningError(ValueError):
    """Raised when a task graph is malformed or unsafe to schedule."""


_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_TASKS = 10000
MAX_DEPENDENCIES_PER_TASK = 1000


def _canonical(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise RuntimeHardeningError(str(exc)) from exc


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def strict_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise RuntimeHardeningError(f"{field} must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise RuntimeHardeningError(f"{field} must be an integer without truncation")
        number = int(value)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        number = int(value.strip())
    else:
        raise RuntimeHardeningError(f"{field} must be an integer")
    if number < minimum or number > maximum:
        raise RuntimeHardeningError(f"{field} must be between {minimum} and {maximum}")
    return number


def normalize_id(value: Any, field: str, fallback: str | None = None) -> str:
    if isinstance(value, (bool, bytes, bytearray, list, tuple, dict, set)):
        raise RuntimeHardeningError(f"{field} must be a scalar identifier")
    raw = str(value if value is not None else "").strip() or str(fallback or "").strip()
    clean = _ID_RE.sub("-", raw).strip("-._")
    if not clean:
        raise RuntimeHardeningError(f"{field} must not be empty")
    if len(clean) > 128:
        suffix = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:12]
        clean = f"{clean[:115]}-{suffix}"
    return clean


def dependency_ids(value: Any, task_number: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[,;\r\n]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        values = list(value)
    else:
        raise RuntimeHardeningError(f"Task {task_number} depends_on must be a string or list")
    if len(values) > MAX_DEPENDENCIES_PER_TASK:
        raise RuntimeHardeningError(f"Task {task_number} exceeds the {MAX_DEPENDENCIES_PER_TASK} dependency limit")
    output: list[str] = []
    seen: dict[str, str] = {}
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        dependency = normalize_id(raw, f"Task {task_number} dependency")
        previous = seen.get(dependency)
        if previous is not None and previous != text:
            raise RuntimeHardeningError(f"Task {task_number} has colliding dependency ids: {previous} and {text}")
        if dependency not in seen:
            seen[dependency] = text
            output.append(dependency)
    return output


def verify_chain(chain: Any) -> tuple[dict[str, Any], bool]:
    data = _canonical(chain)
    if not isinstance(data, dict):
        raise RuntimeHardeningError("Shot chain must be an object")
    supplied = str(data.get("hash", "")).strip().lower()
    if not supplied:
        return data, False
    body = copy.deepcopy(data)
    body.pop("hash", None)
    expected = _digest(body)
    if not _HASH_RE.fullmatch(supplied) or not hmac.compare_digest(supplied, expected):
        raise RuntimeHardeningError("Shot chain failed integrity verification")
    return data, True


def normalize_tasks(tasks: Any) -> tuple[dict[str, dict[str, Any]], list[str], int]:
    task_list = _canonical(tasks)
    if not isinstance(task_list, list):
        raise RuntimeHardeningError("Tasks must be a list")
    if len(task_list) > MAX_TASKS:
        raise RuntimeHardeningError(f"Task graph exceeds the {MAX_TASKS} task limit")
    normalized: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    raw_ids: dict[str, str] = {}
    dependency_count = 0
    for index, raw in enumerate(task_list, start=1):
        if not isinstance(raw, dict):
            raise RuntimeHardeningError(f"Task {index} must be an object")
        source_id = raw.get("task_id") or raw.get("take_id") or raw.get("id")
        raw_text = str(source_id if source_id is not None else f"task-{index:03d}").strip()
        task_id = normalize_id(source_id, f"Task {index} id", f"task-{index:03d}")
        previous = raw_ids.get(task_id)
        if previous is not None:
            if previous != raw_text:
                raise RuntimeHardeningError(f"Colliding task ids: {previous} and {raw_text}")
            raise RuntimeHardeningError(f"Duplicate task id: {task_id}")
        raw_ids[task_id] = raw_text
        dependencies = dependency_ids(raw.get("depends_on", []), index)
        dependency_count += len(dependencies)
        if task_id in dependencies:
            raise RuntimeHardeningError(f"Task {task_id} cannot depend on itself")
        item = copy.deepcopy(raw)
        item["task_id"] = task_id
        item["depends_on"] = dependencies
        normalized[task_id] = item
        order.append(task_id)
    missing = sorted({dependency for item in normalized.values() for dependency in item["depends_on"] if dependency not in normalized})
    if missing:
        raise RuntimeHardeningError(f"Unknown dependencies: {', '.join(missing)}")
    return normalized, order, dependency_count


def cycle_path(tasks: dict[str, dict[str, Any]], order: list[str]) -> list[str]:
    state: dict[str, int] = {}
    stack: list[str] = []
    stack_index: dict[str, int] = {}

    def visit(task_id: str) -> list[str] | None:
        state[task_id] = 1
        stack_index[task_id] = len(stack)
        stack.append(task_id)
        for dependency in tasks[task_id]["depends_on"]:
            if state.get(dependency, 0) == 0:
                found = visit(dependency)
                if found:
                    return found
            elif state.get(dependency) == 1:
                start = stack_index[dependency]
                return stack[start:] + [dependency]
        stack.pop()
        stack_index.pop(task_id, None)
        state[task_id] = 2
        return None

    for task_id in order:
        if state.get(task_id, 0) == 0:
            found = visit(task_id)
            if found:
                return found
    return []


def build_waves(tasks: Any, max_parallel: Any = 4) -> tuple[list[list[dict[str, Any]]], int]:
    parallelism = strict_int(max_parallel, "max_parallel", 1, 64)
    normalized, order, dependency_count = normalize_tasks(tasks)
    pending = set(order)
    completed: set[str] = set()
    waves: list[list[dict[str, Any]]] = []
    while pending:
        ready = [task_id for task_id in order if task_id in pending and set(normalized[task_id]["depends_on"]).issubset(completed)]
        if not ready:
            path = cycle_path(normalized, order)
            detail = " -> ".join(path) if path else ", ".join(sorted(pending))
            raise RuntimeHardeningError(f"Dependency cycle detected: {detail}")
        for start in range(0, len(ready), parallelism):
            batch_ids = ready[start:start + parallelism]
            waves.append([copy.deepcopy(normalized[task_id]) for task_id in batch_ids])
            completed.update(batch_ids)
            pending.difference_update(batch_ids)
    return waves, dependency_count


def execution_plan(chain: Any, max_parallel: Any = 4) -> dict[str, Any]:
    data, source_verified = verify_chain(chain)
    takes = data.get("takes", [])
    waves, dependency_count = build_waves(takes, max_parallel)
    parallelism = strict_int(max_parallel, "max_parallel", 1, 64)
    plan = {
        "schema": "continuity-director/execution-plan@1.0",
        "source_hash": str(data.get("hash", "")),
        "source_verified": source_verified,
        "max_parallel": parallelism,
        "task_count": sum(len(wave) for wave in waves),
        "dependency_count": dependency_count,
        "wave_count": len(waves),
        "max_wave_width": max((len(wave) for wave in waves), default=0),
        "waves": [{"wave": index + 1, "tasks": wave} for index, wave in enumerate(waves)],
    }
    plan["hash"] = _digest(plan)
    return plan
