from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

PACKAGE_VERSION = "0.7.0"
SCHEMA_VERSION = "1.6"
SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6")
MAX_SEED = 2**63 - 1
MAX_PROMPT_CHARS = 12000
ASPECT_RATIO_RE = re.compile(r"^(?P<w>[1-9]\d{0,3}):(?P<h>[1-9]\d{0,3})$")

DEFAULT_NEGATIVE = (
    "identity drift, different person, face change, hairstyle change, age change, "
    "body proportion change, wardrobe change, accessory change, prop duplication, "
    "missing prop, extra fingers, malformed hands, deformed limbs, inconsistent lighting, "
    "wrong screen direction, temporal flicker, frame-to-frame instability, text, watermark"
)

CAMERA_SHOTS = (
    "extreme wide shot",
    "wide shot",
    "medium wide shot",
    "medium shot",
    "medium close-up",
    "close-up",
    "extreme close-up",
    "over-the-shoulder shot",
    "point-of-view shot",
)

CAMERA_MOVES = (
    "locked camera",
    "slow dolly in",
    "slow dolly out",
    "pan left",
    "pan right",
    "tilt up",
    "tilt down",
    "tracking shot",
    "handheld follow",
    "orbit clockwise",
    "orbit counterclockwise",
)

PROVIDERS = ("generic", "comfyui", "kling", "runway", "veo", "wan", "hunyuan", "ltxv")
PROVIDER_CAPABILITIES = {
    "generic": {"transport": "portable", "seed_mode": "hint", "reference_modes": ["identity", "first_frame", "last_frame"]},
    "comfyui": {"transport": "local_workflow", "seed_mode": "deterministic", "reference_modes": ["identity", "face", "wardrobe", "pose", "style", "environment", "first_frame", "last_frame"]},
    "kling": {"transport": "external_service", "seed_mode": "adapter_hint", "reference_modes": ["identity", "first_frame", "last_frame"]},
    "runway": {"transport": "external_service", "seed_mode": "adapter_hint", "reference_modes": ["identity", "first_frame"]},
    "veo": {"transport": "external_service", "seed_mode": "adapter_hint", "reference_modes": ["identity", "environment", "first_frame", "last_frame"]},
    "wan": {"transport": "comfyui_model", "seed_mode": "deterministic", "reference_modes": ["identity", "first_frame"]},
    "hunyuan": {"transport": "comfyui_model", "seed_mode": "deterministic", "reference_modes": ["identity", "first_frame"]},
    "ltxv": {"transport": "comfyui_model", "seed_mode": "deterministic", "reference_modes": ["identity", "first_frame", "last_frame"]},
}



class ContinuityValidationError(ValueError):
    """Raised when a continuity object fails structural validation."""


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = _clean(item)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def normalize_aspect_ratio(value: Any) -> str:
    ratio = _clean(value) or "9:16"
    match = ASPECT_RATIO_RE.fullmatch(ratio)
    if not match:
        raise ContinuityValidationError("aspect_ratio 必须使用 W:H 格式，例如 9:16")
    width, height = int(match.group("w")), int(match.group("h"))
    if width / height < 0.1 or width / height > 10:
        raise ContinuityValidationError("aspect_ratio 比例超出合理范围")
    return f"{width}:{height}"


def normalize_seed(value: Any) -> int:
    try:
        seed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContinuityValidationError("master_seed 必须是整数") from exc
    if seed < 0:
        raise ContinuityValidationError("master_seed 不能为负数")
    return seed & MAX_SEED


def validate_url(value: Any, field_name: str = "url") -> str:
    url = _clean(value)
    if not url:
        return ""
    if not re.match(r"^https?://[^\s]+$", url, flags=re.IGNORECASE):
        raise ContinuityValidationError(f"{field_name} 必须是 http/https 地址")
    return url


def normalize_reference_images(value: Any = None, fallback_url: str = "") -> list[dict[str, Any]]:
    raw: Any = value
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = _split_csv(raw)
    if raw in (None, "", []):
        raw = []
    if not isinstance(raw, list):
        raise ContinuityValidationError("reference_images 必须是数组、JSON 数组或逗号分隔字符串")
    if fallback_url:
        raw = [{"source": fallback_url, "role": "identity", "weight": 1.0}, *raw]

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if isinstance(item, str):
            item = {"source": item, "role": "identity", "weight": 1.0}
        if not isinstance(item, dict):
            raise ContinuityValidationError("reference_images 中每项必须是字符串或对象")
        source = _clean(item.get("source") or item.get("url") or item.get("path"))
        if not source:
            continue
        if re.match(r"^https?://", source, flags=re.IGNORECASE):
            source = validate_url(source, "reference_images.source")
        elif Path(source).is_absolute() or ".." in Path(source).parts:
            raise ContinuityValidationError("本地参考图必须使用安全的相对路径，不能包含 .. 或绝对路径")
        role = _clean(item.get("role")) or "identity"
        if role not in {"identity", "face", "wardrobe", "pose", "style", "environment", "first_frame", "last_frame"}:
            raise ContinuityValidationError(f"不支持的参考图 role：{role}")
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError) as exc:
            raise ContinuityValidationError("reference_images.weight 必须是数字") from exc
        if weight < 0 or weight > 2:
            raise ContinuityValidationError("reference_images.weight 必须在 0 到 2 之间")
        key = (source.casefold(), role)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "reference_id": f"ref-{stable_seed(0, source, role):016x}",
            "source": source,
            "role": role,
            "weight": round(weight, 3),
        })
    return normalized


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _split_csv(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,，;；\n]+", value)
    else:
        parts = list(value)
    return _dedupe(item for item in (_clean(part) for part in parts) if item)


def _join_unique_terms(*values: Any) -> str:
    terms: list[str] = []
    for value in values:
        terms.extend(_split_csv(value))
    return ", ".join(_dedupe(terms))


