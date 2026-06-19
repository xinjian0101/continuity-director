"""Revision-safe JSON merge helpers for collaborative production data."""

from __future__ import annotations

import copy
from typing import Any

from .continuity_core import parse_json

_MISSING = object()


def _conflict_value(value: Any) -> tuple[bool, Any]:
    if value is _MISSING:
        return False, None
    return True, copy.deepcopy(value)


def _record_conflict(path: str, base: Any, current: Any, incoming: Any, conflicts: list[dict[str, Any]], kind: str) -> None:
    base_exists, base_value = _conflict_value(base)
    current_exists, current_value = _conflict_value(current)
    incoming_exists, incoming_value = _conflict_value(incoming)
    conflicts.append({
        "path": path,
        "kind": kind,
        "base": base_value,
        "current": current_value,
        "incoming": incoming_value,
        "base_exists": base_exists,
        "current_exists": current_exists,
        "incoming_exists": incoming_exists,
        "resolution": "current",
    })


def _merge(base: Any, current: Any, incoming: Any, path: str, conflicts: list[dict[str, Any]]) -> Any:
    if current == incoming:
        return copy.deepcopy(current)
    if current == base:
        return copy.deepcopy(incoming)
    if incoming == base:
        return copy.deepcopy(current)
    if all(isinstance(value, dict) for value in (base, current, incoming)):
        result: dict[str, Any] = {}
        for key in sorted(set(base) | set(current) | set(incoming)):
            b, c, i = base.get(key, _MISSING), current.get(key, _MISSING), incoming.get(key, _MISSING)
            child_path = f"{path}.{key}"
            if c is _MISSING and i is _MISSING:
                continue
            if b is _MISSING:
                if c is _MISSING:
                    result[key] = copy.deepcopy(i)
                elif i is _MISSING or c == i:
                    result[key] = copy.deepcopy(c)
                else:
                    _record_conflict(child_path, b, c, i, conflicts, "concurrent-add")
                    result[key] = copy.deepcopy(c)
            elif c is _MISSING:
                if i != b:
                    _record_conflict(child_path, b, c, i, conflicts, "delete-vs-change")
            elif i is _MISSING:
                if c != b:
                    _record_conflict(child_path, b, c, i, conflicts, "change-vs-delete")
                    result[key] = copy.deepcopy(c)
            else:
                result[key] = _merge(b, c, i, child_path, conflicts)
        return result
    _record_conflict(path, base, current, incoming, conflicts, "value-change")
    return copy.deepcopy(current)


def three_way_merge(base: Any, current: Any, incoming: Any) -> tuple[Any, list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    merged = _merge(parse_json(base, default={}), parse_json(current, default={}), parse_json(incoming, default={}), "$", conflicts)
    return merged, conflicts
