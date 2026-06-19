"""Deterministic continuity data helpers used by the ComfyUI nodes."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Iterable


class ContinuityError(ValueError):
    """Raised when continuity data is malformed or internally inconsistent."""


_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_id(value: Any, fallback: str = "item") -> str:
    text = str(value or "").strip()
    text = _ID_RE.sub("-", text).strip("-._")
    return text or fallback


def stable_json(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":") if indent is None else None, indent=indent)


def digest(value: Any) -> str:
    payload = value if isinstance(value, str) else stable_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_name(expected: type | tuple[type, ...]) -> str:
    values = expected if isinstance(expected, tuple) else (expected,)
    return " or ".join(getattr(item, "__name__", str(item)) for item in values)


def parse_json(value: Any, *, default: Any = None, expected: type | tuple[type, ...] | None = None) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        result = copy.deepcopy(default)
    elif isinstance(value, str):
        try:
            result = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ContinuityError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    else:
        result = copy.deepcopy(value)
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
    clean_kind = normalize_id(kind, "lock")
    clean_id = normalize_id(item_id, clean_kind)
    body = {"schema": f"continuity-director/{clean_kind}@{schema_version}", "kind": clean_kind, "id": clean_id, "data": copy.deepcopy(payload)}
    body["hash"] = digest(body)
    return body


def _validated_lock(value: Any, kind: str, position: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContinuityError(f"{kind.title()} lock {position} must be an object")
    item_id = str(value.get("id", "")).strip()
    if not item_id:
        raise ContinuityError(f"{kind.title()} lock {position} is missing id")
    supplied_kind = str(value.get("kind", kind)).strip()
    if supplied_kind and supplied_kind != kind:
        raise ContinuityError(f"Expected {kind} lock, received {supplied_kind} at position {position}")
    return copy.deepcopy(value)


def _lock_collection(values: Any, kind: str) -> list[dict[str, Any]]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ContinuityError(f"{kind.title()} locks must be a list")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, value in enumerate(values, start=1):
        item = _validated_lock(value, kind, position)
        item_id = normalize_id(item["id"], kind)
        if item_id in seen:
            raise ContinuityError(f"Duplicate {kind} lock id: {item_id}")
        seen.add(item_id)
        output.append(item)
    return output


def build_manifest(project: dict[str, Any], characters: list[dict[str, Any]] | None = None, scenes: list[dict[str, Any]] | None = None, shots: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    project_lock = _validated_lock(project, "project", 1)
    manifest = {
        "schema": "continuity-director/manifest@1.0",
        "project": project_lock,
        "characters": _lock_collection(characters, "character"),
        "scenes": _lock_collection(scenes, "scene"),
        "shots": _lock_collection(shots, "shot"),
    }
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
