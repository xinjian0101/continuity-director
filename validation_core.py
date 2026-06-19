"""Validation, migration, retry, checkpoint, and environment-lock helpers."""

from __future__ import annotations

import copy
import platform
import re
import sys
from typing import Any

from .continuity_core import ContinuityError, digest, normalize_id, parse_json, stable_json, utc_now

_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def verify_hashed_payload(payload: Any) -> dict[str, Any]:
    data = parse_json(payload, default={}, expected=dict)
    supplied = str(data.get("hash", ""))
    canonical = copy.deepcopy(data)
    canonical.pop("hash", None)
    expected = digest(canonical)
    return {
        "valid": bool(supplied) and supplied == expected,
        "supplied_hash": supplied,
        "expected_hash": expected,
        "schema": data.get("schema"),
    }


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
    attempts = max(1, min(100, int(max_attempts)))
    base = max(0.0, float(base_delay_seconds))
    factor = max(1.0, float(multiplier))
    ceiling = max(base, float(max_delay_seconds))
    delays = [round(min(ceiling, base * (factor ** index)), 6) for index in range(max(0, attempts - 1))]
    policy = {
        "schema": "continuity-director/retry-policy@1.0",
        "max_attempts": attempts,
        "base_delay_seconds": base,
        "multiplier": factor,
        "max_delay_seconds": ceiling,
        "delays_seconds": delays,
    }
    policy["hash"] = digest(policy)
    return policy


def queue_checkpoint(execution_plan: Any, completed_ids: Any = None, failed_ids: Any = None) -> dict[str, Any]:
    plan = parse_json(execution_plan, default={}, expected=dict)
    completed = {normalize_id(value) for value in parse_json(completed_ids, default=[], expected=list)}
    failed = {normalize_id(value) for value in parse_json(failed_ids, default=[], expected=list)}
    tasks = [task for wave in plan.get("waves", []) for task in wave.get("tasks", [])]
    known = {normalize_id(task.get("task_id")) for task in tasks}
    unknown = sorted((completed | failed) - known)
    if unknown:
        raise ContinuityError(f"Unknown checkpoint task ids: {', '.join(unknown)}")
    remaining = [task_id for task_id in sorted(known) if task_id not in completed and task_id not in failed]
    checkpoint = {
        "schema": "continuity-director/queue-checkpoint@1.0",
        "plan_hash": plan.get("hash", ""),
        "created_at": utc_now(),
        "completed": sorted(completed),
        "failed": sorted(failed),
        "remaining": remaining,
        "remaining_count": len(remaining),
    }
    checkpoint["hash"] = digest(checkpoint)
    return checkpoint


def idempotency_key(namespace: str, payload: Any) -> tuple[str, str]:
    data = parse_json(payload, default={})
    canonical = stable_json(data)
    key = f"{normalize_id(namespace, 'continuity-director')}:{digest(canonical)}"
    return key, canonical


def environment_lock(comfyui_version: str, frontend_version: str, models: Any = None, notes: str = "") -> dict[str, Any]:
    model_data = parse_json(models, default=[], expected=(list, dict))
    lock = {
        "schema": "continuity-director/environment-lock@1.0",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": sys.platform,
        "comfyui_version": str(comfyui_version).strip(),
        "frontend_version": str(frontend_version).strip(),
        "models": model_data,
        "notes": str(notes).strip(),
    }
    lock["hash"] = digest(lock)
    return lock
