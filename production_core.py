from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from continuity_core import (
    ContinuityValidationError,
    PACKAGE_VERSION,
    PROVIDER_CAPABILITIES,
    PROVIDERS,
    SCHEMA_VERSION,
    build_character,
    build_sequence_from_brief,
    audit_sequence,
    manifest_fingerprint,
    provider_payload,
    slugify,
    stable_seed,
    to_json,
    validate_object,
)


def make_issue(code: str, severity: str, path: str, message: str, **details: Any) -> dict[str, Any]:
    level = str(severity).lower().strip()
    if level not in {"info", "warning", "error"}:
        raise ContinuityValidationError(f"不支持的 issue severity：{severity}")
    item = {"code": str(code).strip(), "severity": level, "path": str(path).strip(), "message": str(message).strip()}
    item.update({key: deepcopy(value) for key, value in details.items()})
    return item


def normalize_cast(project: dict[str, Any] | str, characters: list[dict[str, Any]]) -> dict[str, Any]:
    project_obj = validate_object(project, "project_lock")
    if not isinstance(characters, list) or not characters:
        raise ContinuityValidationError("characters 必须是非空数组")
    locks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, cfg in enumerate(characters):
        if not isinstance(cfg, dict):
            raise ContinuityValidationError(f"characters[{index}] 必须是对象")
        character = build_character(
            project_obj,
            cfg.get("character_id", f"character-{index + 1}"),
            cfg.get("display_name", f"Character {index + 1}"),
            cfg.get("identity_description", "recognizable natural human character"),
            cfg.get("face_features", ""),
            cfg.get("hair", ""),
            cfg.get("body_features", ""),
            cfg.get("default_wardrobe", ""),
            cfg.get("signature_props", ""),
            cfg.get("immutable_rules", ""),
            cfg.get("reference_image_url", ""),
            cfg.get("protected_state_fields", "wardrobe, props"),
            cfg.get("reference_images"),
        )
        cid = character["character_id"]
        if cid in seen:
            raise ContinuityValidationError(f"角色 ID 重复：{cid}")
        seen.add(cid)
        locks.append(character)
    cast = {
        "schema_version": SCHEMA_VERSION,
        "type": "cast_lock",
        "project_id": project_obj["project_id"],
        "character_count": len(locks),
        "characters": locks,
    }
    cast["fingerprint"] = manifest_fingerprint(cast)
    return cast


def cast_character(cast: dict[str, Any] | str, character_id: str) -> dict[str, Any]:
    obj = json.loads(cast) if isinstance(cast, str) else deepcopy(cast)
    if obj.get("type") != "cast_lock":
        raise ContinuityValidationError("cast 必须是 cast_lock")
    wanted = slugify(character_id, "character")
    for item in obj.get("characters", []):
        if item.get("character_id") == wanted:
            return deepcopy(item)
    raise ContinuityValidationError(f"cast 中不存在角色：{wanted}")


def build_scene_topology(scene: dict[str, Any] | str, zones: list[dict[str, Any]], connections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scene_obj = validate_object(scene, "scene_lock")
    if not isinstance(zones, list) or not zones:
        raise ContinuityValidationError("zones 必须是非空数组")
    normalized_zones: list[dict[str, Any]] = []
    zone_ids: set[str] = set()
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict):
            raise ContinuityValidationError(f"zones[{index}] 必须是对象")
        zone_id = slugify(zone.get("zone_id", f"zone-{index + 1}"), f"zone-{index + 1}")
        if zone_id in zone_ids:
            raise ContinuityValidationError(f"zone_id 重复：{zone_id}")
        zone_ids.add(zone_id)
        normalized_zones.append({
            "zone_id": zone_id,
            "description": str(zone.get("description", "")).strip(),
            "anchors": [str(item).strip() for item in zone.get("anchors", []) if str(item).strip()],
        })
    normalized_connections: list[dict[str, Any]] = []
    for index, connection in enumerate(connections or []):
        if not isinstance(connection, dict):
            raise ContinuityValidationError(f"connections[{index}] 必须是对象")
        source = slugify(connection.get("from", ""), "")
        target = slugify(connection.get("to", ""), "")
        if source not in zone_ids or target not in zone_ids:
            raise ContinuityValidationError(f"connections[{index}] 引用了不存在的 zone")
        normalized_connections.append({
            "from": source,
            "to": target,
            "direction": str(connection.get("direction", "")).strip(),
            "transition": str(connection.get("transition", "")).strip(),
        })
    topology = {
        "schema_version": SCHEMA_VERSION,
        "type": "scene_topology",
        "project_id": scene_obj["project_id"],
        "scene_id": scene_obj["scene_id"],
        "zones": normalized_zones,
        "connections": normalized_connections,
    }
    topology["fingerprint"] = manifest_fingerprint(topology)
    return topology


