"""Strict JSON canonicalization helpers for Continuity Director."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from .continuity_core import ContinuityError

_PATH_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_JSON_DEPTH = 64


def child_path(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    if _PATH_KEY_RE.fullmatch(key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def reject_json_constant(value: str) -> None:
    raise ContinuityError(f"Non-finite JSON number is not allowed: {value}")


def validate_json_value(value: Any, *, path: str = "$", depth: int = 0) -> Any:
    if depth > _MAX_JSON_DEPTH:
        raise ContinuityError(f"JSON nesting exceeds {_MAX_JSON_DEPTH} levels at {path}")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContinuityError(f"Non-finite number at {path}")
        return value
    if isinstance(value, (list, tuple)):
        return [validate_json_value(item, path=child_path(path, index), depth=depth + 1) for index, item in enumerate(value)]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContinuityError(f"JSON object key at {path} must be a string, received {type(key).__name__}")
            output[key] = validate_json_value(item, path=child_path(path, key), depth=depth + 1)
        return output
    raise ContinuityError(f"Unsupported JSON value at {path}: {type(value).__name__}")
