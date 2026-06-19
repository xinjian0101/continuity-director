"""Revision-safe JSON merge helpers for collaborative production data."""

from __future__ import annotations

import copy
from typing import Any

from .continuity_core import parse_json

_MISSING = object()


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
                    conflicts.append({"path": child_path, "base": None, "current": c, "incoming": i})
                    result[key] = copy.deepcopy(c)
            elif c is _MISSING:
                if i != b:
                    conflicts.append({"path": child_path, "base": b, "current": None, "incoming": i})
            elif i is _MISSING:
                if c != b:
                    conflicts.append({"path": child_path, "base": b, "current": c, "incoming": None})
                    result[key] = copy.deepcopy(c)
            else:
                result[key] = _merge(b, c, i, child_path, conflicts)
        return result
    conflicts.append({"path": path, "base": base, "current": current, "incoming": incoming})
    return copy.deepcopy(current)


def three_way_merge(base: Any, current: Any, incoming: Any) -> tuple[Any, list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    merged = _merge(parse_json(base, default={}), parse_json(current, default={}), parse_json(incoming, default={}), "$", conflicts)
    return merged, conflicts
