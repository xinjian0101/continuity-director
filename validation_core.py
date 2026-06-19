"""Validation, migration, retry, checkpoint, and environment-lock helpers."""

from __future__ import annotations

import copy
import hmac
import math
import platform
import re
import sys
from typing import Any

from .continuity_core import ContinuityError, digest, normalize_id, parse_json, stable_json, utc_now

_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContinuityError(f"{field} must be an integer") from exc
    return max(minimum, min(maximum, number))


def _finite_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContinuityError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ContinuityError(f"{field} must be finite")
    return number


def verify_hashed_payload(payload: Any) -> dict[str, Any]:
    data = parse_json(payload, default={}, expected=dict)
    supplied = str(data.get("hash", "")).strip().lower()
    canonical = copy.deepcopy(data)
    canonical.pop("hash", None)
    expected = digest(canonical)
    valid_format = bool(_HASH_RE.fullmatch(supplied))
    valid = valid_format and hmac.compare_digest(supplied, expected)
    if not supplied:
        reason = "missing-hash"
    elif not valid_format:
        reason = "invalid-hash-format"
    elif not valid:
        reason = "hash-mismatch"
    else:
        reason = "valid"
    return {"valid": valid, "reason": reason, "hash_format_valid": valid_format, "supplied_hash": supplied, "expected_hash": expected, "schema": data.get("schema")}


def migrate_payload(payload: Any, target_version: str = "1.0") -> tuple[dict[str, Any], list[dict[str, str]]]:
    data = parse_json(payload, default={}, expected=dict)
    target = str(target_version or "").strip()
    if not _VERSION_RE.fullmatch(target):
        raise ContinuityError("target_version must use numeric dot notation such as 1.0 or 1.0.1")
    schema = str(data.get("schema") or "continuity-director/payload@0.0").strip()
    if "@" in schema:
        prefix, current = schema.rsplit("@", 1)
    else:
        prefix, current = schema, "0.0"
    prefix = prefix.strip() or "continuity-director/payload"
    current = current.strip() or "0.0"
    if current == target:
        return copy.deepcopy(data), []
    result = copy.deepcopy(data)
    result["schema"] = f"{prefix}@{target}"
    changes = [{"path": "$.schema", "from": current, "to": target}]
    result["migration"] = {"target_version": target, "changed": True}
    result.pop("hash", None)
    result["hash"] = digest(result)
    return result, changes


def retry_policy(max_attempts: int, base_delay_seconds: float, multiplier: float, max_delay_seconds: float) -> dict[str, Any]:
    attempts = _bounded_int(max_attempts, "max_attempts", 1, 100)
    base = max(0.0, _finite_float(base_delay_seconds, "base_delay_seconds"))
    factor = max(1.0, min(10.0, _finite_float(multiplier, "multiplier")))
    ceiling = max(base, max(0.0, _finite_float(max_delay_seconds, "max_delay_seconds")))
    delays: list[float] = []
    delay = min(base, ceiling)
    for _ in range(max(0, attempts - 1)):
        delays.append(round(delay, 6))
        if delay >= ceiling or factor == 1.0:
            delay = ceiling if delay >= ceiling else delay
        elif delay > ceiling / factor:
            delay = ceiling
        else:
            delay = min(ceiling, delay * factor)
    policy = {"schema": "continuity-director/retry-policy@1.0", "max_attempts": attempts, "base_delay_seconds": base, "multiplier": factor, "max_delay_seconds": ceiling, "delays_seconds": delays}
    policy["hash"] = digest(policy)
    return policy


def _checkpoint_ids(value: Any, field: str) -> list[str]:
    values = parse_json(value, default=[], expected=list)
    output: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(values, start=1):
        task_id = normalize_id(raw, "")
        if not task_id:
            raise ContinuityError(f"{field} item {index} must contain a task id")
        if task_id not in seen:
            seen.add(task_id)
            output.append(task_id)
    return output


