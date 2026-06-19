"""Deterministic task planning and dependency-wave scheduling."""

from __future__ import annotations

from typing import Any

from .continuity_core import ContinuityError, parse_json
from .runtime_hardening_core import RuntimeHardeningError, build_waves, execution_plan


def dependency_waves(tasks: Any, max_parallel: int = 4) -> list[list[dict[str, Any]]]:
    task_data = parse_json(tasks, default=[], expected=list)
    try:
        waves, _ = build_waves(task_data, max_parallel)
        return waves
    except RuntimeHardeningError as exc:
        raise ContinuityError(str(exc)) from exc


def build_execution_plan(shot_chain: Any, max_parallel: int = 4) -> dict[str, Any]:
    chain = parse_json(shot_chain, default={}, expected=dict)
    try:
        return execution_plan(chain, max_parallel)
    except RuntimeHardeningError as exc:
        raise ContinuityError(str(exc)) from exc