def compile_prompt_sections(sections: Iterable[str], max_chars: int = MAX_PROMPT_CHARS) -> tuple[str, list[str], dict[str, int]]:
    normalized: list[str] = []
    seen: set[str] = set()
    for section in sections:
        line = _clean(section)
        if not line:
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(line)
    prompt = "\n".join(normalized)
    warnings: list[str] = []
    original_chars = len(prompt)
    if len(prompt) > max_chars:
        prompt = prompt[: max_chars - 1].rstrip(" ,;\n") + "…"
        warnings.append(f"正向提示词超过 {max_chars} 字符，已安全截断")
    stats = {
        "sections": len(normalized),
        "characters": len(prompt),
        "original_characters": original_chars,
        "estimated_tokens": max(1, (len(prompt) + 3) // 4),
    }
    return prompt, warnings, stats


def _json_object(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 不能为空")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} 不是有效 JSON：{exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} 必须是 JSON 对象")
    return parsed


def to_json(data: dict[str, Any], pretty: bool = True) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2 if pretty else None, sort_keys=False)


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContinuityValidationError(f"{field_name} 必须是对象")
    return value


def validate_object(obj: dict[str, Any] | str, expected_type: str | None = None) -> dict[str, Any]:
    data = _json_object(obj, expected_type or "object") if isinstance(obj, str) else deepcopy(obj)
    _require_mapping(data, expected_type or "object")
    schema_version = _clean(data.get("schema_version"))
    if schema_version and schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ContinuityValidationError(f"不支持的 schema_version：{schema_version}")
    if schema_version and schema_version != SCHEMA_VERSION:
        data = migrate_object(data)
    if expected_type and data.get("type") != expected_type:
        raise ContinuityValidationError(f"对象类型应为 {expected_type}，实际为 {data.get('type')!r}")
    return data


def migrate_object(obj: dict[str, Any] | str) -> dict[str, Any]:
    data = _json_object(obj, "object") if isinstance(obj, str) else deepcopy(obj)
    source_version = _clean(data.get("schema_version")) or "1.0"
    if source_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ContinuityValidationError(f"无法迁移 schema_version：{source_version}")
    if source_version == SCHEMA_VERSION:
        return data

    object_type = data.get("type")
    if object_type == "shot_manifest":
        data.setdefault("warnings", [])
        data.setdefault("previous_shot_id", None)
        data.setdefault("continuity_state", {})
        data["continuity_state"].setdefault("custom", {})
        data.setdefault("lineage", {})
        data["lineage"].setdefault("parent_fingerprint", None)
        data["lineage"].setdefault("sequence_index", 1)
        data["lineage"].setdefault("branch_id", None)
        data["lineage"].setdefault("branch_root_fingerprint", None)
        data["lineage"].setdefault("branch_index", None)
        data.setdefault("take", None)
    elif object_type == "character_lock":
        data.setdefault("reference_images", [])
    elif object_type == "sequence_manifest":
        data.setdefault("warnings", [])
        data.setdefault("branch", None)
    data["schema_version"] = SCHEMA_VERSION
    if object_type == "shot_manifest":
        data["fingerprint"] = manifest_fingerprint(data)
    return data


def validate_linkage(project: dict[str, Any], character: dict[str, Any] | None = None, scene: dict[str, Any] | None = None, previous: dict[str, Any] | None = None) -> None:
    project_id = project.get("project_id")
    if not project_id:
        raise ContinuityValidationError("project 缺少 project_id")
    if character and character.get("project_id") != project_id:
        raise ContinuityValidationError("character_lock 不属于当前 project_lock")
    if scene:
        if scene.get("project_id") != project_id:
            raise ContinuityValidationError("scene_lock 不属于当前 project_lock")
        if character and scene.get("character_id") != character.get("character_id"):
            raise ContinuityValidationError("scene_lock 与 character_lock 不匹配")
    if previous:
        previous_project_id = previous.get("project", {}).get("project_id")
        previous_character_id = previous.get("character", {}).get("character_id")
        if previous_project_id and previous_project_id != project_id:
            raise ContinuityValidationError("previous_shot 来自其他项目")
        if character and previous_character_id and previous_character_id != character.get("character_id"):
            raise ContinuityValidationError("previous_shot 来自其他角色")




def stable_seed(master_seed: int, *parts: Any) -> int:
    material = "|".join([str(int(master_seed)), *(_clean(part) for part in parts)])
    digest = hashlib.blake2b(material.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & MAX_SEED


def slugify(value: str, fallback: str = "continuity") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", _clean(value)).strip("-._")
    return cleaned[:80] or fallback


def build_project(
    project_name: str,
    master_seed: int,
    aspect_ratio: str,
    fps: int,
    visual_style: str,
    color_palette: str,
    lighting_rule: str,
    global_negative: str = "",
) -> dict[str, Any]:
    name = _clean(project_name)
    if not name:
        raise ValueError("project_name 不能为空")
    if fps < 1 or fps > 120:
        raise ContinuityValidationError("fps 必须在 1 到 120 之间")
    seed = normalize_seed(master_seed)
    ratio = normalize_aspect_ratio(aspect_ratio)

    negative = _join_unique_terms(DEFAULT_NEGATIVE, global_negative)
    project_id = f"project-{stable_seed(seed, name):016x}"

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "project_lock",
        "project_id": project_id,
        "project_name": name,
        "master_seed": seed,
        "aspect_ratio": ratio,
        "fps": int(fps),
        "locks": {
            "visual_style": _clean(visual_style),
            "color_palette": _clean(color_palette),
            "lighting_rule": _clean(lighting_rule),
        },
        "global_negative": negative,
    }