def validate_zone_transition(topology: dict[str, Any] | str, from_zone: str, to_zone: str) -> dict[str, Any]:
    obj = json.loads(topology) if isinstance(topology, str) else deepcopy(topology)
    if obj.get("type") != "scene_topology":
        raise ContinuityValidationError("topology 必须是 scene_topology")
    source = slugify(from_zone, "")
    target = slugify(to_zone, "")
    if source == target:
        return {"allowed": True, "connection": None, "issues": []}
    for connection in obj.get("connections", []):
        if connection.get("from") == source and connection.get("to") == target:
            return {"allowed": True, "connection": deepcopy(connection), "issues": []}
    return {
        "allowed": False,
        "connection": None,
        "issues": [make_issue("ZONE_JUMP", "error", "transition.zone", "镜头位置发生无连接跳跃", before=source, after=target)],
    }


def validate_dialogue_turns(cast: dict[str, Any] | str, turns: list[dict[str, Any]]) -> dict[str, Any]:
    cast_obj = json.loads(cast) if isinstance(cast, str) else deepcopy(cast)
    if cast_obj.get("type") != "cast_lock":
        raise ContinuityValidationError("cast 必须是 cast_lock")
    known = {item.get("character_id") for item in cast_obj.get("characters", [])}
    issues: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    previous_speaker = None
    for index, turn in enumerate(turns or []):
        if not isinstance(turn, dict):
            issues.append(make_issue("DIALOGUE_TURN_TYPE", "error", f"turns[{index}]", "对白轮次必须是对象"))
            continue
        speaker = slugify(turn.get("speaker_id", ""), "")
        text = str(turn.get("text", "")).strip()
        if speaker not in known:
            issues.append(make_issue("UNKNOWN_SPEAKER", "error", f"turns[{index}].speaker_id", "对白说话人不在演员表中", value=speaker))
        if not text:
            issues.append(make_issue("EMPTY_DIALOGUE", "warning", f"turns[{index}].text", "对白文本为空"))
        if previous_speaker == speaker and speaker:
            issues.append(make_issue("REPEATED_SPEAKER", "info", f"turns[{index}].speaker_id", "相邻对白由同一角色连续说出"))
        normalized.append({
            "speaker_id": speaker,
            "text": text,
            "emotion": str(turn.get("emotion", "")).strip(),
            "lip_sync": bool(turn.get("lip_sync", True)),
        })
        previous_speaker = speaker
    return {
        "valid": not any(item["severity"] == "error" for item in issues),
        "turns": normalized,
        "issues": issues,
    }


def build_branch_sequence(
    brief: dict[str, Any] | str,
    parent_shot: dict[str, Any] | str,
    branch_id: str,
) -> dict[str, Any]:
    parent = validate_object(parent_shot, "shot_manifest")
    sequence = build_sequence_from_brief(brief, parent)
    bid = slugify(branch_id, "branch-01")
    root_fingerprint = parent.get("fingerprint") or manifest_fingerprint(parent)
    for index, shot in enumerate(sequence["shots"], start=1):
        shot.setdefault("lineage", {})
        shot["lineage"].update({
            "branch_id": bid,
            "branch_root_fingerprint": root_fingerprint,
            "branch_index": index,
        })
        shot["fingerprint"] = manifest_fingerprint(shot)
        if index + 1 < len(sequence["shots"]):
            sequence["shots"][index]["lineage"]["parent_fingerprint"] = shot["fingerprint"]
    sequence["branch"] = {
        "branch_id": bid,
        "root_shot_id": parent.get("shot", {}).get("shot_id"),
        "root_fingerprint": root_fingerprint,
    }
    sequence["fingerprint"] = manifest_fingerprint(sequence)
    return sequence


