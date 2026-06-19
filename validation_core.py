"""Validation, migration, retry, checkpoint, and environment-lock helpers."""

from __future__ import annotations

import copy
import hmac
import re
from typing import Any

from .continuity_core import ContinuityError, digest, parse_json, utc_now
from .validation_hardening_core import (
    ValidationHardeningError,
    checkpoint_record,
    environment_record,
    idempotency_record,
    migrate_record,
    retry_record,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


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
    return {
        "valid": valid,
        "reason": reason,
        "hash_format_valid": valid_format,
        "supplied_hash": supplied,
        "expected_hash": expected,
        "schema": data.get("schema"),
    }


def migrate_payload(payload: Any, target_version: str = "1.0") -> tuple[dict[str, Any], list[dict[str, str]]]:
    data = parse_json(payload, default={}, expected=dict)
    try:
        return migrate_record(data, target_version)
    except ValidationHardeningError as exc:
        raise ContinuityError(str(exc)) from exc


def retry_policy(max_attempts: int, base_delay_seconds: float, multiplier: float, max_delay_seconds: float) -> dict[str, Any]:
    try:
        return retry_record(max_attempts, base_delay_seconds, multiplier, max_delay_seconds)
    except ValidationHardeningError as exc:
        raise ContinuityError(str(exc)) from exc


def queue_checkpoint(execution_plan: Any, completed_ids: Any = None, failed_ids: Any = None) -> dict[str, Any]:
    plan = parse_json(execution_plan, default={}, expected=dict)
    completed = parse_json(completed_ids, default=[], expected=list)
    failed = parse_json(failed_ids, default=[], expected=list)
    try:
        return checkpoint_record(plan, completed, failed, utc_now())
    except ValidationHardeningError as exc:
        raise ContinuityError(str(exc)) from exc


def idempotency_key(namespace: str, payload: Any) -> tuple[str, str]:
    data = parse_json(payload, default={})
    try:
        return idempotency_record(namespace, data)
    except ValidationHardeningError as exc:
        raise ContinuityError(str(exc)) from exc


def environment_lock(comfyui_version: str, frontend_version: str, models: Any = None, notes: str = "") -> dict[str, Any]:
    model_data = parse_json(models, default=[], expected=(list, dict))
    try:
        return environment_record(comfyui_version, frontend_version, model_data, notes)
    except ValidationHardeningError as exc:
        raise ContinuityError(str(exc)) from exc