def build_character(
    project: dict[str, Any] | str,
    character_id: str,
    display_name: str,
    identity_description: str,
    face_features: str,
    hair: str,
    body_features: str,
    default_wardrobe: str,
    signature_props: str = "",
    immutable_rules: str = "",
    reference_image_url: str = "",
    protected_state_fields: str | Iterable[str] = "wardrobe, props",
    reference_images: Any = None,
) -> dict[str, Any]:
    project_obj = validate_object(project, "project_lock")
    cid = slugify(character_id or display_name, "character")
    if not _clean(identity_description):
        raise ValueError("identity_description 不能为空")

    locked = {
        "identity_description": _clean(identity_description),
        "face_features": _clean(face_features),
        "hair": _clean(hair),
        "body_features": _clean(body_features),
        "default_wardrobe": _clean(default_wardrobe),
        "signature_props": _split_csv(signature_props),
        "immutable_rules": _split_csv(immutable_rules),
        "protected_state_fields": _split_csv(protected_state_fields),
    }
    anchor_parts = [
        f"CHARACTER_ID[{cid}]",
        f"same person as all previous shots",
        locked["identity_description"],
        f"fixed facial structure: {locked['face_features']}" if locked["face_features"] else "",
        f"fixed hair: {locked['hair']}" if locked["hair"] else "",
        f"fixed body proportions: {locked['body_features']}" if locked["body_features"] else "",
        f"wardrobe lock: {locked['default_wardrobe']}" if locked["default_wardrobe"] else "",
        f"signature props: {', '.join(locked['signature_props'])}" if locked["signature_props"] else "",
        f"immutable rules: {', '.join(locked['immutable_rules'])}" if locked["immutable_rules"] else "",
        "preserve identity, clothing construction, materials and proportions exactly",
    ]
    identity_anchor = ", ".join(part for part in anchor_parts if part)
    primary_reference = validate_url(reference_image_url, "reference_image_url")
    refs = normalize_reference_images(reference_images, primary_reference)

    return {
        "schema_version": SCHEMA_VERSION,
        "type": "character_lock",
        "project_id": project_obj["project_id"],
        "character_id": cid,
        "display_name": _clean(display_name) or cid,
        "seed": stable_seed(project_obj["master_seed"], project_obj["project_id"], cid),
        "locked": locked,
        "identity_anchor": identity_anchor,
        "reference_image_url": primary_reference,
        "reference_images": refs,
    }


def build_scene(
    project: dict[str, Any] | str,
    character: dict[str, Any] | str,
    scene_id: str,
    location: str,
    time_of_day: str,
    weather: str,
    lighting: str,
    environment_details: str,
    screen_direction: str = "",
    persistent_objects: str = "",
) -> dict[str, Any]:
    project_obj = validate_object(project, "project_lock")
    character_obj = validate_object(character, "character_lock")
    validate_linkage(project_obj, character_obj)
    sid = slugify(scene_id, "scene")
    return {
        "schema_version": SCHEMA_VERSION,
        "type": "scene_lock",
        "project_id": project_obj["project_id"],
        "character_id": character_obj["character_id"],
        "scene_id": sid,
        "seed": stable_seed(project_obj["master_seed"], project_obj["project_id"], sid),
        "locked": {
            "location": _clean(location),
            "time_of_day": _clean(time_of_day),
            "weather": _clean(weather),
            "lighting": _clean(lighting) or project_obj["locks"].get("lighting_rule", ""),
            "environment_details": _clean(environment_details),
            "screen_direction": _clean(screen_direction),
            "persistent_objects": _split_csv(persistent_objects),
        },
    }


def _state_from_previous(previous: dict[str, Any] | None, character: dict[str, Any]) -> dict[str, Any]:
    if previous:
        state = deepcopy(previous.get("continuity_state", {}))
    else:
        state = {}
    state.setdefault("wardrobe", character["locked"].get("default_wardrobe", ""))
    state.setdefault("props", deepcopy(character["locked"].get("signature_props", [])))
    state.setdefault("injuries", [])
    state.setdefault("dirt_and_damage", [])
    state.setdefault("position", "")
    state.setdefault("emotion", "")
    state.setdefault("custom", {})
    return state


