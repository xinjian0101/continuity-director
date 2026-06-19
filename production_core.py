"""Production planning, take ranking, and quality-gate helpers."""

from __future__ import annotations

import copy
import math
from typing import Any

from .continuity_core import ContinuityError, digest, normalize_id, parse_json
from .storyboard_hardening_core import StoryboardError, expand as expand_storyboard_strict

DEFAULT_WEIGHTS = {"identity": 0.35, "continuity": 0.25, "technical": 0.20, "motion": 0.10, "prompt": 0.10}
DEFAULT_THRESHOLDS = {"identity": 0.78, "continuity": 0.72, "technical": 0.70}


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ContinuityError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContinuityError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ContinuityError(f"{field} must be finite")
    return number


def _clamp(value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    if not math.isfinite(number):
        return minimum
    return max(minimum, min(maximum, number))


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
    strategy = strategy if strategy in {"last_to_first", "shared_anchor", "manual"} else "last_to_first"
    if strategy == "last_to_first":
        selected = previous_data.get("last_frame") or previous_data.get("frame") or previous_data.get("asset")
    elif strategy == "shared_anchor":
        selected = current_data.get("anchor") or previous_data.get("anchor")
    else:
        selected = current_data.get("manual")
    result = {"schema": "continuity-director/reference-handoff@1.0", "strategy": strategy, "selected_reference": selected, "previous": previous_data, "current": current_data}
    result["hash"] = digest(result)
    return result


def quality_gate(metrics: Any, thresholds: Any | None = None, mode: str = "all") -> dict[str, Any]:
    metric_data = parse_json(metrics, default={}, expected=dict)
    supplied_thresholds = parse_json(thresholds, default={}, expected=dict)
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"all", "any"}:
        raise ContinuityError("Quality gate mode must be 'all' or 'any'")
    threshold_data = dict(DEFAULT_THRESHOLDS)
    for raw_name, value in supplied_thresholds.items():
        name = str(raw_name).strip()
        if not name:
            raise ContinuityError("Quality gate metric names must not be empty")
        threshold_data[name] = value
    checks = []
    for name in sorted(threshold_data):
        minimum = _clamp(threshold_data[name])
        score = _clamp(metric_data.get(name, 0.0))
        checks.append({"metric": name, "score": score, "minimum": minimum, "passed": score >= minimum, "missing": name not in metric_data})
    passed = True if not checks else (any(item["passed"] for item in checks) if normalized_mode == "any" else all(item["passed"] for item in checks))
    return {"schema": "continuity-director/quality-gate@1.0", "mode": normalized_mode, "passed": passed, "checks": checks, "failed_metrics": [item["metric"] for item in checks if not item["passed"]], "missing_metrics": [item["metric"] for item in checks if item["missing"]]}


def _normalized_weights(weights: dict[str, Any] | None) -> dict[str, float]:
    applied: dict[str, Any] = dict(DEFAULT_WEIGHTS)
    if weights:
        applied.update(weights)
    output: dict[str, float] = {}
    for raw_name, raw_weight in applied.items():
        name = str(raw_name).strip()
        if not name:
            raise ContinuityError("Take weight names must not be empty")
        output[name] = max(0.0, _finite_number(raw_weight, f"Weight {name}"))
    return output


def score_take(metrics: dict[str, Any], weights: dict[str, Any] | None = None) -> float:
    if not isinstance(metrics, dict):
        raise ContinuityError("Take metrics must be an object")
    positive = _normalized_weights(weights)
    total_weight = sum(positive.values())
    if total_weight <= 0.0:
        return 0.0
    return sum(_clamp(metrics.get(key, 0.0)) * weight for key, weight in positive.items()) / total_weight


def rank_takes(takes: Any, weights: Any | None = None) -> list[dict[str, Any]]:
    take_list = parse_json(takes, default=[], expected=list)
    weight_data = parse_json(weights, default={}, expected=dict)
    ranked: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, take in enumerate(take_list):
        if not isinstance(take, dict):
            raise ContinuityError(f"Take {index + 1} must be an object")
        item = copy.deepcopy(take)
        take_id = normalize_id(item.get("take_id") or item.get("id") or f"take-{index + 1:03d}", f"take-{index + 1:03d}")
        if take_id in seen_ids:
            raise ContinuityError(f"Duplicate take id: {take_id}")
        seen_ids.add(take_id)
        metric_values = item.get("metrics", item)
        if not isinstance(metric_values, dict):
            raise ContinuityError(f"Take {take_id} metrics must be an object")
        item["take_id"] = take_id
        item["score"] = round(score_take(metric_values, weight_data), 6)
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item["take_id"]))
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    return ranked
