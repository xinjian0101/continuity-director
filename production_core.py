"""Production planning, take ranking, and quality-gate helpers."""

from __future__ import annotations

import copy
from typing import Any

from .continuity_core import ContinuityError, digest, normalize_id, parse_json

DEFAULT_WEIGHTS = {"identity": 0.35, "continuity": 0.25, "technical": 0.20, "motion": 0.10, "prompt": 0.10}
DEFAULT_THRESHOLDS = {"identity": 0.78, "continuity": 0.72, "technical": 0.70}


def _clamp(value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(minimum, min(maximum, number))


def expand_storyboard(storyboard: Any, manifest: dict[str, Any] | None, base_seed: int, takes_per_shot: int) -> dict[str, Any]:
    source = parse_json(storyboard, default=[], expected=(list, dict))
    shots = source.get("shots", []) if isinstance(source, dict) else source
    if not isinstance(shots, list):
        raise ContinuityError("Storyboard 'shots' must be a list")
    takes_per_shot = max(1, min(16, int(takes_per_shot)))
    entries: list[dict[str, Any]] = []
    for shot_index, raw in enumerate(shots):
        if isinstance(raw, str):
            raw = {"prompt": raw}
        if not isinstance(raw, dict):
            raise ContinuityError(f"Shot {shot_index + 1} must be an object or string")
        shot_id = normalize_id(raw.get("id") or raw.get("shot_id") or f"shot-{shot_index + 1:03d}")
        for take_index in range(takes_per_shot):
            seed = int(raw.get("seed", base_seed + shot_index * 1000 + take_index))
            entries.append({"shot_id": shot_id, "take_id": f"{shot_id}-take-{take_index + 1:02d}", "take_index": take_index + 1, "seed": seed, "prompt": str(raw.get("prompt", "")), "negative_prompt": str(raw.get("negative_prompt", "")), "scene_id": normalize_id(raw.get("scene_id", "scene-default")), "character_ids": list(raw.get("character_ids", [])), "camera": copy.deepcopy(raw.get("camera", {})), "duration_seconds": float(raw.get("duration_seconds", 3.0)), "references": copy.deepcopy(raw.get("references", [])), "depends_on": list(raw.get("depends_on", []))})
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
    threshold_data = dict(DEFAULT_THRESHOLDS)
    threshold_data.update(parse_json(thresholds, default={}, expected=dict))
    checks = []
    for name, minimum in threshold_data.items():
        score = _clamp(metric_data.get(name, 0.0))
        minimum = _clamp(minimum)
        checks.append({"metric": name, "score": score, "minimum": minimum, "passed": score >= minimum})
    passed = True if not checks else (any(item["passed"] for item in checks) if mode == "any" else all(item["passed"] for item in checks))
    return {"schema": "continuity-director/quality-gate@1.0", "mode": mode, "passed": passed, "checks": checks, "failed_metrics": [item["metric"] for item in checks if not item["passed"]]}


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
