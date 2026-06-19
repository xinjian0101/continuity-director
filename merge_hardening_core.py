"""List-aware three-way JSON merge with explicit conflict metadata."""

from __future__ import annotations

import copy
from typing import Any

from .strict_json_core import StrictJSONError, child_path, validate_json_value


class MergeHardeningError(ValueError):
    """Raised when merge inputs are not canonical JSON values."""


_MISSING = object()


def _canonical(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise MergeHardeningError(str(exc)) from exc


def _conflict_value(value: Any) -> tuple[bool, Any]:
    if value is _MISSING:
        return False, None
    return True, copy.deepcopy(value)


def _record(path: str, base: Any, current: Any, incoming: Any, conflicts: list[dict[str, Any]], kind: str) -> None:
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


def _merge_mapping(base: dict[str, Any], current: dict[str, Any], incoming: dict[str, Any], path: str, conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(set(base) | set(current) | set(incoming)):
        b = base.get(key, _MISSING)
        c = current.get(key, _MISSING)
        i = incoming.get(key, _MISSING)
        child = child_path(path, key)
        if c is _MISSING and i is _MISSING:
            continue
        if b is _MISSING:
            if c is _MISSING:
                result[key] = copy.deepcopy(i)
            elif i is _MISSING or c == i:
                result[key] = copy.deepcopy(c)
            else:
                _record(child, b, c, i, conflicts, "concurrent-add")
                result[key] = copy.deepcopy(c)
        elif c is _MISSING:
            if i != b:
                _record(child, b, c, i, conflicts, "delete-vs-change")
        elif i is _MISSING:
            if c != b:
                _record(child, b, c, i, conflicts, "change-vs-delete")
                result[key] = copy.deepcopy(c)
        else:
            result[key] = _merge(b, c, i, child, conflicts)
    return result


def _merge_list(base: list[Any], current: list[Any], incoming: list[Any], path: str, conflicts: list[dict[str, Any]]) -> list[Any]:
    result: list[Any] = []
    maximum = max(len(base), len(current), len(incoming))
    for index in range(maximum):
        b = base[index] if index < len(base) else _MISSING
        c = current[index] if index < len(current) else _MISSING
        i = incoming[index] if index < len(incoming) else _MISSING
        child = child_path(path, index)
        if c is _MISSING and i is _MISSING:
            continue
        if b is _MISSING:
            if c is _MISSING:
                result.append(copy.deepcopy(i))
            elif i is _MISSING or c == i:
                result.append(copy.deepcopy(c))
            else:
                _record(child, b, c, i, conflicts, "concurrent-list-add")
                result.append(copy.deepcopy(c))
        elif c is _MISSING:
            if i != b:
                _record(child, b, c, i, conflicts, "list-delete-vs-change")
        elif i is _MISSING:
            if c != b:
                _record(child, b, c, i, conflicts, "list-change-vs-delete")
                result.append(copy.deepcopy(c))
        else:
            result.append(_merge(b, c, i, child, conflicts))
    return result


def _merge(base: Any, current: Any, incoming: Any, path: str, conflicts: list[dict[str, Any]]) -> Any:
    if current == incoming:
        return copy.deepcopy(current)
    if current == base:
        return copy.deepcopy(incoming)
    if incoming == base:
        return copy.deepcopy(current)
    if all(isinstance(value, dict) for value in (base, current, incoming)):
        return _merge_mapping(base, current, incoming, path, conflicts)
    if all(isinstance(value, list) for value in (base, current, incoming)):
        return _merge_list(base, current, incoming, path, conflicts)
    _record(path, base, current, incoming, conflicts, "value-change")
    return copy.deepcopy(current)


def three_way_merge_values(base: Any, current: Any, incoming: Any) -> tuple[Any, list[dict[str, Any]]]:
    base_value = _canonical(base)
    current_value = _canonical(current)
    incoming_value = _canonical(incoming)
    conflicts: list[dict[str, Any]] = []
    merged = _merge(base_value, current_value, incoming_value, "$", conflicts)
    conflicts.sort(key=lambda item: (item["path"], item["kind"]))
    return merged, conflicts
