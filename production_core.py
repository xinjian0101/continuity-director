"""Production planning, Take ranking, reference handoff, and quality helpers."""

from __future__ import annotations

from typing import Any

from .continuity_core import ContinuityError, parse_json
from .production_quality_core import (
    ProductionQualityError,
    normalized_weights,
    quality_report,
    rank_take_records,
    reference_handoff_record,
    score_metrics,
)
from .storyboard_hardening_core import StoryboardError, expand as expand_storyboard_strict

DEFAULT_WEIGHTS = {"identity": 0.35, "continuity": 0.25, "technical": 0.20, "motion": 0.10, "prompt": 0.10}
DEFAULT_THRESHOLDS = {"identity": 0.78, "continuity": 0.72, "technical": 0.70}


def expand_storyboard(storyboard: Any, manifest: dict[str, Any] | None, base_seed: int, takes_per_shot: int) -> dict[str, Any]:
    source = parse_json(storyboard, default=[], expected=(list, dict))
    manifest_data = parse_json(manifest, default={}, expected=dict)
    try:
        return expand_storyboard_strict(source, manifest_data, base_seed, takes_per_shot)
    except StoryboardError as exc:
        raise ContinuityError(str(exc)) from exc


def reference_handoff(previous: Any, current: Any, strategy: str = "last_to_first") -> dict[str, Any]:
    previous_data = parse_json(previous, default={}, expected=dict)
    current_data = parse_json(current, default={}, expected=dict)
    try:
        return reference_handoff_record(previous_data, current_data, strategy)
    except ProductionQualityError as exc:
        raise ContinuityError(str(exc)) from exc


def quality_gate(metrics: Any, thresholds: Any | None = None, mode: str = "all") -> dict[str, Any]:
    metric_data = parse_json(metrics, default={}, expected=dict)
    threshold_data = parse_json(thresholds, default={}, expected=dict)
    try:
        return quality_report(metric_data, threshold_data, mode, DEFAULT_THRESHOLDS)
    except ProductionQualityError as exc:
        raise ContinuityError(str(exc)) from exc


def score_take(metrics: dict[str, Any], weights: dict[str, Any] | None = None) -> float:
    metric_data = parse_json(metrics, default={}, expected=dict)
    weight_data = parse_json(weights, default={}, expected=dict)
    try:
        return score_metrics(metric_data, normalized_weights(weight_data, DEFAULT_WEIGHTS))
    except ProductionQualityError as exc:
        raise ContinuityError(str(exc)) from exc


def rank_takes(takes: Any, weights: Any | None = None) -> list[dict[str, Any]]:
    take_data = parse_json(takes, default=[], expected=list)
    weight_data = parse_json(weights, default={}, expected=dict)
    try:
        return rank_take_records(take_data, weight_data, DEFAULT_WEIGHTS)
    except ProductionQualityError as exc:
        raise ContinuityError(str(exc)) from exc
