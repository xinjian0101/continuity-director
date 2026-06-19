"""Strict reliability, migration, checkpoint, and environment helpers."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import platform
import re
import sys
from typing import Any

from .strict_json_core import StrictJSONError, validate_json_value


class ValidationHardeningError(ValueError):
    """Raised when reliability metadata is unsafe or inconsistent."""


_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SENSITIVE_KEYS = {"token", "password", "secret", "api_key", "apikey", "authorization", "access_key", "private_key"}


def _canonical(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise ValidationHardeningError(str(exc)) from exc


def stable_json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def strict_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValidationHardeningError(f"{field} must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValidationHardeningError(f"{field} must be an integer without truncation")
        number = int(value)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        number = int(value.strip())
    else:
        raise ValidationHardeningError(f"{field} must be an integer")
    if number < minimum or number > maximum:
        raise ValidationHardeningError(f"{field} must be between {minimum} and {maximum}")
    return number


def finite_float(value: Any, field: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValidationHardeningError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationHardeningError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValidationHardeningError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise ValidationHardeningError(f"{field} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ValidationHardeningError(f"{field} must be at most {maximum}")
    return number


def version_tuple(value: Any, field: str) -> tuple[int, ...]:
    text = str(value or "").strip()
    if not _VERSION_RE.fullmatch(text):
        raise ValidationHardeningError(f"{field} must use numeric dot notation")
    return tuple(int(part) for part in text.split("."))


def migrate_record(payload: Any, target_version: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    data = _canonical(payload)
    if not isinstance(data, dict):
        raise ValidationHardeningError("payload must be an object")
    target = str(target_version or "").strip()
    target_parts = version_tuple(target, "target_version")
    schema = str(data.get("schema") or "continuity-director/payload@0.0").strip()
    if "@" in schema:
        prefix, current = schema.rsplit("@", 1)
    else:
        prefix, current = schema, "0.0"
    prefix = prefix.strip() or "continuity-director/payload"
    current = current.strip() or "0.0"
    current_parts = version_tuple(current, "current schema version")
    if target_parts < current_parts:
        raise ValidationHardeningError(f"schema downgrade is not allowed: {current} -> {target}")
    if target_parts == current_parts:
        return copy.deepcopy(data), []
    result = copy.deepcopy(data)
    result["schema"] = f"{prefix}@{target}"
    result["migration"] = {"from_version": current, "target_version": target, "changed": True}
    result.pop("hash", None)
    result["hash"] = digest(result)
    return result, [{"path": "$.schema", "from": current, "to": target}]


def retry_record(max_attempts: Any, base_delay: Any, multiplier: Any, max_delay: Any) -> dict[str, Any]:
    attempts = strict_int(max_attempts, "max_attempts", 1, 100)
    base = finite_float(base_delay, "base_delay_seconds", 0.0, 86400.0)
    factor = finite_float(multiplier, "multiplier", 1.0, 10.0)
    ceiling = finite_float(max_delay, "max_delay_seconds", 0.0, 86400.0)
    if ceiling < base:
        raise ValidationHardeningError("max_delay_seconds must be greater than or equal to base_delay_seconds")
    delays: list[float] = []
    delay = base
    for _ in range(max(0, attempts - 1)):
        delays.append(round(min(delay, ceiling), 6))
        if delay >= ceiling or factor == 1.0:
            delay = ceiling
        elif delay > ceiling / factor:
            delay = ceiling
        else:
            delay *= factor
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


def normalize_id(value: Any, field: str) -> str:
    if isinstance(value, (bool, bytes, bytearray, list, tuple, dict, set)):
        raise ValidationHardeningError(f"{field} must be a scalar identifier")
    raw = str(value if value is not None else "").strip()
    clean = _ID_RE.sub("-", raw).strip("-._")
    if not clean:
        raise ValidationHardeningError(f"{field} must not be empty")
    if len(clean) > 128:
        suffix = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:12]
        clean = f"{clean[:115]}-{suffix}"
    return clean


def verify_hash(data: dict[str, Any], field: str) -> bool:
    supplied = str(data.get("hash", "")).strip().lower()
    if not supplied:
        return False
    body = copy.deepcopy(data)
    body.pop("hash", None)
    expected = digest(body)
    if not _HASH_RE.fullmatch(supplied) or not hmac.compare_digest(supplied, expected):
        raise ValidationHardeningError(f"{field} failed integrity verification")
    return True


def plan_task_order(plan: Any) -> tuple[dict[str, Any], list[str], bool]:
    data = _canonical(plan)
    if not isinstance(data, dict):
        raise ValidationHardeningError("execution plan must be an object")
    verified = verify_hash(data, "execution plan")
    waves = data.get("waves", [])
    if not isinstance(waves, list):
        raise ValidationHardeningError("execution plan waves must be a list")
    order: list[str] = []
    seen: set[str] = set()
    for wave_index, wave in enumerate(waves, start=1):
        if not isinstance(wave, dict):
            raise ValidationHardeningError(f"execution plan wave {wave_index} must be an object")
        tasks = wave.get("tasks", [])
        if not isinstance(tasks, list):
            raise ValidationHardeningError(f"execution plan wave {wave_index} tasks must be a list")
        for task_index, task in enumerate(tasks, start=1):
            if not isinstance(task, dict):
                raise ValidationHardeningError(f"execution plan wave {wave_index} task {task_index} must be an object")
            task_id = normalize_id(task.get("task_id"), f"execution plan wave {wave_index} task {task_index} id")
            if task_id in seen:
                raise ValidationHardeningError(f"duplicate execution plan task id: {task_id}")
            seen.add(task_id)
            order.append(task_id)
    declared_count = data.get("task_count")
    if declared_count is not None and strict_int(declared_count, "task_count", 0, 100000) != len(order):
        raise ValidationHardeningError("execution plan task_count does not match its tasks")
    return data, order, verified


def id_list(value: Any, field: str) -> list[str]:
    data = _canonical(value)
    if not isinstance(data, list):
        raise ValidationHardeningError(f"{field} must be a list")
    output: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(data, start=1):
        task_id = normalize_id(raw, f"{field} item {index}")
        if task_id not in seen:
            seen.add(task_id)
            output.append(task_id)
    return output


def checkpoint_record(plan: Any, completed_ids: Any, failed_ids: Any, created_at: str) -> dict[str, Any]:
    data, order, verified = plan_task_order(plan)
    known = set(order)
    completed = set(id_list(completed_ids, "completed_ids"))
    failed = set(id_list(failed_ids, "failed_ids"))
    overlap = sorted(completed & failed)
    if overlap:
        raise ValidationHardeningError(f"tasks cannot be both completed and failed: {', '.join(overlap)}")
    unknown = sorted((completed | failed) - known)
    if unknown:
        raise ValidationHardeningError(f"unknown checkpoint task ids: {', '.join(unknown)}")
    remaining = [task_id for task_id in order if task_id not in completed and task_id not in failed]
    checkpoint = {
        "schema": "continuity-director/queue-checkpoint@1.0",
        "plan_hash": str(data.get("hash", "")),
        "plan_verified": verified,
        "created_at": created_at,
        "completed": [task_id for task_id in order if task_id in completed],
        "failed": [task_id for task_id in order if task_id in failed],
        "remaining": remaining,
        "remaining_count": len(remaining),
    }
    checkpoint["hash"] = digest(checkpoint)
    return checkpoint


def idempotency_record(namespace: Any, payload: Any) -> tuple[str, str]:
    name = normalize_id(namespace, "namespace")
    canonical = stable_json(payload)
    return f"{name}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}", canonical


def clean_version(value: Any, field: str) -> str:
    text = str(value or "").strip() or "unknown"
    if len(text) > 128 or any(ord(char) < 32 for char in text):
        raise ValidationHardeningError(f"{field} is invalid")
    return text


def reject_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "_", key.lower()).strip("_")
            if normalized in _SENSITIVE_KEYS:
                raise ValidationHardeningError(f"sensitive field is not allowed in environment lock: {path}.{key}")
            reject_sensitive(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_sensitive(item, f"{path}[{index}]")


def normalize_models(models: Any) -> Any:
    data = _canonical(models)
    reject_sensitive(data, "$.models")
    if isinstance(data, dict):
        return copy.deepcopy(data)
    if not isinstance(data, list):
        raise ValidationHardeningError("models must be a list or object")
    output: list[Any] = []
    seen: set[str] = set()
    for index, item in enumerate(data, start=1):
        if isinstance(item, str):
            cleaned: Any = item.strip()
            if not cleaned:
                continue
        elif isinstance(item, dict):
            cleaned = copy.deepcopy(item)
        else:
            raise ValidationHardeningError(f"model inventory item {index} must be a string or object")
        key = stable_json(cleaned)
        if key not in seen:
            seen.add(key)
            output.append(cleaned)
    output.sort(key=stable_json)
    return output


def environment_record(comfyui_version: Any, frontend_version: Any, models: Any, notes: Any) -> dict[str, Any]:
    note_text = str(notes or "").strip()
    if len(note_text) > 10000:
        raise ValidationHardeningError("notes exceeds 10000 characters")
    lock = {
        "schema": "continuity-director/environment-lock@1.0",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": sys.platform,
        "platform_machine": platform.machine() or "unknown",
        "comfyui_version": clean_version(comfyui_version, "comfyui_version"),
        "frontend_version": clean_version(frontend_version, "frontend_version"),
        "models": normalize_models(models),
        "notes": note_text,
    }
    lock["hash"] = digest(lock)
    return lock
