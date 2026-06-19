"""Strict reference handoff, quality-gate, and Take ranking helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any

from .strict_json_core import StrictJSONError, validate_json_value


class ProductionQualityError(ValueError):
    """Raised when quality or ranking inputs are invalid."""


_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _canonical(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise ProductionQualityError(str(exc)) from exc


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _id(value: Any, field: str, fallback: str | None = None) -> str:
    if isinstance(value, (bool, list, tuple, dict, set, bytes, bytearray)):
        raise ProductionQualityError(f"{field} must be a scalar identifier")
    raw = str(value if value is not None else "").strip() or str(fallback or "").strip()
    clean = _ID_RE.sub("-", raw).strip("-._")
    if not clean:
        raise ProductionQualityError(f"{field} must not be empty")
    if len(clean) > 128:
        suffix = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:12]
        clean = f"{clean[:115]}-{suffix}"
    return clean


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ProductionQualityError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductionQualityError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ProductionQualityError(f"{field} must be finite")
    return number


def unit_interval(value: Any, field: str) -> float:
    number = _finite(value, field)
    if number < 0.0 or number > 1.0:
        raise ProductionQualityError(f"{field} must be between 0 and 1")
    return number


def _named_values(values: Any, field: str) -> dict[str, Any]:
    data = _canonical(values)
    if not isinstance(data, dict):
        raise ProductionQualityError(f"{field} must be an object")
    output: dict[str, Any] = {}
    raw_by_name: dict[str, str] = {}
    for raw_name, value in data.items():
        name = raw_name.strip()
        if not name:
            raise ProductionQualityError(f"{field} names must not be empty")
        previous = raw_by_name.get(name)
        if previous is not None and previous != raw_name:
            raise ProductionQualityError(f"{field} contains colliding names: {previous!r} and {raw_name!r}")
        raw_by_name[name] = raw_name
        output[name] = value
    return output


def reference_handoff_record(previous: Any, current: Any, strategy: str) -> dict[str, Any]:
    previous_data = _canonical(previous)
    current_data = _canonical(current)
    if not isinstance(previous_data, dict) or not isinstance(current_data, dict):
        raise ProductionQualityError("Reference handoff inputs must be objects")
    normalized_strategy = str(strategy or "").strip().lower()
    if normalized_strategy not in {"last_to_first", "shared_anchor", "manual"}:
        raise ProductionQualityError("Reference handoff strategy must be last_to_first, shared_anchor, or manual")
    selected = None
    selected_from = ""
    if normalized_strategy == "last_to_first":
        for key in ("last_frame", "frame", "asset"):
            if key in previous_data and previous_data[key] is not None:
                selected = previous_data[key]
                selected_from = f"previous.{key}"
                break
    elif normalized_strategy == "shared_anchor":
        if current_data.get("anchor") is not None:
            selected = current_data["anchor"]
            selected_from = "current.anchor"
        elif previous_data.get("anchor") is not None:
            selected = previous_data["anchor"]
            selected_from = "previous.anchor"
    elif "manual" in current_data and current_data["manual"] is not None:
        selected = current_data["manual"]
        selected_from = "current.manual"
    if selected is None:
        raise ProductionQualityError(f"No usable reference was found for strategy {normalized_strategy}")
    result = {
        "schema": "continuity-director/reference-handoff@1.0",
        "strategy": normalized_strategy,
        "selected_reference": copy.deepcopy(selected),
        "selected_from": selected_from,
        "previous": previous_data,
        "current": current_data,
    }
    result["hash"] = _digest(result)
    return result


def quality_report(metrics: Any, thresholds: Any, mode: str, defaults: dict[str, float]) -> dict[str, Any]:
    metric_data = _named_values(metrics, "metrics")
    supplied_thresholds = _named_values(thresholds, "thresholds")
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"all", "any"}:
        raise ProductionQualityError("Quality gate mode must be all or any")
    threshold_data: dict[str, Any] = dict(defaults)
    threshold_data.update(supplied_thresholds)
    checks: list[dict[str, Any]] = []
    for name in sorted(threshold_data):
        minimum = unit_interval(threshold_data[name], f"Threshold {name}")
        missing = name not in metric_data
        score = 0.0 if missing else unit_interval(metric_data[name], f"Metric {name}")
        checks.append({"metric": name, "score": score, "minimum": minimum, "passed": score >= minimum, "missing": missing})
    passed = True if not checks else (any(item["passed"] for item in checks) if normalized_mode == "any" else all(item["passed"] for item in checks))
    return {
        "schema": "continuity-director/quality-gate@1.0",
        "mode": normalized_mode,
        "passed": passed,
        "checks": checks,
        "failed_metrics": [item["metric"] for item in checks if not item["passed"]],
        "missing_metrics": [item["metric"] for item in checks if item["missing"]],
    }


def normalized_weights(weights: Any, defaults: dict[str, float]) -> dict[str, float]:
    supplied = _named_values(weights, "weights")
    output: dict[str, float] = {name: _finite(value, f"Weight {name}") for name, value in defaults.items()}
    for name, value in supplied.items():
        output[name] = _finite(value, f"Weight {name}")
    for name, value in output.items():
        if value < 0.0 or value > 1_000_000.0:
            raise ProductionQualityError(f"Weight {name} must be between 0 and 1000000")
    return output


def score_metrics(metrics: Any, weights: dict[str, float]) -> float:
    metric_data = _named_values(metrics, "metrics")
    total = sum(weights.values())
    if total <= 0.0:
        return 0.0
    weighted = 0.0
    for name, weight in weights.items():
        value = 0.0 if name not in metric_data else unit_interval(metric_data[name], f"Metric {name}")
        weighted += value * weight
    return weighted / total


def rank_take_records(takes: Any, weights: Any, defaults: dict[str, float]) -> list[dict[str, Any]]:
    take_data = _canonical(takes)
    if not isinstance(take_data, list):
        raise ProductionQualityError("takes must be a list")
    if len(take_data) > 100000:
        raise ProductionQualityError("takes exceeds the 100000 item limit")
    weight_data = normalized_weights(weights, defaults)
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(take_data, start=1):
        if not isinstance(raw, dict):
            raise ProductionQualityError(f"Take {index} must be an object")
        item = copy.deepcopy(raw)
        take_id = _id(item.get("take_id") or item.get("id"), f"Take {index} id", f"take-{index:03d}")
        if take_id in seen:
            raise ProductionQualityError(f"Duplicate take id: {take_id}")
        seen.add(take_id)
        metric_data = item.get("metrics", {})
        if not isinstance(metric_data, dict):
            raise ProductionQualityError(f"Take {take_id} metrics must be an object")
        item["take_id"] = take_id
        item["score"] = round(score_metrics(metric_data, weight_data), 6)
        item["source_index"] = index
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item["take_id"], item["source_index"]))
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
        item.pop("source_index", None)
    return ranked
