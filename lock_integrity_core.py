"""Lock integrity and manifest reference validation without package import cycles."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
from typing import Any

from .strict_json_core import StrictJSONError, validate_json_value


class LockIntegrityError(ValueError):
    """Raised when a lock or manifest reference is invalid."""


_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise LockIntegrityError(str(exc)) from exc


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_lock_record(kind: str, item_id: str, payload: Any, schema_version: str) -> dict[str, Any]:
    if not _ID_RE.fullmatch(kind):
        raise LockIntegrityError("lock kind is invalid")
    if not _ID_RE.fullmatch(item_id):
        raise LockIntegrityError("lock id is invalid")
    if not _VERSION_RE.fullmatch(schema_version):
        raise LockIntegrityError("schema version must use numeric dot notation")
    data = _canonical(payload)
    if not isinstance(data, dict):
        raise LockIntegrityError("lock payload must be an object")
    body = {"schema": f"continuity-director/{kind}@{schema_version}", "kind": kind, "id": item_id, "data": data}
    body["hash"] = _digest(body)
    return body


def validate_lock_record(value: Any, expected_kind: str, position: int) -> dict[str, Any]:
    item = _canonical(value)
    if not isinstance(item, dict):
        raise LockIntegrityError(f"{expected_kind.title()} lock {position} must be an object")
    kind = str(item.get("kind", "")).strip()
    item_id = str(item.get("id", "")).strip()
    schema = str(item.get("schema", "")).strip()
    supplied_hash = str(item.get("hash", "")).strip().lower()
    if kind != expected_kind:
        raise LockIntegrityError(f"Expected {expected_kind} lock, received {kind or 'missing'} at position {position}")
    if not _ID_RE.fullmatch(item_id):
        raise LockIntegrityError(f"{expected_kind.title()} lock {position} has an invalid id")
    schema_match = re.fullmatch(rf"continuity-director/{re.escape(expected_kind)}@(\d+\.\d+(?:\.\d+)?)", schema)
    if not schema_match:
        raise LockIntegrityError(f"{expected_kind.title()} lock {position} has an invalid schema")
    if not isinstance(item.get("data"), dict):
        raise LockIntegrityError(f"{expected_kind.title()} lock {position} data must be an object")
    canonical = copy.deepcopy(item)
    canonical.pop("hash", None)
    expected_hash = _digest(canonical)
    if not _HASH_RE.fullmatch(supplied_hash) or not hmac.compare_digest(supplied_hash, expected_hash):
        raise LockIntegrityError(f"{expected_kind.title()} lock {item_id} failed integrity verification")
    item["hash"] = supplied_hash
    return item


def validate_manifest_references(project: dict[str, Any], characters: list[dict[str, Any]], scenes: list[dict[str, Any]], shots: list[dict[str, Any]]) -> None:
    project_id = project["id"]
    character_ids = {item["id"] for item in characters}
    scene_ids = {item["id"] for item in scenes}
    for shot in shots:
        data = shot.get("data", {})
        shot_id = shot["id"]
        referenced_project = data.get("project_id")
        if referenced_project not in (None, "", project_id):
            raise LockIntegrityError(f"Shot {shot_id} references unknown project {referenced_project}")
        referenced_scene = data.get("scene_id")
        if referenced_scene not in (None, "") and referenced_scene not in scene_ids:
            raise LockIntegrityError(f"Shot {shot_id} references unknown scene {referenced_scene}")
        referenced_characters = data.get("character_ids", [])
        if not isinstance(referenced_characters, list):
            raise LockIntegrityError(f"Shot {shot_id} character_ids must be a list")
        unknown = sorted({str(item) for item in referenced_characters if str(item) not in character_ids})
        if unknown:
            raise LockIntegrityError(f"Shot {shot_id} references unknown characters: {', '.join(unknown)}")
