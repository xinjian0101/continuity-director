"""Revision-safe JSON merge helpers for collaborative production data."""

from __future__ import annotations

from typing import Any

from .continuity_core import ContinuityError, parse_json
from .merge_hardening_core import MergeHardeningError, three_way_merge_values


def three_way_merge(base: Any, current: Any, incoming: Any) -> tuple[Any, list[dict[str, Any]]]:
    base_value = parse_json(base, default={})
    current_value = parse_json(current, default={})
    incoming_value = parse_json(incoming, default={})
    try:
        return three_way_merge_values(base_value, current_value, incoming_value)
    except MergeHardeningError as exc:
        raise ContinuityError(str(exc)) from exc
