"""Deterministic continuity data helpers used by the ComfyUI nodes."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Iterable

from .lock_integrity_core import LockIntegrityError, build_lock_record, validate_lock_record, validate_manifest_references
from .strict_json_core import StrictJSONError, reject_json_constant, validate_json_value


class ContinuityError(ValueError):
    """Raised when continuity data is malformed or internally inconsistent."""


_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ID_LENGTH = 128


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_id(value: Any, fallback: str = "item") -> str:
    text = str(value or "").strip()
    text = _ID_RE.sub("-", text).strip("-._") or str(fallback or "item").strip() or "item"
    if len(text) <= MAX_ID_LENGTH:
        return text
    suffix = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{text[: MAX_ID_LENGTH - 13]}-{suffix}"


def require_id(value: Any, field: str, *, fallback: str | None = None) -> str:
    if isinstance(value, (bool, bytes, bytearray, list, tuple, dict, set)):
        raise ContinuityError(f"{field} must be a scalar identifier")
    raw = str(value if value is not None else "").strip()
    if not raw and fallback is None:
        raise ContinuityError(f"{field} must not be empty")
    normalized = normalize_id(raw, fallback or "")
    if not normalized:
        raise ContinuityError(f"{field} contains no valid identifier characters")
    return normalized


def require_schema_version(value: Any, field: str = "schema_version") -> str:
    text = str(value or "").strip()
    if not _VERSION_RE.fullmatch(text):
        raise ContinuityError(f"{field} must use numeric dot notation such as 1.0 or 1.0.1")
    return text


def _validated_json(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise ContinuityError(str(exc)) from exc


def stable_json(value: Any, *, indent: int | None = None) -> str:
    canonical = _validated_json(value)
    return json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":") if indent is None else None, indent=indent, allow_nan=False)


def digest(value: Any) -> str:
    payload = value if isinstance(value, str) else stable_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def integrity_report(value: Any) -> dict[str, Any]:
    data = _validated_json(value)
    if not isinstance(data, dict):
        raise ContinuityError("Hashed payload must be an object")
    supplied = str(data.get("hash", "")).strip().lower()
    body = copy.deepcopy(data)
    body.pop("hash", None)
    expected = digest(body)
    valid_format = bool(_HASH_RE.fullmatch(supplied))
    return {"valid": valid_format and hmac.compare_digest(supplied, expected), "valid_format": valid_format, "supplied": supplied, "expected": expected}


def _expected_name(expected: type | tuple[type, ...]) -> str:
    values = expected if isinstance(expected, tuple) else (expected,)
    return " or ".join(getattr(item, "__name__", str(item)) for item in values)


def parse_json(value: Any, *, default: Any = None, expected: type | tuple[type, ...] | None = None) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        result = _validated_json(default)
    elif isinstance(value, str):
        try:
            result = json.loads(value, parse_constant=reject_json_constant)
        except StrictJSONError as exc:
            raise ContinuityError(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ContinuityError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
        result = _validated_json(result)
    else:
        result = _validated_json(value)
    if expected is not None and not isinstance(result, expected):
        raise ContinuityError(f"Expected {_expected_name(expected)}, received {type(result).__name__}")
    return result


def split_csv(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray, Mapping)):
        raise ContinuityError("CSV input must be a string or an iterable of scalar values")
    parts = re.split(r"[,;\r\n]+", value) if isinstance(value, str) else list(value)
    output: list[str] = []
    seen: set[str] = set()
    for item in parts:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def build_lock(kind: str, item_id: str, payload: dict[str, Any], *, schema_version: str = "1.0") -> dict[str, Any]:
    clean_kind = require_id(kind, "lock kind", fallback="lock")
    clean_id = require_id(item_id, "lock id", fallback=clean_kind)
    version = require_schema_version(schema_version)
    try:
        return build_lock_record(clean_kind, clean_id, payload, version)
    except LockIntegrityError as exc:
        raise ContinuityError(str(exc)) from exc


def _validated_lock(value: Any, kind: str, position: int) -> dict[str, Any]:
    try:
        return validate_lock_record(value, kind, position)
    except LockIntegrityError as exc:
        raise ContinuityError(str(exc)) from exc


def _lock_collection(values: Any, kind: str) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ContinuityError(f"{kind.title()} locks must be a list")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, value in enumerate(values, start=1):
        item = _validated_lock(value, kind, position)
        item_id = item["id"]
        if item_id in seen:
            raise ContinuityError(f"Duplicate {kind} lock id: {item_id}")
        seen.add(item_id)
        output.append(item)
    return output


def build_manifest(project: dict[str, Any], characters: list[dict[str, Any]] | None = None, scenes: list[dict[str, Any]] | None = None, shots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    project_lock = _validated_lock(project, "project", 1)
    character_locks = _lock_collection(characters, "character")
    scene_locks = _lock_collection(scenes, "scene")
    shot_locks = _lock_collection(shots, "shot")
    try:
        validate_manifest_references(project_lock, character_locks, scene_locks, shot_locks)
    except LockIntegrityError as exc:
        raise ContinuityError(str(exc)) from exc
    manifest = {"schema": "continuity-director/manifest@1.0", "project": project_lock, "characters": character_locks, "scenes": scene_locks, "shots": shot_locks}
    manifest["hash"] = digest(manifest)
    return manifest


def _flatten(value: Any, prefix: str = "$") -> dict[str, Any]:
    output: dict[str, Any] = {}
    if isinstance(value, dict):
        if not value:
            output[prefix] = {}
        for key in sorted(value):
            output.update(_flatten(value[key], f"{prefix}.{key}"))
    elif isinstance(value, list):
        if not value:
            output[prefix] = []
        for index, item in enumerate(value):
            output.update(_flatten(item, f"{prefix}[{index}]"))
    else:
        output[prefix] = value
    return output


def _path_is_ignored(path: str, ignored: tuple[str, ...]) -> bool:
    for raw in ignored:
        item = raw[:-2] if raw.endswith(".*") else raw
        if path == item or path.startswith(f"{item}.") or path.startswith(f"{item}["):
            return True
    return False


def continuity_diff(expected: Any, actual: Any, ignore_paths: Iterable[str] | None = None) -> list[dict[str, Any]]:
    ignored = tuple(path.strip() for path in (ignore_paths or []) if path.strip())
    left = _flatten(expected)
    right = _flatten(actual)
    issues: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        if ignored and _path_is_ignored(path, ignored):
            continue
        if path not in left:
            issues.append({"path": path, "type": "unexpected", "actual": right[path]})
        elif path not in right:
            issues.append({"path": path, "type": "missing", "expected": left[path]})
        elif left[path] != right[path]:
            issues.append({"path": path, "type": "changed", "expected": left[path], "actual": right[path]})
    return issues


def audit_event(event_type: str, actor: str, payload: Any, previous_hash: str = "") -> dict[str, Any]:
    event = {"schema": "continuity-director/audit-event@1.0", "timestamp": utc_now(), "event_type": normalize_id(event_type, "event"), "actor": str(actor or "local").strip() or "local", "payload": copy.deepcopy(payload), "previous_hash": str(previous_hash or "")}
    event["hash"] = digest(event)
    return event


def package_payload(**sections: Any) -> dict[str, Any]:
    payload = {"schema": "continuity-director/package@1.0", "created_at": utc_now(), "sections": {key: copy.deepcopy(value) for key, value in sections.items() if value is not None}}
    payload["hash"] = digest(payload)
    return payload
