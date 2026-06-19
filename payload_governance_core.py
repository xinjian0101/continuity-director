"""Diff, audit-chain, and package governance helpers without import cycles."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .strict_json_core import StrictJSONError, child_path, validate_json_value


class PayloadGovernanceError(ValueError):
    """Raised when governed payload data is invalid."""


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SECTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


def _canonical(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise PayloadGovernanceError(str(exc)) from exc


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _integrity(value: Any) -> tuple[bool, str, str]:
    item = _canonical(value)
    if not isinstance(item, dict):
        return False, "", ""
    supplied = str(item.get("hash", "")).strip().lower()
    body = copy.deepcopy(item)
    body.pop("hash", None)
    expected = _digest(body)
    return bool(_HASH_RE.fullmatch(supplied)) and hmac.compare_digest(supplied, expected), supplied, expected


def _flatten(value: Any, path: str, output: dict[str, Any]) -> None:
    if isinstance(value, dict):
        if not value:
            output[path] = {}
        for key in sorted(value):
            output_path = child_path(path, key)
            _flatten(value[key], output_path, output)
    elif isinstance(value, list):
        if not value:
            output[path] = []
        for index, item in enumerate(value):
            _flatten(item, child_path(path, index), output)
    else:
        output[path] = value


def normalize_ignore_paths(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw = re.split(r"[,;\r\n]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        raw = list(value)
    else:
        raise PayloadGovernanceError("ignore_paths must be a string or list")
    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        path = str(item).strip()
        if not path:
            continue
        if not path.startswith("$"):
            raise PayloadGovernanceError(f"ignore path must start with $: {path}")
        if path not in seen:
            seen.add(path)
            output.append(path)
    return tuple(output)


def _ignored(path: str, ignored: tuple[str, ...]) -> bool:
    for raw in ignored:
        base = raw[:-2] if raw.endswith(".*") else raw
        if path == base or path.startswith(f"{base}.") or path.startswith(f"{base}["):
            return True
    return False


def continuity_issues(expected: Any, actual: Any, ignore_paths: Any = None, max_issues: int = 10000) -> list[dict[str, Any]]:
    left_value = _canonical(expected)
    right_value = _canonical(actual)
    try:
        limit = int(max_issues)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PayloadGovernanceError("max_issues must be an integer") from exc
    if isinstance(max_issues, bool) or limit < 1 or limit > 100000:
        raise PayloadGovernanceError("max_issues must be between 1 and 100000")
    ignored = normalize_ignore_paths(ignore_paths)
    left: dict[str, Any] = {}
    right: dict[str, Any] = {}
    _flatten(left_value, "$", left)
    _flatten(right_value, "$", right)
    paths = sorted(set(left) | set(right))
    issues: list[dict[str, Any]] = []
    for path in paths:
        if _ignored(path, ignored):
            continue
        if path not in left:
            issues.append({"path": path, "type": "unexpected", "actual": right[path]})
        elif path not in right:
            issues.append({"path": path, "type": "missing", "expected": left[path]})
        elif left[path] != right[path]:
            issues.append({"path": path, "type": "changed", "expected": left[path], "actual": right[path]})
        if len(issues) >= limit:
            issues.append({"path": "$", "type": "truncated", "limit": limit})
            break
    return issues


def audit_record(event_type: str, actor: str, payload: Any, previous_hash: str = "") -> dict[str, Any]:
    event_name = str(event_type or "").strip()
    actor_name = str(actor or "").strip()
    predecessor = str(previous_hash or "").strip().lower()
    if not event_name:
        raise PayloadGovernanceError("event_type must not be empty")
    if len(event_name) > 128:
        raise PayloadGovernanceError("event_type exceeds 128 characters")
    if not actor_name:
        raise PayloadGovernanceError("actor must not be empty")
    if len(actor_name) > 256:
        raise PayloadGovernanceError("actor exceeds 256 characters")
    if predecessor and not _HASH_RE.fullmatch(predecessor):
        raise PayloadGovernanceError("previous_hash must be empty or a 64-character SHA-256 hash")
    event = {
        "schema": "continuity-director/audit-event@1.0",
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "event_type": event_name,
        "actor": actor_name,
        "payload": _canonical(payload),
        "previous_hash": predecessor,
        "chain_root": not bool(predecessor),
    }
    event["hash"] = _digest(event)
    return event


def package_record(sections: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(sections, Mapping):
        raise PayloadGovernanceError("sections must be a mapping")
    normalized: dict[str, Any] = {}
    integrity: dict[str, str] = {}
    for raw_name, value in sections.items():
        if value is None:
            continue
        name = str(raw_name).strip()
        if not _SECTION_RE.fullmatch(name):
            raise PayloadGovernanceError(f"invalid package section name: {name or 'empty'}")
        item = _canonical(value)
        if isinstance(item, dict) and "hash" in item:
            valid, _, _ = _integrity(item)
            if not valid:
                raise PayloadGovernanceError(f"package section {name} failed integrity verification")
            integrity[name] = "verified"
        else:
            integrity[name] = "unhashed"
        normalized[name] = item
    if not normalized:
        raise PayloadGovernanceError("package must contain at least one section")
    payload = {
        "schema": "continuity-director/package@1.0",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sections": normalized,
        "section_integrity": integrity,
    }
    payload["hash"] = _digest(payload)
    return payload
