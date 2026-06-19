"""Strict storyboard normalization, reference validation, and Take expansion."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .strict_json_core import StrictJSONError, validate_json_value


class StoryboardError(ValueError):
    """Raised when a storyboard cannot be expanded safely."""


_ID_CLEAN_RE = re.compile(r"[^A-Za-z0-9._-]+")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_SEED = 2147483647
_SEED_SPACE = _MAX_SEED + 1


def _canonical(value: Any) -> Any:
    try:
        return validate_json_value(value)
    except StrictJSONError as exc:
        raise StoryboardError(str(exc)) from exc


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_id(value: Any, field: str, fallback: str | None = None) -> str:
    if isinstance(value, (bool, bytes, bytearray, list, tuple, dict, set)):
        raise StoryboardError(f"{field} must be a scalar identifier")
    raw = str(value if value is not None else "").strip()
    if not raw:
        raw = fallback or ""
    clean = _ID_CLEAN_RE.sub("-", raw).strip("-._")
    if not clean:
        raise StoryboardError(f"{field} must not be empty")
    if len(clean) > 128:
        suffix = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:12]
        clean = f"{clean[:115]}-{suffix}"
    return clean


def strict_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise StoryboardError(f"{field} must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise StoryboardError(f"{field} must be an integer without truncation")
        number = int(value)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        number = int(value.strip())
    else:
        raise StoryboardError(f"{field} must be an integer")
    if number < minimum or number > maximum:
        raise StoryboardError(f"{field} must be between {minimum} and {maximum}")
    return number


def finite_duration(value: Any, shot_number: int) -> float:
    if isinstance(value, bool):
        raise StoryboardError(f"Shot {shot_number} duration_seconds must be numeric")
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise StoryboardError(f"Shot {shot_number} duration_seconds must be numeric") from exc
    if not math.isfinite(duration):
        raise StoryboardError(f"Shot {shot_number} duration_seconds must be finite")
    if duration <= 0.0 or duration > 600.0:
        raise StoryboardError(f"Shot {shot_number} duration_seconds must be greater than 0 and at most 600")
    return duration


def id_list(value: Any, field: str, shot_number: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[,;\r\n]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        values = list(value)
    else:
        raise StoryboardError(f"Shot {shot_number} {field} must be a string or list")
    output: list[str] = []
    seen: dict[str, str] = {}
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        item = normalize_id(raw, f"Shot {shot_number} {field}")
        previous = seen.get(item)
        if previous is not None and previous != text:
            raise StoryboardError(f"Shot {shot_number} {field} contains colliding identifiers: {previous} and {text}")
        if item not in seen:
            seen[item] = text
            output.append(item)
    return output


def _verify_manifest(manifest: Any) -> dict[str, Any]:
    if manifest in (None, {}):
        return {}
    data = _canonical(manifest)
    if not isinstance(data, dict):
        raise StoryboardError("Manifest must be an object")
    supplied = str(data.get("hash", "")).strip().lower()
    if supplied:
        body = copy.deepcopy(data)
        body.pop("hash", None)
        expected = _digest(body)
        if not _HASH_RE.fullmatch(supplied) or not hmac.compare_digest(supplied, expected):
            raise StoryboardError("Manifest failed integrity verification")
    if data.get("schema") not in (None, "continuity-director/manifest@1.0"):
        raise StoryboardError("Unsupported manifest schema")
    return data


def _manifest_ids(manifest: dict[str, Any], key: str) -> list[str]:
    values = manifest.get(key, [])
    if not isinstance(values, list):
        raise StoryboardError(f"Manifest {key} must be a list")
    output: list[str] = []
    for index, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            raise StoryboardError(f"Manifest {key} item {index} must be an object")
        output.append(normalize_id(item.get("id"), f"Manifest {key} item {index} id"))
    return output


def _references(value: Any, shot_number: int) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return _canonical(value)
    if isinstance(value, dict):
        return [_canonical(value)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    raise StoryboardError(f"Shot {shot_number} references must be a list, object, or non-empty string")


def _text(value: Any, field: str, shot_number: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise StoryboardError(f"Shot {shot_number} {field} must be a string")
    return value.strip()


def _camera(value: Any, shot_number: int) -> Any:
    if value is None:
        return {}
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _canonical(value)
    raise StoryboardError(f"Shot {shot_number} camera must be a string or object")


def _unique_seed(candidate: int, used: set[int]) -> int:
    seed = candidate % _SEED_SPACE
    for _ in range(_SEED_SPACE):
        if seed not in used:
            used.add(seed)
            return seed
        seed = (seed + 1) % _SEED_SPACE
    raise StoryboardError("No unique seed remains available")


def expand(storyboard: Any, manifest: Any, base_seed: Any, takes_per_shot: Any) -> dict[str, Any]:
    source = _canonical(storyboard)
    if not isinstance(source, (list, dict)):
        raise StoryboardError("Storyboard must be a list or object")
    shots = source.get("shots", []) if isinstance(source, dict) else source
    if not isinstance(shots, list):
        raise StoryboardError("Storyboard shots must be a list")
    if len(shots) > 10000:
        raise StoryboardError("Storyboard exceeds the 10000 shot limit")
    manifest_data = _verify_manifest(manifest)
    scene_ids = _manifest_ids(manifest_data, "scenes") if manifest_data else []
    character_ids = set(_manifest_ids(manifest_data, "characters")) if manifest_data else set()
    take_limit = strict_int(takes_per_shot, "takes_per_shot", 1, 16)
    seed_base = strict_int(base_seed, "base_seed", 0, _MAX_SEED)
    plans: list[dict[str, Any]] = []
    seen_shots: set[str] = set()
    for index, raw in enumerate(shots, start=1):
        item = {"prompt": raw} if isinstance(raw, str) else _canonical(raw)
        if not isinstance(item, dict):
            raise StoryboardError(f"Shot {index} must be an object or string")
        shot_id = normalize_id(item.get("id") or item.get("shot_id"), f"Shot {index} id", f"shot-{index:03d}")
        if shot_id in seen_shots:
            raise StoryboardError(f"Duplicate shot id: {shot_id}")
        seen_shots.add(shot_id)
        requested_scene = item.get("scene_id")
        if requested_scene in (None, ""):
            if len(scene_ids) == 1:
                scene_id = scene_ids[0]
            elif len(scene_ids) > 1:
                raise StoryboardError(f"Shot {index} must specify scene_id because the manifest has multiple scenes")
            else:
                scene_id = "scene-default"
        else:
            scene_id = normalize_id(requested_scene, f"Shot {index} scene_id")
        if scene_ids and scene_id not in scene_ids:
            raise StoryboardError(f"Shot {shot_id} references unknown scene {scene_id}")
        characters = id_list(item.get("character_ids", []), "character_ids", index)
        unknown_characters = sorted(set(characters) - character_ids) if character_ids else []
        if unknown_characters:
            raise StoryboardError(f"Shot {shot_id} references unknown characters: {', '.join(unknown_characters)}")
        dependencies = id_list(item.get("depends_on", []), "depends_on", index)
        if shot_id in dependencies:
            raise StoryboardError(f"Shot {shot_id} cannot depend on itself")
        explicit_seed = item.get("seed")
        seed_start = strict_int(explicit_seed, f"Shot {index} seed", 0, _MAX_SEED) if explicit_seed is not None else (seed_base + (index - 1) * 1000) % _SEED_SPACE
        plans.append({
            "shot_id": shot_id,
            "scene_id": scene_id,
            "character_ids": characters,
            "shot_dependencies": dependencies,
            "prompt": _text(item.get("prompt"), "prompt", index),
            "negative_prompt": _text(item.get("negative_prompt"), "negative_prompt", index),
            "camera": _camera(item.get("camera", {}), index),
            "duration_seconds": finite_duration(item.get("duration_seconds", 3.0), index),
            "references": _references(item.get("references", []), index),
            "seed_start": seed_start,
        })
    known_shots = {item["shot_id"] for item in plans}
    for plan in plans:
        unknown = sorted(set(plan["shot_dependencies"]) - known_shots)
        if unknown:
            raise StoryboardError(f"Shot {plan['shot_id']} has unknown dependencies: {', '.join(unknown)}")
    take_ids = {plan["shot_id"]: [f"{plan['shot_id']}-take-{index:02d}" for index in range(1, take_limit + 1)] for plan in plans}
    entries: list[dict[str, Any]] = []
    used_seeds: set[int] = set()
    for plan in plans:
        dependencies = [take_id for shot_id in plan["shot_dependencies"] for take_id in take_ids[shot_id]]
        for take_index, take_id in enumerate(take_ids[plan["shot_id"]], start=1):
            entries.append({
                "shot_id": plan["shot_id"],
                "take_id": take_id,
                "take_index": take_index,
                "seed": _unique_seed(plan["seed_start"] + take_index - 1, used_seeds),
                "prompt": plan["prompt"],
                "negative_prompt": plan["negative_prompt"],
                "scene_id": plan["scene_id"],
                "character_ids": copy.deepcopy(plan["character_ids"]),
                "camera": copy.deepcopy(plan["camera"]),
                "duration_seconds": plan["duration_seconds"],
                "references": copy.deepcopy(plan["references"]),
                "shot_dependencies": copy.deepcopy(plan["shot_dependencies"]),
                "depends_on": dependencies.copy(),
            })
    chain = {
        "schema": "continuity-director/shot-chain@1.0",
        "manifest_hash": str(manifest_data.get("hash", "")),
        "shot_count": len(plans),
        "take_count": len(entries),
        "takes_per_shot": take_limit,
        "takes": entries,
    }
    chain["hash"] = _digest(chain)
    return chain