def build_take_variants(
    brief: dict[str, Any] | str,
    take_count: int = 3,
    previous_shot: dict[str, Any] | str | None = None,
    strategy: str = "seed_only",
) -> dict[str, Any]:
    obj = json.loads(brief) if isinstance(brief, str) else deepcopy(brief)
    if take_count < 1 or take_count > 32:
        raise ContinuityValidationError("take_count 必须在 1 到 32 之间")
    if strategy not in {"seed_only", "camera_micro_variation"}:
        raise ContinuityValidationError("strategy 仅支持 seed_only 或 camera_micro_variation")
    takes: list[dict[str, Any]] = []
    base_shot = deepcopy(obj.get("shot", {}))
    for index in range(1, take_count + 1):
        take_brief = deepcopy(obj)
        take_shot = deepcopy(base_shot)
        base_salt = str(take_shot.get("seed_salt", "")).strip()
        take_shot["seed_salt"] = f"{base_salt}|take-{index}" if base_salt else f"take-{index}"
        if strategy == "camera_micro_variation":
            composition = str(take_shot.get("composition", "")).strip()
            take_shot["composition"] = f"{composition}; micro variation take {index}".strip("; ")
        take_brief["shot"] = take_shot
        result = build_sequence_from_brief({**take_brief, "shots": [take_shot]}, previous_shot)
        manifest = result["shots"][0]
        manifest["take"] = {"take_index": index, "take_count": take_count, "strategy": strategy}
        manifest["fingerprint"] = manifest_fingerprint(manifest)
        takes.append(manifest)
    group = {
        "schema_version": SCHEMA_VERSION,
        "type": "take_group",
        "take_count": take_count,
        "strategy": strategy,
        "takes": takes,
    }
    group["fingerprint"] = manifest_fingerprint(group)
    return group

PROVIDER_BUDGETS = {
    "generic": {"prompt_chars": 12000, "negative_chars": 6000, "max_references": 8},
    "comfyui": {"prompt_chars": 16000, "negative_chars": 8000, "max_references": 16},
    "kling": {"prompt_chars": 5000, "negative_chars": 2500, "max_references": 4},
    "runway": {"prompt_chars": 4000, "negative_chars": 2000, "max_references": 3},
    "veo": {"prompt_chars": 8000, "negative_chars": 4000, "max_references": 4},
    "wan": {"prompt_chars": 10000, "negative_chars": 5000, "max_references": 8},
    "hunyuan": {"prompt_chars": 10000, "negative_chars": 5000, "max_references": 8},
    "ltxv": {"prompt_chars": 10000, "negative_chars": 5000, "max_references": 8},
}


