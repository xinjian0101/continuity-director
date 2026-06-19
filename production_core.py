"""Production planning, take ranking, and quality-gate helpers."""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping
from typing import Any

from .continuity_core import ContinuityError, digest, normalize_id, parse_json, split_csv

DEFAULT_WEIGHTS = {"identity": 0.35, "continuity": 0.25, "technical": 0.20, "motion": 0.10, "prompt": 0.10}
DEFAULT_THRESHOLDS = {"identity": 0.78, "continuity": 0.72, "technical": 0.70}


def _finite_number(value: Any, field: str) -> float:
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


def _integer(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContinuityError(f"{field} must be an integer") from exc


def _duration(value: Any, shot_number: int) -> float:
    duration = _finite_number(value, f"Shot {shot_number} duration_seconds")
    if duration <= 0.0 or duration > 600.0:
        raise ContinuityError(f"Shot {shot_number} duration_seconds must be greater than 0 and at most 600")
    return duration


def _id_list(value: Any, field: str, shot_number: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = split_csv(value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        values = list(value)
    else:
        raise ContinuityError(f"Shot {shot_number} {field} must be a string or list")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = normalize_id(raw, "")
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _references(value: Any, shot_number: int) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return copy.deepcopy(value)
    if isinstance(value, dict):
        return [copy.deepcopy(value)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    raise ContinuityError(f"Shot {shot_number} references must be a list, object, or string")


def expand_storyboard(storyboard: Any, manifest: dict[str, Any] | None, base_seed: int, takes_per_shot: int) -> dict[str, Any]:
    source = parse_json(storyboard, default=[], expected=(list, dict))
    if manifest is not None and not isinstance(manifest, dict):
        raise ContinuityError("Manifest must be an object")
    shots = source.get("shots", []) if isinstance(source, dict) else source
    if not isinstance(shots, list):
        raise ContinuityError("Storyboard 'shots' must be a list")
    take_limit = max(1, min(16, _integer(takes_per_shot, "takes_per_shot")))
    seed_base = _integer(base_seed, "base_seed")
    if seed_base < 0 or seed_base > 2147483647:
        raise ContinuityError("base_seed must be between 0 and 2147483647")
    entries: list[dict[str, Any]] = []
    seen_shots: set[str] = set()
    for shot_index, raw in enumerate(shots):
        shot_number = shot_index + 1
        if isinstance(raw, str):
            raw = {"prompt": raw}
        if not isinstance(raw, dict):
            raise ContinuityError(f"Shot {shot_number} must be an object or string")
        shot_id = normalize_id(raw.get("id") or raw.get("shot_id") or f"shot-{shot_number:03d}")
        if shot_id in seen_shots:
            raise ContinuityError(f"Duplicate shot id: {shot_id}")
        seen_shots.add(shot_id)
        duration = _duration(raw.get("duration_seconds", 3.0), shot_number)
        characters = _id_list(raw.get("character_ids", []), "character_ids", shot_number)
        dependencies = _id_list(raw.get("depends_on", []), "depends_on", shot_number)
        references = _references(raw.get("references", []), shot_number)
        for take_index in range(take_limit):
            generated_seed = seed_base + shot_index * 1000 + take_index
            seed = _integer(raw.get("seed", generated_seed), f"Shot {shot_number} seed")
            if seed < 0 or seed > 2147483647:
                raise ContinuityError(f"Shot {shot_number} seed must be between 0 and 2147483647")
            entries.append({
                "shot_id": shot_id,
                "take_id": f"{shot_id}-take-{take_index + 1:02d}",
                "take_index": take_index + 1,
                "seed": seed,
                "prompt": str(raw.get("prompt") or ""),
                "negative_prompt": str(raw.get("negative_prompt") or ""),
                "scene_id": normalize_id(raw.get("scene_id", "scene-default")),
                "character_ids": characters.copy(),
                "camera": copy.deepcopy(raw.get("camera", {})),
                "duration_seconds": duration,
                "references": copy.deepcopy(references),
                "depends_on": dependencies.copy(),
            })
    chain = {"schema": "continuity-director/shot-chain@1.0", "manifest_hash": (manifest or {}).get("hash", ""), "shot_count": len(shots), "take_count": len(entries), "takes": entries}
    chain["hash"] = digest(chain)
    return chain


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
    return {
        "schema": "continuity-director/quality-gate@1.0",
        "mode": normalized_mode,
        "passed": passed,
        "checks": checks,
        "failed_metrics": [item["metric"] for item in checks if not item["passed"]],
        "missing_metrics": [item["metric"] for item in checks if item["missing"]],
    }


def score_take(metrics: dict[str, Any], weights: dict[str, Any] | None = None) -> float:
    applied = dict(DEFAULT_WEIGHTS)
    if weights:
        applied.update(weights)
    positive = {key: max(0.0, float(value)) for key, value in applied.items()}
    total_weight = sum(positive.values()) or 1.0
    return sum(_clamp(metrics.get(key, 0.0)) * weight for key, weight in positive.items()) / total_weight


def rank_takes(takes: Any, weights: Any | None = None) -> list[dict[str, Any]]:
    take_list = parse_json(takes, default=[], expected=list)
    weight_data = parse_json(weights, default={}, expected=dict)
    ranked: list[dict[str, Any]] = []
    for index, take in enumerate(take_list):
        if not isinstance(take, dict):
            raise ContinuityError(f"Take {index + 1} must be an object")
        item = copy.deepcopy(take)
        item["take_id"] = str(item.get("take_id") or item.get("id") or f"take-{index + 1:03d}")
        item["score"] = round(score_take(item.get("metrics", item), weight_data), 6)
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item["take_id"]))
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    return ranked