def _apply_state_updates(state: dict[str, Any], updates: dict[str, Any], allowed_changes: list[str]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    allowed = {item.lower() for item in allowed_changes}
    for key, value in updates.items():
        if value in (None, "", [], {}):
            continue
        old = state.get(key)
        if old not in (None, "", [], {}) and old != value and key.lower() not in allowed:
            warnings.append(f"状态字段 {key} 发生变化，但未列入 allowed_changes：{old!r} -> {value!r}")
            continue
        state[key] = deepcopy(value)
    return state, warnings


def _change_allowed(key: str, allowed_changes: Iterable[str]) -> bool:
    allowed = {item.casefold() for item in allowed_changes}
    return "*" in allowed or key.casefold() in allowed


def enforce_character_locks(state: dict[str, Any], character: dict[str, Any], allowed_changes: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    result = deepcopy(state)
    warnings: list[str] = []
    locked = character.get("locked", {})
    protected = {item.casefold() for item in locked.get("protected_state_fields", ["wardrobe", "props"])}
    unlocks = {item.split(":", 1)[1].casefold() for item in allowed_changes if _clean(item).casefold().startswith("unlock:")}

    if "wardrobe" in protected and "wardrobe" not in unlocks:
        expected = locked.get("default_wardrobe", "")
        if expected and result.get("wardrobe") != expected:
            warnings.append("wardrobe 属于角色硬锁字段，已恢复默认服装；如需剧情换装，请在 allowed_changes 中加入 unlock:wardrobe")
            result["wardrobe"] = expected

    if "props" in protected and "props" not in unlocks:
        expected_props = _dedupe(locked.get("signature_props", []))
        current_props = _dedupe(result.get("props", []))
        missing = [item for item in expected_props if item.casefold() not in {p.casefold() for p in current_props}]
        if missing:
            warnings.append(f"props 属于角色硬锁字段，已补回标志性道具：{', '.join(missing)}")
            result["props"] = _dedupe([*current_props, *missing])
    return result, warnings


def apply_state_patch(state: dict[str, Any], patch: dict[str, Any], allowed_changes: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    result = deepcopy(state)
    warnings: list[str] = []
    if not patch:
        return result, warnings
    unknown = set(patch) - {"set", "clear", "add", "remove"}
    if unknown:
        raise ContinuityValidationError(f"state_patch_json 含未知操作：{', '.join(sorted(unknown))}")

    set_values = patch.get("set", {})
    if set_values and not isinstance(set_values, dict):
        raise ContinuityValidationError("state_patch_json.set 必须是对象")
    for key, value in set_values.items():
        old = result.get(key)
        if old != value and old not in (None, "", [], {}) and not _change_allowed(key, allowed_changes):
            warnings.append(f"状态字段 {key} 的 set 操作未获允许：{old!r} -> {value!r}")
            continue
        result[key] = deepcopy(value)

    clear_fields = patch.get("clear", [])
    if isinstance(clear_fields, str):
        clear_fields = _split_csv(clear_fields)
    if not isinstance(clear_fields, list):
        raise ContinuityValidationError("state_patch_json.clear 必须是数组或逗号分隔字符串")
    for key in clear_fields:
        key = _clean(key)
        if not key:
            continue
        if not _change_allowed(key, allowed_changes):
            warnings.append(f"状态字段 {key} 的 clear 操作未获允许")
            continue
        current = result.get(key)
        result[key] = [] if isinstance(current, list) else {} if isinstance(current, dict) else ""

    for operation in ("add", "remove"):
        mapping = patch.get(operation, {})
        if mapping and not isinstance(mapping, dict):
            raise ContinuityValidationError(f"state_patch_json.{operation} 必须是对象")
        for key, values in mapping.items():
            if not _change_allowed(key, allowed_changes):
                warnings.append(f"状态字段 {key} 的 {operation} 操作未获允许")
                continue
            current = result.setdefault(key, [])
            if not isinstance(current, list):
                raise ContinuityValidationError(f"状态字段 {key} 不是列表，不能执行 {operation}")
            values_list = _split_csv(values if isinstance(values, (str, list, tuple, set)) else [values])
            if operation == "add":
                result[key] = _dedupe([*current, *values_list])
            else:
                remove_keys = {item.casefold() for item in values_list}
                result[key] = [item for item in current if _clean(item).casefold() not in remove_keys]
    return result, warnings


def build_transition(previous: dict[str, Any] | None, transition_cfg: dict[str, Any], allowed_changes: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    previous_transition = previous.get("transition", {}) if previous else {}
    inherited_entry = previous_transition.get("exit_frame", "")
    transition = {
        "entry_frame": _clean(transition_cfg.get("entry_frame")) or inherited_entry,
        "exit_frame": _clean(transition_cfg.get("exit_frame")),
        "screen_position": _clean(transition_cfg.get("screen_position")),
        "gaze_direction": _clean(transition_cfg.get("gaze_direction")),
        "movement_direction": _clean(transition_cfg.get("movement_direction")),
        "camera_axis": _clean(transition_cfg.get("camera_axis")),
        "cut_type": _clean(transition_cfg.get("cut_type")) or "continuity cut",
    }
    warnings: list[str] = []
    explicit_entry = _clean(transition_cfg.get("entry_frame"))
    if inherited_entry and explicit_entry and inherited_entry != explicit_entry and not _change_allowed("transition", allowed_changes):
        warnings.append("当前镜头 entry_frame 与上一镜 exit_frame 不一致；已保留显式值，但建议检查转场")
    previous_direction = _clean(previous_transition.get("movement_direction"))
    current_direction = transition["movement_direction"]
    if previous_direction and current_direction and previous_direction != current_direction and not _change_allowed("movement_direction", allowed_changes):
        warnings.append(f"运动方向发生变化：{previous_direction} -> {current_direction}")
    return transition, warnings


def build_shot(
    project: dict[str, Any] | str,
    character: dict[str, Any] | str,
    scene: dict[str, Any] | str,
    shot_id: str,
    duration_seconds: float,
    action: str,
    emotion: str,
    dialogue: str,
    camera_shot: str,
    camera_move: str,
    lens: str,
    composition: str,
    motion_rules: str,
    previous_shot: dict[str, Any] | str | None = None,
    allowed_changes: str | Iterable[str] | None = None,
    wardrobe_override: str = "",
    props_override: str = "",
    injuries: str = "",
    dirt_and_damage: str = "",
    position: str = "",
    custom_state_json: str = "",
    state_patch_json: str = "",
    transition_json: str = "",
    sequence_index: int = 0,
    seed_salt: str = "",
) -> dict[str, Any]:
    project_obj = validate_object(project, "project_lock")
    character_obj = validate_object(character, "character_lock")
    scene_obj = validate_object(scene, "scene_lock")
    previous_obj: dict[str, Any] | None = None
    if previous_shot:
        previous_obj = validate_object(previous_shot, "shot_manifest")
    validate_linkage(project_obj, character_obj, scene_obj, previous_obj)

    shot_key = slugify(shot_id, "shot")
    duration = round(float(duration_seconds), 3)
    if duration <= 0 or duration > 120:
        raise ValueError("duration_seconds 必须大于 0 且不超过 120")

    allowed = _split_csv(allowed_changes)
    state = _state_from_previous(previous_obj, character_obj)
    custom_state: dict[str, Any] = {}
    if _clean(custom_state_json):
        custom_state = _json_object(custom_state_json, "custom_state_json")

    updates = {
        "wardrobe": _clean(wardrobe_override),
        "props": _split_csv(props_override),
        "injuries": _split_csv(injuries),
        "dirt_and_damage": _split_csv(dirt_and_damage),
        "position": _clean(position),
        "emotion": _clean(emotion),
        "custom": custom_state,
    }
    state, warnings = _apply_state_updates(state, updates, allowed)
    if _clean(state_patch_json):
        patch = _json_object(state_patch_json, "state_patch_json")
        state, patch_warnings = apply_state_patch(state, patch, allowed)
        warnings.extend(patch_warnings)
    state, lock_warnings = enforce_character_locks(state, character_obj, allowed)
    warnings.extend(lock_warnings)
    transition_cfg = _json_object(transition_json, "transition_json") if _clean(transition_json) else {}
    transition, transition_warnings = build_transition(previous_obj, transition_cfg, allowed)
    warnings.extend(transition_warnings)

    derived_sequence_index = int(sequence_index) if int(sequence_index) > 0 else (int(previous_obj.get("lineage", {}).get("sequence_index", 0)) + 1 if previous_obj else 1)
    seed_parts = [project_obj["project_id"], character_obj["character_id"], scene_obj["scene_id"], shot_key]
    if _clean(seed_salt):
        seed_parts.append(_clean(seed_salt))
    shot_seed = stable_seed(project_obj["master_seed"], *seed_parts)
    scene_lock = scene_obj["locked"]
    project_lock = project_obj["locks"]

    continuity_summary = (
        f"wardrobe={state.get('wardrobe', '')}; props={', '.join(state.get('props', []))}; "
        f"injuries={', '.join(state.get('injuries', []))}; "
        f"dirt_and_damage={', '.join(state.get('dirt_and_damage', []))}; "
        f"position={state.get('position', '')}; emotion={state.get('emotion', '')}"
    )

    prompt_sections = [
        f"[IDENTITY LOCK] {character_obj['identity_anchor']}",
        (
            "[STYLE LOCK] "
            f"{project_lock.get('visual_style', '')}; color palette: {project_lock.get('color_palette', '')}; "
            f"lighting rule: {project_lock.get('lighting_rule', '')}; aspect ratio {project_obj['aspect_ratio']}"
        ),
        (
            "[SCENE LOCK] "
            f"location: {scene_lock.get('location', '')}; time: {scene_lock.get('time_of_day', '')}; "
            f"weather: {scene_lock.get('weather', '')}; lighting: {scene_lock.get('lighting', '')}; "
            f"environment: {scene_lock.get('environment_details', '')}; "
            f"screen direction: {scene_lock.get('screen_direction', '')}; "
            f"persistent objects: {', '.join(scene_lock.get('persistent_objects', []))}"
        ),
        f"[CONTINUITY STATE] {continuity_summary}",
        f"[ACTION] {_clean(action)}",
        f"[PERFORMANCE] emotion: {_clean(emotion)}; dialogue: {_clean(dialogue)}",
        (
            "[CAMERA] "
            f"{_clean(camera_shot)}, {_clean(camera_move)}, lens {_clean(lens)}, "
            f"composition: {_clean(composition)}"
        ),
        f"[MOTION] {_clean(motion_rules)}",
        (
            "[TRANSITION] "
            f"entry frame: {transition.get('entry_frame', '')}; exit frame: {transition.get('exit_frame', '')}; "
            f"screen position: {transition.get('screen_position', '')}; gaze: {transition.get('gaze_direction', '')}; "
            f"movement: {transition.get('movement_direction', '')}; camera axis: {transition.get('camera_axis', '')}; "
            f"cut: {transition.get('cut_type', '')}"
        ),
        (
            "[HARD CONSTRAINT] Keep the exact same identity, face geometry, hairstyle, body proportions, "
            "wardrobe construction, materials, accessories, prop count, environment layout, lighting direction "
            "and screen direction unless an allowed change is explicitly listed."
        ),
    ]
    positive_prompt, prompt_warnings, prompt_stats = compile_prompt_sections(prompt_sections)
    warnings.extend(prompt_warnings)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "type": "shot_manifest",
        "project": {
            "project_id": project_obj["project_id"],
            "project_name": project_obj["project_name"],
            "aspect_ratio": project_obj["aspect_ratio"],
            "fps": project_obj["fps"],
            "locks": deepcopy(project_lock),
        },
        "character": {
            "character_id": character_obj["character_id"],
            "display_name": character_obj["display_name"],
            "locked": deepcopy(character_obj["locked"]),
            "identity_anchor": character_obj["identity_anchor"],
            "reference_image_url": character_obj.get("reference_image_url", ""),
            "reference_images": deepcopy(character_obj.get("reference_images", [])),
        },
        "scene": deepcopy(scene_obj),
        "shot": {
            "shot_id": shot_key,
            "duration_seconds": duration,
            "action": _clean(action),
            "emotion": _clean(emotion),
            "dialogue": _clean(dialogue),
            "camera_shot": _clean(camera_shot),
            "camera_move": _clean(camera_move),
            "lens": _clean(lens),
            "composition": _clean(composition),
            "motion_rules": _clean(motion_rules),
            "allowed_changes": allowed,
        },
        "seed": shot_seed,
        "seed_salt": _clean(seed_salt),
        "lineage": {
            "parent_fingerprint": previous_obj.get("fingerprint") if previous_obj else None,
            "sequence_index": derived_sequence_index,
        },
        "transition": transition,
        "continuity_state": state,
        "positive_prompt": positive_prompt,
        "negative_prompt": project_obj["global_negative"],
        "prompt_stats": prompt_stats,
        "warnings": warnings,
        "previous_shot_id": previous_obj.get("shot", {}).get("shot_id") if previous_obj else None,
    }
    manifest["fingerprint"] = manifest_fingerprint(manifest)
    return manifest



def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def build_from_brief(brief: dict[str, Any] | str, previous_shot: dict[str, Any] | str | None = None) -> dict[str, Any]:
    obj = _json_object(brief, "brief") if isinstance(brief, str) else deepcopy(brief)
    project_cfg = obj.get("project", {})
    character_cfg = obj.get("character", {})
    scene_cfg = obj.get("scene", {})
    shot_cfg = obj.get("shot", {})
    if not all(isinstance(item, dict) for item in (project_cfg, character_cfg, scene_cfg, shot_cfg)):
        raise ValueError("brief 的 project、character、scene、shot 必须都是 JSON 对象")

    project = build_project(
        project_cfg.get("project_name", "AI Short Film"),
        project_cfg.get("master_seed", 20260619),
        project_cfg.get("aspect_ratio", "9:16"),
        project_cfg.get("fps", 24),
        project_cfg.get("visual_style", "cinematic realistic photography, natural texture"),
        project_cfg.get("color_palette", "neutral cinematic palette"),
        project_cfg.get("lighting_rule", "stable physically plausible lighting"),
        project_cfg.get("global_negative", ""),
    )
    character = build_character(
        project,
        character_cfg.get("character_id", "hero-01"),
        character_cfg.get("display_name", "Hero"),
        character_cfg.get("identity_description", "recognizable natural human character"),
        character_cfg.get("face_features", ""),
        character_cfg.get("hair", ""),
        character_cfg.get("body_features", ""),
        character_cfg.get("default_wardrobe", ""),
        character_cfg.get("signature_props", ""),
        character_cfg.get("immutable_rules", ""),
        character_cfg.get("reference_image_url", ""),
        character_cfg.get("protected_state_fields", "wardrobe, props"),
        character_cfg.get("reference_images"),
    )
    scene = build_scene(
        project,
        character,
        scene_cfg.get("scene_id", "scene-01"),
        scene_cfg.get("location", ""),
        scene_cfg.get("time_of_day", ""),
        scene_cfg.get("weather", ""),
        scene_cfg.get("lighting", ""),
        scene_cfg.get("environment_details", ""),
        scene_cfg.get("screen_direction", ""),
        scene_cfg.get("persistent_objects", ""),
    )
    manifest = build_shot(
        project,
        character,
        scene,
        shot_cfg.get("shot_id", "shot-001"),
        shot_cfg.get("duration_seconds", 5.0),
        shot_cfg.get("action", ""),
        shot_cfg.get("emotion", ""),
        shot_cfg.get("dialogue", ""),
        shot_cfg.get("camera_shot", "medium shot"),
        shot_cfg.get("camera_move", "locked camera"),
        shot_cfg.get("lens", "35mm"),
        shot_cfg.get("composition", ""),
        shot_cfg.get("motion_rules", "natural physically plausible motion"),
        previous_shot,
        shot_cfg.get("allowed_changes", "emotion, position"),
        shot_cfg.get("wardrobe_override", ""),
        shot_cfg.get("props_override", ""),
        shot_cfg.get("injuries", ""),
        shot_cfg.get("dirt_and_damage", ""),
        shot_cfg.get("position", ""),
        to_json(shot_cfg.get("custom_state", {}), pretty=False) if shot_cfg.get("custom_state") else "",
        to_json(shot_cfg.get("state_patch", {}), pretty=False) if shot_cfg.get("state_patch") else "",
        to_json(shot_cfg.get("transition", {}), pretty=False) if shot_cfg.get("transition") else "",
        shot_cfg.get("sequence_index", 0),
        shot_cfg.get("seed_salt", ""),
    )
    return {"project": project, "character": character, "scene": scene, "manifest": manifest}

def build_sequence_from_brief(brief: dict[str, Any] | str, previous_shot: dict[str, Any] | str | None = None) -> dict[str, Any]:
    obj = _json_object(brief, "brief") if isinstance(brief, str) else deepcopy(brief)
    shots = obj.get("shots")
    if not isinstance(shots, list) or not shots:
        single = obj.get("shot")
        if isinstance(single, dict):
            shots = [single]
        else:
            raise ContinuityValidationError("批量 brief 必须包含非空 shots 数组")

    current_previous = validate_object(previous_shot, "shot_manifest") if previous_shot else None
    manifests: list[dict[str, Any]] = []
    base_scene = deepcopy(obj.get("scene", {}))
    for index, shot_cfg in enumerate(shots, start=1):
        if not isinstance(shot_cfg, dict):
            raise ContinuityValidationError(f"shots[{index - 1}] 必须是对象")
        item_brief = {
            "project": deepcopy(obj.get("project", {})),
            "character": deepcopy(obj.get("character", {})),
            "scene": deep_merge(base_scene, shot_cfg.get("scene_override", {})),
            "shot": deepcopy(shot_cfg),
        }
        item_brief["shot"].setdefault("sequence_index", index)
        item_brief["shot"].setdefault("shot_id", f"shot-{index:03d}")
        result = build_from_brief(item_brief, current_previous)
        current_previous = result["manifest"]
        manifests.append(current_previous)

    sequence_payload = {
        "schema_version": SCHEMA_VERSION,
        "type": "sequence_manifest",
        "project_id": manifests[0]["project"]["project_id"],
        "character_id": manifests[0]["character"]["character_id"],
        "sequence_id": slugify(obj.get("sequence_id", "sequence-01"), "sequence-01"),
        "shot_count": len(manifests),
        "total_duration_seconds": round(sum(item["shot"]["duration_seconds"] for item in manifests), 3),
        "shots": manifests,
        "warnings": [warning for item in manifests for warning in item.get("warnings", [])],
    }
    sequence_payload["fingerprint"] = manifest_fingerprint(sequence_payload)
    return sequence_payload


def manifest_fingerprint(manifest: dict[str, Any] | str) -> str:
    obj = _json_object(manifest, "manifest") if isinstance(manifest, str) else deepcopy(manifest)
    obj.pop("fingerprint", None)
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def audit_manifests(previous: dict[str, Any] | str, current: dict[str, Any] | str) -> dict[str, Any]:
    prev = _json_object(previous, "previous") if isinstance(previous, str) else deepcopy(previous)
    curr = _json_object(current, "current") if isinstance(current, str) else deepcopy(current)
    issues: list[dict[str, Any]] = []
    score = 100

    def compare(path: str, old: Any, new: Any, penalty: int, allowed: set[str] | None = None) -> None:
        nonlocal score
        if old == new:
            return
        leaf = path.rsplit(".", 1)[-1].lower()
        if allowed and leaf in allowed:
            issues.append({"severity": "info", "field": path, "message": "变化已被允许", "before": old, "after": new})
            return
        score = max(0, score - penalty)
        issues.append({"severity": "error" if penalty >= 20 else "warning", "field": path, "message": "检测到未授权连续性变化", "before": old, "after": new})

    allowed = {item.lower() for item in curr.get("shot", {}).get("allowed_changes", [])}
    compare("character.character_id", prev.get("character", {}).get("character_id"), curr.get("character", {}).get("character_id"), 50)
    compare("character.locked.identity_description", prev.get("character", {}).get("locked", {}).get("identity_description"), curr.get("character", {}).get("locked", {}).get("identity_description"), 35)
    compare("character.locked.face_features", prev.get("character", {}).get("locked", {}).get("face_features"), curr.get("character", {}).get("locked", {}).get("face_features"), 30)
    compare("character.locked.hair", prev.get("character", {}).get("locked", {}).get("hair"), curr.get("character", {}).get("locked", {}).get("hair"), 25)
    compare("project.locks.visual_style", prev.get("project", {}).get("locks", {}).get("visual_style"), curr.get("project", {}).get("locks", {}).get("visual_style"), 20)
    compare("project.aspect_ratio", prev.get("project", {}).get("aspect_ratio"), curr.get("project", {}).get("aspect_ratio"), 15)
    compare("scene.locked.screen_direction", prev.get("scene", {}).get("locked", {}).get("screen_direction"), curr.get("scene", {}).get("locked", {}).get("screen_direction"), 8, allowed)
    compare("transition.camera_axis", prev.get("transition", {}).get("camera_axis"), curr.get("transition", {}).get("camera_axis"), 8, allowed)
    compare("transition.movement_direction", prev.get("transition", {}).get("movement_direction"), curr.get("transition", {}).get("movement_direction"), 6, allowed)
    previous_exit = prev.get("transition", {}).get("exit_frame")
    current_entry = curr.get("transition", {}).get("entry_frame")
    if previous_exit and current_entry:
        compare("transition.entry_frame", previous_exit, current_entry, 10, allowed)
    for key, penalty in (("wardrobe", 20), ("props", 12), ("injuries", 10), ("dirt_and_damage", 8), ("position", 5)):
        compare(f"continuity_state.{key}", prev.get("continuity_state", {}).get(key), curr.get("continuity_state", {}).get(key), penalty, allowed)

    return {
        "score": score,
        "passed": score >= 80 and not any(issue["severity"] == "error" for issue in issues),
        "issues": issues,
        "previous_fingerprint": prev.get("fingerprint") or manifest_fingerprint(prev),
        "current_fingerprint": curr.get("fingerprint") or manifest_fingerprint(curr),
    }


def audit_sequence(sequence: dict[str, Any] | str) -> dict[str, Any]:
    obj = _json_object(sequence, "sequence") if isinstance(sequence, str) else deepcopy(sequence)
    if obj.get("type") != "sequence_manifest":
        raise ContinuityValidationError("sequence 必须是 sequence_manifest")
    shots = obj.get("shots", [])
    if not isinstance(shots, list) or not shots:
        raise ContinuityValidationError("sequence_manifest.shots 不能为空")

    pair_reports: list[dict[str, Any]] = []
    structural_issues: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, shot in enumerate(shots):
        shot_id = shot.get("shot", {}).get("shot_id")
        if shot_id in seen_ids:
            structural_issues.append({"severity": "error", "field": f"shots[{index}].shot_id", "message": "镜头 ID 重复", "value": shot_id})
        seen_ids.add(shot_id)
        expected_index = index + 1
        actual_index = shot.get("lineage", {}).get("sequence_index")
        if actual_index != expected_index:
            structural_issues.append({"severity": "warning", "field": f"shots[{index}].lineage.sequence_index", "message": "顺序编号不连续", "expected": expected_index, "actual": actual_index})
        if index > 0:
            expected_parent = shots[index - 1].get("fingerprint") or manifest_fingerprint(shots[index - 1])
            actual_parent = shot.get("lineage", {}).get("parent_fingerprint")
            if actual_parent != expected_parent:
                structural_issues.append({"severity": "error", "field": f"shots[{index}].lineage.parent_fingerprint", "message": "父级指纹断链", "expected": expected_parent, "actual": actual_parent})
            report = audit_manifests(shots[index - 1], shot)
            report["from_shot_id"] = shots[index - 1].get("shot", {}).get("shot_id")
            report["to_shot_id"] = shot_id
            pair_reports.append(report)

    pair_scores = [report["score"] for report in pair_reports] or [100]
    structural_penalty = sum(20 if item["severity"] == "error" else 5 for item in structural_issues)
    score = max(0, round(sum(pair_scores) / len(pair_scores)) - structural_penalty)
    passed = score >= 80 and not structural_issues and all(report["passed"] for report in pair_reports)
    return {
        "score": score,
        "passed": passed,
        "shot_count": len(shots),
        "minimum_pair_score": min(pair_scores),
        "average_pair_score": round(sum(pair_scores) / len(pair_scores), 2),
        "structural_issues": structural_issues,
        "pair_reports": pair_reports,
        "sequence_fingerprint": obj.get("fingerprint") or manifest_fingerprint(obj),
    }


def provider_payload(
    manifest: dict[str, Any] | str,
    provider: str,
    reference_image_url: str = "",
    provider_settings: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    obj = _json_object(manifest, "manifest") if isinstance(manifest, str) else deepcopy(manifest)
    provider_name = _clean(provider).lower() or "generic"
    if provider_name not in PROVIDERS:
        raise ValueError(f"不支持的 provider：{provider_name}")

    explicit_ref = validate_url(reference_image_url, "reference_image_url") if _clean(reference_image_url) else ""
    manifest_refs = deepcopy(obj.get("character", {}).get("reference_images", []))
    refs = normalize_reference_images(manifest_refs, explicit_ref) if explicit_ref else manifest_refs
    ref = explicit_ref or obj.get("character", {}).get("reference_image_url", "")
    settings = {}
    if provider_settings:
        settings = _json_object(provider_settings, "provider_settings") if isinstance(provider_settings, str) else deepcopy(provider_settings)
    capabilities = deepcopy(PROVIDER_CAPABILITIES[provider_name])
    compatibility_warnings: list[str] = []
    supported_roles = set(capabilities["reference_modes"])
    ignored_roles = sorted({item.get("role", "identity") for item in refs if item.get("role", "identity") not in supported_roles})
    if ignored_roles:
        compatibility_warnings.append(f"当前适配器未声明支持以下参考图角色：{', '.join(ignored_roles)}")
    if not refs:
        compatibility_warnings.append("未提供参考图；跨镜头身份稳定性将主要依赖模型自身能力")
    if capabilities["seed_mode"] == "adapter_hint":
        compatibility_warnings.append("seed 作为可移植提示保留，外部平台是否原生采用该字段取决于其当前接口")
    base = {
        "adapter_schema": "continuity-director-portable-v1",
        "provider": provider_name,
        "capabilities": capabilities,
        "compatibility_warnings": compatibility_warnings,
        "note": "便携字段映射；外部平台的正式 API 字段和模型名应以其当前官方文档为准。",
        "payload": {
            "prompt": obj["positive_prompt"],
            "negative_prompt": obj["negative_prompt"],
            "seed": obj["seed"],
            "duration_seconds": obj["shot"]["duration_seconds"],
            "aspect_ratio": obj["project"]["aspect_ratio"],
            "fps": obj["project"]["fps"],
            "reference_image_url": ref or None,
            "reference_images": refs,
            "provider_settings": settings,
            "continuity_fingerprint": obj.get("fingerprint") or manifest_fingerprint(obj),
        },
    }

    hints = {
        "generic": "将 payload 映射到目标视频模型。优先使用图生视频或参考图模式。",
        "comfyui": "把 prompt、negative_prompt、seed 分别连接到文本编码、负面文本编码和采样器；参考图连接 IP-Adapter/Reference/首帧节点。",
        "kling": "优先使用 Image-to-Video 或 Multi-Image-to-Video；参考图作为角色身份锚点。",
        "runway": "优先使用 Image-to-Video 或 references；固定输入图并复用 continuity_fingerprint。",
        "veo": "优先使用 reference images 或首帧/尾帧引导；连续镜头复用角色参考图。",
        "wan": "在 ComfyUI 中固定 seed，并把角色参考图接到模型支持的图像条件节点。",
        "hunyuan": "使用图像条件工作流，固定 seed、分辨率、帧数和角色锚点。",
        "ltxv": "使用首帧/图像条件工作流，固定 seed 与镜头派生参数。",
    }
    base["usage_hint"] = hints[provider_name]
    return base


def _available_path(path: Path, overwrite: bool) -> Path:
    target = path
    if target.exists() and not overwrite:
        stem, suffix = target.stem, target.suffix
        index = 1
        while target.exists():
            target = target.with_name(f"{stem}-{index}{suffix}")
            index += 1
    return target


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")


def package_sequence(
    path: str | os.PathLike[str],
    sequence: dict[str, Any] | str,
    provider: str = "generic",
    overwrite: bool = False,
) -> Path:
    obj = _json_object(sequence, "sequence") if isinstance(sequence, str) else deepcopy(sequence)
    if obj.get("type") != "sequence_manifest":
        raise ContinuityValidationError("只能打包 sequence_manifest")
    provider_name = _clean(provider).lower() or "generic"
    if provider_name not in PROVIDERS:
        raise ContinuityValidationError(f"不支持的 provider：{provider_name}")

    target = Path(path).expanduser().resolve()
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _available_path(target, overwrite)

    files: dict[str, bytes] = {"sequence.json": _json_bytes(obj)}
    for index, shot in enumerate(obj.get("shots", []), start=1):
        shot_id = slugify(shot.get("shot", {}).get("shot_id", f"shot-{index:03d}"), f"shot-{index:03d}")
        files[f"shots/{index:03d}-{shot_id}.json"] = _json_bytes(shot)
        files[f"providers/{index:03d}-{shot_id}-{provider_name}.json"] = _json_bytes(provider_payload(shot, provider_name))
    checksums = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}
    index_data = {
        "package_schema": "continuity-director-package-v1",
        "package_version": PACKAGE_VERSION,
        "sequence_id": obj.get("sequence_id"),
        "provider": provider_name,
        "shot_count": obj.get("shot_count", len(obj.get("shots", []))),
        "files": sorted(files),
    }
    files["index.json"] = _json_bytes(index_data)
    files["checksums.sha256.json"] = _json_bytes(checksums)

    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, content in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, content)
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target


def atomic_write_json(path: str | os.PathLike[str], data: dict[str, Any], overwrite: bool = False) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _available_path(target, overwrite)

    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target