def apply_provider_budget(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    result = deepcopy(payload)
    provider_name = str(provider).strip().lower() or "generic"
    budget = deepcopy(PROVIDER_BUDGETS.get(provider_name, PROVIDER_BUDGETS["generic"]))
    body = result.setdefault("payload", {})
    warnings = result.setdefault("compatibility_warnings", [])
    for field, limit_key in (("prompt", "prompt_chars"), ("negative_prompt", "negative_chars")):
        value = str(body.get(field, ""))
        limit = budget[limit_key]
        if len(value) > limit:
            body[field] = value[: max(0, limit - 1)].rstrip(" ,;\n") + "…"
            warnings.append(f"{field} 超过 {limit} 字符，已按 {provider_name} 预算截断")
    refs = list(body.get("reference_images", []) or [])
    if len(refs) > budget["max_references"]:
        refs.sort(key=lambda item: float(item.get("weight", 1.0)), reverse=True)
        body["reference_images"] = refs[: budget["max_references"]]
        warnings.append(f"参考图超过 {budget['max_references']} 张，已按权重保留优先项")
    result["budget"] = budget
    result["budget_applied"] = True
    return result


def budgeted_provider_payload(manifest: dict[str, Any] | str, provider: str, reference_image_url: str = "", provider_settings: dict[str, Any] | str | None = None) -> dict[str, Any]:
    return apply_provider_budget(provider_payload(manifest, provider, reference_image_url, provider_settings), provider)


def validate_provider_profile(profile: dict[str, Any] | str) -> dict[str, Any]:
    obj = json.loads(profile) if isinstance(profile, str) else deepcopy(profile)
    if not isinstance(obj, dict):
        raise ContinuityValidationError("provider profile 必须是对象")
    name = slugify(obj.get("name", "custom-provider"), "custom-provider")
    transport = str(obj.get("transport", "portable")).strip()
    seed_mode = str(obj.get("seed_mode", "hint")).strip()
    if transport not in {"portable", "local_workflow", "external_service", "comfyui_model"}:
        raise ContinuityValidationError("provider profile.transport 不受支持")
    if seed_mode not in {"deterministic", "hint", "adapter_hint", "unsupported"}:
        raise ContinuityValidationError("provider profile.seed_mode 不受支持")
    roles = obj.get("reference_modes", ["identity", "first_frame"])
    if not isinstance(roles, list):
        raise ContinuityValidationError("provider profile.reference_modes 必须是数组")
    budget = obj.get("budget", {})
    if not isinstance(budget, dict):
        raise ContinuityValidationError("provider profile.budget 必须是对象")
    normalized_budget = {
        "prompt_chars": max(100, min(int(budget.get("prompt_chars", 8000)), 100000)),
        "negative_chars": max(100, min(int(budget.get("negative_chars", 4000)), 50000)),
        "max_references": max(0, min(int(budget.get("max_references", 4)), 64)),
    }
    return {
        "profile_schema": "continuity-director-provider-v1",
        "name": name,
        "transport": transport,
        "seed_mode": seed_mode,
        "reference_modes": sorted({str(item).strip() for item in roles if str(item).strip()}),
        "budget": normalized_budget,
        "field_map": deepcopy(obj.get("field_map", {})) if isinstance(obj.get("field_map", {}), dict) else {},
        "notes": str(obj.get("notes", "")).strip(),
    }


def custom_provider_payload(manifest: dict[str, Any] | str, profile: dict[str, Any] | str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    provider_profile = validate_provider_profile(profile)
    obj = validate_object(manifest, "shot_manifest")
    payload = {
        "adapter_schema": "continuity-director-custom-v1",
        "provider": provider_profile["name"],
        "profile": provider_profile,
        "compatibility_warnings": [],
        "payload": {
            "prompt": obj["positive_prompt"],
            "negative_prompt": obj["negative_prompt"],
            "seed": obj["seed"],
            "duration_seconds": obj["shot"]["duration_seconds"],
            "aspect_ratio": obj["project"]["aspect_ratio"],
            "fps": obj["project"]["fps"],
            "reference_images": deepcopy(obj.get("character", {}).get("reference_images", [])),
            "provider_settings": deepcopy(settings or {}),
            "continuity_fingerprint": obj.get("fingerprint") or manifest_fingerprint(obj),
        },
    }
    budget_name = provider_profile["name"]
    PROVIDER_BUDGETS[budget_name] = deepcopy(provider_profile["budget"])
    return apply_provider_budget(payload, budget_name)


def negotiate_provider(manifest: dict[str, Any] | str, provider: str) -> dict[str, Any]:
    obj = validate_object(manifest, "shot_manifest")
    provider_name = str(provider).strip().lower() or "generic"
    if provider_name not in PROVIDERS:
        raise ContinuityValidationError(f"不支持的 provider：{provider_name}")
    capabilities = deepcopy(PROVIDER_CAPABILITIES[provider_name])
    requested_roles = {item.get("role", "identity") for item in obj.get("character", {}).get("reference_images", [])}
    supported_roles = set(capabilities.get("reference_modes", []))
    unsupported = sorted(requested_roles - supported_roles)
    issues: list[dict[str, Any]] = []
    for role in unsupported:
        issues.append(make_issue("REFERENCE_ROLE_UNSUPPORTED", "warning", "character.reference_images", "平台未声明支持该参考图角色", role=role))
    if capabilities.get("seed_mode") in {"hint", "adapter_hint", "unsupported"}:
        issues.append(make_issue("SEED_NOT_GUARANTEED", "warning", "seed", "该平台不保证原生采用传入 seed", mode=capabilities.get("seed_mode")))
    strategy = {
        "use_first_frame": "first_frame" in supported_roles,
        "use_last_frame": "last_frame" in supported_roles,
        "use_identity_reference": bool({"identity", "face"} & supported_roles),
        "seed_policy": capabilities.get("seed_mode"),
        "transport": capabilities.get("transport"),
    }
    return {
        "provider": provider_name,
        "compatible": not any(item["severity"] == "error" for item in issues),
        "capabilities": capabilities,
        "strategy": strategy,
        "issues": issues,
    }


class ContentAddressedCache:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_for(value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        if not re_full_hex(key, 64):
            raise ContinuityValidationError("cache key 必须是 64 位十六进制 SHA-256")
        return self.root / key[:2] / f"{key}.json"

    def put(self, value: Any) -> tuple[str, Path]:
        key = self.key_for(value)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd, temp_name = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(value, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, path)
            except Exception:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
        return key, path

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def prune(self, max_entries: int = 1000) -> int:
        if max_entries < 0:
            raise ContinuityValidationError("max_entries 不能为负数")
        files = sorted(self.root.glob("*/*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        removed = 0
        for path in files[max_entries:]:
            path.unlink(missing_ok=True)
            removed += 1
        return removed


def re_full_hex(value: str, length: int) -> bool:
    return len(value) == length and all(char in "0123456789abcdef" for char in value.lower())


def save_checkpoint(path: str | os.PathLike[str], sequence: dict[str, Any] | str, completed_shot_ids: Iterable[str] = ()) -> Path:
    obj = json.loads(sequence) if isinstance(sequence, str) else deepcopy(sequence)
    if obj.get("type") != "sequence_manifest":
        raise ContinuityValidationError("checkpoint 仅支持 sequence_manifest")
    known_ids = {shot.get("shot", {}).get("shot_id") for shot in obj.get("shots", [])}
    completed = [slugify(item, "") for item in completed_shot_ids if slugify(item, "")]
    unknown = sorted(set(completed) - known_ids)
    if unknown:
        raise ContinuityValidationError(f"completed_shot_ids 含未知镜头：{', '.join(unknown)}")
    payload = {
        "checkpoint_schema": "continuity-director-checkpoint-v1",
        "package_version": PACKAGE_VERSION,
        "sequence_fingerprint": obj.get("fingerprint") or manifest_fingerprint(obj),
        "completed_shot_ids": completed,
        "remaining_shot_ids": [shot_id for shot_id in known_ids if shot_id not in set(completed)],
        "sequence": obj,
    }
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
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


def load_checkpoint(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("checkpoint_schema") != "continuity-director-checkpoint-v1":
        raise ContinuityValidationError("不支持的 checkpoint schema")
    sequence = payload.get("sequence", {})
    expected = payload.get("sequence_fingerprint")
    actual = sequence.get("fingerprint") or manifest_fingerprint(sequence)
    if expected != actual:
        raise ContinuityValidationError("checkpoint 中的序列指纹不一致")
    return payload


def verify_sequence_package(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    issues: list[dict[str, Any]] = []
    checked = 0
    with zipfile.ZipFile(target, "r") as archive:
        names = set(archive.namelist())
        required = {"sequence.json", "index.json", "checksums.sha256.json"}
        for missing in sorted(required - names):
            issues.append(make_issue("PACKAGE_FILE_MISSING", "error", missing, "项目包缺少必要文件"))
        if "checksums.sha256.json" in names:
            checksums = json.loads(archive.read("checksums.sha256.json"))
            if not isinstance(checksums, dict):
                issues.append(make_issue("CHECKSUM_INDEX_INVALID", "error", "checksums.sha256.json", "校验索引不是对象"))
            else:
                for name, expected in checksums.items():
                    checked += 1
                    if name not in names:
                        issues.append(make_issue("CHECKSUM_FILE_MISSING", "error", name, "校验索引引用的文件不存在"))
                        continue
                    actual = hashlib.sha256(archive.read(name)).hexdigest()
                    if actual != expected:
                        issues.append(make_issue("CHECKSUM_MISMATCH", "error", name, "文件 SHA-256 不匹配", expected=expected, actual=actual))
        bad_paths = [name for name in names if name.startswith("/") or ".." in Path(name).parts]
        for name in bad_paths:
            issues.append(make_issue("UNSAFE_ARCHIVE_PATH", "error", name, "项目包包含不安全路径"))
    return {
        "valid": not any(issue["severity"] == "error" for issue in issues),
        "checked_files": checked,
        "issues": issues,
        "package_path": str(target),
    }


def repair_sequence(sequence: dict[str, Any] | str, apply_fixes: bool = False) -> dict[str, Any]:
    obj = json.loads(sequence) if isinstance(sequence, str) else deepcopy(sequence)
    if obj.get("type") != "sequence_manifest":
        raise ContinuityValidationError("sequence 必须是 sequence_manifest")
    original_report = audit_sequence(obj)
    suggestions: list[dict[str, Any]] = []
    for issue in original_report.get("structural_issues", []):
        field = issue.get("field", "")
        if "sequence_index" in field:
            suggestions.append(make_issue("FIX_SEQUENCE_INDEX", "info", field, "按数组顺序重建 sequence_index"))
        elif "parent_fingerprint" in field:
            suggestions.append(make_issue("FIX_PARENT_LINK", "info", field, "使用上一镜最新指纹重建父链"))
        elif "shot_id" in field:
            suggestions.append(make_issue("FIX_DUPLICATE_SHOT_ID", "info", field, "为重复镜头 ID 添加稳定序号"))
    if not apply_fixes:
        return {"changed": False, "sequence": obj, "before": original_report, "after": original_report, "suggestions": suggestions}

    seen: dict[str, int] = {}
    previous_fingerprint = None
    for index, shot in enumerate(obj.get("shots", []), start=1):
        shot_id = slugify(shot.get("shot", {}).get("shot_id", f"shot-{index:03d}"), f"shot-{index:03d}")
        seen[shot_id] = seen.get(shot_id, 0) + 1
        if seen[shot_id] > 1:
            shot_id = f"{shot_id}-{seen[shot_id]}"
            shot.setdefault("shot", {})["shot_id"] = shot_id
        shot.setdefault("lineage", {})["sequence_index"] = index
        shot["lineage"]["parent_fingerprint"] = previous_fingerprint
        shot["previous_shot_id"] = obj["shots"][index - 2].get("shot", {}).get("shot_id") if index > 1 else None
        shot["fingerprint"] = manifest_fingerprint(shot)
        previous_fingerprint = shot["fingerprint"]
    obj["shot_count"] = len(obj.get("shots", []))
    obj["total_duration_seconds"] = round(sum(float(item.get("shot", {}).get("duration_seconds", 0)) for item in obj.get("shots", [])), 3)
    obj["fingerprint"] = manifest_fingerprint(obj)
    after = audit_sequence(obj)
    return {"changed": obj != (json.loads(sequence) if isinstance(sequence, str) else sequence), "sequence": obj, "before": original_report, "after": after, "suggestions": suggestions}


def sequence_to_ndjson(sequence: dict[str, Any] | str) -> str:
    obj = json.loads(sequence) if isinstance(sequence, str) else deepcopy(sequence)
    if obj.get("type") != "sequence_manifest":
        raise ContinuityValidationError("sequence 必须是 sequence_manifest")
    header = {
        "record_type": "sequence_header",
        "schema_version": obj.get("schema_version", SCHEMA_VERSION),
        "sequence_id": obj.get("sequence_id"),
        "project_id": obj.get("project_id"),
        "character_id": obj.get("character_id"),
    }
    lines = [json.dumps(header, ensure_ascii=False, sort_keys=True)]
    for shot in obj.get("shots", []):
        lines.append(json.dumps({"record_type": "shot", "manifest": shot}, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + "\n"


def sequence_from_ndjson(text: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(str(text).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContinuityValidationError(f"NDJSON 第 {line_number} 行无效：{exc}") from exc
        if not isinstance(record, dict):
            raise ContinuityValidationError(f"NDJSON 第 {line_number} 行必须是对象")
        records.append(record)
    if not records or records[0].get("record_type") != "sequence_header":
        raise ContinuityValidationError("NDJSON 缺少 sequence_header")
    header = records[0]
    shots = [deepcopy(item.get("manifest")) for item in records[1:] if item.get("record_type") == "shot"]
    if not shots or any(not isinstance(item, dict) for item in shots):
        raise ContinuityValidationError("NDJSON 不包含有效镜头")
    sequence = {
        "schema_version": header.get("schema_version", SCHEMA_VERSION),
        "type": "sequence_manifest",
        "sequence_id": slugify(header.get("sequence_id", "sequence-01"), "sequence-01"),
        "project_id": header.get("project_id") or shots[0].get("project", {}).get("project_id"),
        "character_id": header.get("character_id") or shots[0].get("character", {}).get("character_id"),
        "shot_count": len(shots),
        "total_duration_seconds": round(sum(float(item.get("shot", {}).get("duration_seconds", 0)) for item in shots), 3),
        "shots": shots,
        "warnings": [warning for shot in shots for warning in shot.get("warnings", [])],
    }
    sequence["fingerprint"] = manifest_fingerprint(sequence)
    return sequence


def production_report(sequence: dict[str, Any] | str, provider: str = "generic") -> dict[str, Any]:
    obj = json.loads(sequence) if isinstance(sequence, str) else deepcopy(sequence)
    if obj.get("type") != "sequence_manifest":
        raise ContinuityValidationError("sequence 必须是 sequence_manifest")
    audit = audit_sequence(obj)
    durations = [float(shot.get("shot", {}).get("duration_seconds", 0)) for shot in obj.get("shots", [])]
    prompt_chars = [len(str(shot.get("positive_prompt", ""))) for shot in obj.get("shots", [])]
    warnings = [warning for shot in obj.get("shots", []) for warning in shot.get("warnings", [])]
    negotiations = [negotiate_provider(shot, provider) for shot in obj.get("shots", [])]
    provider_issue_count = sum(len(item.get("issues", [])) for item in negotiations)
    readiness = max(0, min(100, audit["score"] - min(20, len(warnings)) - min(20, provider_issue_count * 2)))
    blockers: list[dict[str, Any]] = []
    if not audit["passed"]:
        blockers.append(make_issue("SEQUENCE_AUDIT_FAILED", "error", "sequence", "序列连续性审计未通过", score=audit["score"]))
    if provider_issue_count:
        blockers.append(make_issue("PROVIDER_ADAPTATION_REQUIRED", "warning", "provider", "平台导出前仍有能力差异需要处理", count=provider_issue_count))
    return {
        "report_schema": "continuity-director-production-report-v1",
        "package_version": PACKAGE_VERSION,
        "sequence_id": obj.get("sequence_id"),
        "provider": provider,
        "readiness_score": readiness,
        "ready": readiness >= 80 and not any(item["severity"] == "error" for item in blockers),
        "metrics": {
            "shot_count": len(durations),
            "total_duration_seconds": round(sum(durations), 3),
            "average_shot_seconds": round(sum(durations) / len(durations), 3) if durations else 0,
            "maximum_prompt_characters": max(prompt_chars) if prompt_chars else 0,
            "warning_count": len(warnings),
            "provider_issue_count": provider_issue_count,
        },
        "audit": audit,
        "blockers": blockers,
    }