def _plan_task_order(plan: dict[str, Any]) -> list[str]:
    waves = plan.get("waves", [])
    if not isinstance(waves, list):
        raise ContinuityError("Execution plan waves must be a list")
    order: list[str] = []
    seen: set[str] = set()
    for wave_index, wave in enumerate(waves, start=1):
        if not isinstance(wave, dict):
            raise ContinuityError(f"Execution plan wave {wave_index} must be an object")
        tasks = wave.get("tasks", [])
        if not isinstance(tasks, list):
            raise ContinuityError(f"Execution plan wave {wave_index} tasks must be a list")
        for task_index, task in enumerate(tasks, start=1):
            if not isinstance(task, dict):
                raise ContinuityError(f"Execution plan wave {wave_index} task {task_index} must be an object")
            task_id = normalize_id(task.get("task_id"), "")
            if not task_id:
                raise ContinuityError(f"Execution plan wave {wave_index} task {task_index} is missing task_id")
            if task_id in seen:
                raise ContinuityError(f"Duplicate execution plan task id: {task_id}")
            seen.add(task_id)
            order.append(task_id)
    return order


def queue_checkpoint(execution_plan: Any, completed_ids: Any = None, failed_ids: Any = None) -> dict[str, Any]:
    plan = parse_json(execution_plan, default={}, expected=dict)
    order = _plan_task_order(plan)
    known = set(order)
    completed = set(_checkpoint_ids(completed_ids, "completed_ids"))
    failed = set(_checkpoint_ids(failed_ids, "failed_ids"))
    overlap = sorted(completed & failed)
    if overlap:
        raise ContinuityError(f"Tasks cannot be both completed and failed: {', '.join(overlap)}")
    unknown = sorted((completed | failed) - known)
    if unknown:
        raise ContinuityError(f"Unknown checkpoint task ids: {', '.join(unknown)}")
    remaining = [task_id for task_id in order if task_id not in completed and task_id not in failed]
    checkpoint = {"schema": "continuity-director/queue-checkpoint@1.0", "plan_hash": str(plan.get("hash", "")), "created_at": utc_now(), "completed": [task_id for task_id in order if task_id in completed], "failed": [task_id for task_id in order if task_id in failed], "remaining": remaining, "remaining_count": len(remaining)}
    checkpoint["hash"] = digest(checkpoint)
    return checkpoint


def idempotency_key(namespace: str, payload: Any) -> tuple[str, str]:
    data = parse_json(payload, default={})
    canonical = stable_json(data)
    key = f"{normalize_id(namespace, 'continuity-director')}:{digest(canonical)}"
    return key, canonical


def _clean_version(value: Any) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _normalize_models(models: Any) -> Any:
    model_data = parse_json(models, default=[], expected=(list, dict))
    if isinstance(model_data, dict):
        return copy.deepcopy(model_data)
    normalized: list[Any] = []
    seen: set[str] = set()
    for index, item in enumerate(model_data, start=1):
        if isinstance(item, str):
            cleaned: Any = item.strip()
            if not cleaned:
                continue
        elif isinstance(item, dict):
            cleaned = copy.deepcopy(item)
        else:
            raise ContinuityError(f"Model inventory item {index} must be a string or object")
        key = stable_json(cleaned)
        if key not in seen:
            seen.add(key)
            normalized.append(cleaned)
    normalized.sort(key=stable_json)
    return normalized


def environment_lock(comfyui_version: str, frontend_version: str, models: Any = None, notes: str = "") -> dict[str, Any]:
    lock = {
        "schema": "continuity-director/environment-lock@1.0",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": sys.platform,
        "platform_machine": platform.machine() or "unknown",
        "comfyui_version": _clean_version(comfyui_version),
        "frontend_version": _clean_version(frontend_version),
        "models": _normalize_models(models),
        "notes": str(notes or "").strip(),
    }
    lock["hash"] = digest(lock)
    return lock
