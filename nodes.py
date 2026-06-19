from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .continuity_core import (
    CAMERA_MOVES,
    CAMERA_SHOTS,
    PROVIDERS,
    atomic_write_json,
    audit_manifests,
    audit_sequence,
    build_sequence_from_brief,
    migrate_object,
    package_sequence,
    validate_object,
    build_character,
    build_from_brief,
    build_project,
    build_scene,
    build_shot,
    provider_payload,
    slugify,
    to_json,
)

from .production_core import (
    build_take_variants,
    normalize_cast,
    production_report,
    repair_sequence,
    verify_sequence_package,
)

from .runtime_core import (
    build_reference_registry,
    update_reference_status,
    plan_character_presence,
    build_sequence_timeline,
    compile_dependency_graph,
    build_retry_policy,
    reconcile_task_results,
    classify_generation_failure,
    validate_model_profile,
    select_reference_frames,
    compile_execution_plan,
    diagnose_execution_plan,
)

from .orchestration_core import (
    validate_workflow_template,
    bind_workflow_template,
    build_run_snapshot,
    create_queue_state,
    claim_ready_tasks,
    reap_expired_leases,
    build_asset_index,
    validate_quality_gate,
    evaluate_take_quality,
    select_best_takes,
    plan_remakes,
    create_trace_log,
    append_trace_event,
    summarize_trace_log,
    package_run_bundle,
    verify_run_bundle,
)

from .collaboration_core import (
    create_collaboration_manifest,
    acquire_edit_lock,
    release_edit_lock,
    create_approval_record,
    transition_approval,
    create_change_request,
    review_change_request,
    append_audit_event,
    verify_audit_log,
    three_way_merge,
    register_worker,
    update_worker_heartbeat,
    detect_stale_workers,
    schedule_distributed_tasks,
    build_compatibility_matrix,
    create_environment_lockfile,
    import_bulk_records,
    validate_template_manifest,
    verify_template_trust,
    build_fault_injection_plan,
    evaluate_fault_recovery,
    build_replay_manifest,
    compare_replay_manifests,
    evaluate_generation_gate,
    build_collaboration_dashboard,
)

from .postprocess_core import (
    probe_media_file,
    build_frame_extraction_plan,
    execute_frame_extraction,
    evaluate_technical_quality,
    normalize_external_metrics,
    evaluate_boundary_continuity,
    build_sequence_assembly_plan,
    execute_sequence_assembly,
    create_version_snapshot,
    build_structured_diff,
    build_rollback_plan,
    apply_rollback_plan,
    plan_batch_rerun,
    apply_batch_rerun_plan,
    build_resource_quota,
    evaluate_resource_quota,
    reserve_resource_quota,
    collect_observability_metrics,
    build_system_health_report,
    create_regression_baseline,
    compare_regression_results,
    package_configuration_bundle,
    load_configuration_bundle,
    build_artifact_lineage,
    trace_artifact_lineage,
)

CATEGORY = "Continuity Director"


def _multiline(default: str = "") -> tuple[str, dict[str, Any]]:
    return ("STRING", {"default": default, "multiline": True, "dynamicPrompts": False})


def _validate_json_text(value: str, field_name: str) -> bool | str:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        return f"{field_name} 不是有效 JSON：{exc}"
    return True if isinstance(parsed, dict) else f"{field_name} 必须是 JSON 对象"


class CDOneClickDirector:
    DESCRIPTION = "从单个 JSON 一次生成项目锁、角色锁、场景锁与镜头 Manifest。"
    SEARCH_ALIASES = ["一键导演", "continuity", "character consistency"]

    @classmethod
    def INPUT_TYPES(cls):
        example = """{
  \"project\": {\"project_name\": \"我的短片\", \"master_seed\": 20260619, \"aspect_ratio\": \"9:16\"},
  \"character\": {\"character_id\": \"hero-01\", \"identity_description\": \"20-year-old Chinese man\", \"default_wardrobe\": \"dark jacket\"},
  \"scene\": {\"scene_id\": \"scene-01\", \"location\": \"underground garage\"},
  \"shot\": {\"shot_id\": \"shot-001\", \"action\": \"walks toward a damaged car\", \"camera_shot\": \"medium shot\"}
}"""
        return {
            "required": {"brief_json": ("STRING", {"default": example, "multiline": True, "dynamicPrompts": False})},
            "optional": {"previous_shot": ("SHOT_MANIFEST",)},
        }

    RETURN_TYPES = ("PROJECT_LOCK", "CHARACTER_LOCK", "SCENE_LOCK", "STRING", "STRING", "INT", "SHOT_MANIFEST", "STRING")
    RETURN_NAMES = ("project_lock", "character_lock", "scene_lock", "positive_prompt", "negative_prompt", "seed", "shot_manifest", "manifest_json")
    FUNCTION = "direct"
    CATEGORY = f"{CATEGORY}/00 Quick Start"

    @classmethod
    def VALIDATE_INPUTS(cls, brief_json):
        return _validate_json_text(brief_json, "brief_json")

    def direct(self, brief_json, previous_shot=None):
        result = build_from_brief(brief_json, previous_shot)
        manifest = result["manifest"]
        return (
            result["project"],
            result["character"],
            result["scene"],
            manifest["positive_prompt"],
            manifest["negative_prompt"],
            manifest["seed"],
            manifest,
            to_json(manifest),
        )


class CDProjectLock:
    SEARCH_ALIASES = ["项目锁", "project seed"]
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_name": ("STRING", {"default": "My AI Short Film"}),
                "master_seed": ("INT", {"default": 20260619, "min": 0, "max": 2**63 - 1}),
                "aspect_ratio": (["9:16", "16:9", "1:1", "4:3", "3:4", "21:9"],),
                "fps": ("INT", {"default": 24, "min": 1, "max": 120}),
                "visual_style": _multiline("cinematic realistic photography, natural skin texture, physically plausible lighting"),
                "color_palette": ("STRING", {"default": "neutral cinematic palette"}),
                "lighting_rule": _multiline("keep key-light direction and color temperature stable inside the same scene"),
                "global_negative": _multiline(""),
            }
        }

    RETURN_TYPES = ("PROJECT_LOCK", "STRING")
    RETURN_NAMES = ("project_lock", "project_json")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def create(self, project_name, master_seed, aspect_ratio, fps, visual_style, color_palette, lighting_rule, global_negative):
        project = build_project(project_name, master_seed, aspect_ratio, fps, visual_style, color_palette, lighting_rule, global_negative)
        return (project, to_json(project))


class CDCharacterLock:
    SEARCH_ALIASES = ["角色锁", "character identity"]
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_lock": ("PROJECT_LOCK",),
                "character_id": ("STRING", {"default": "hero-01"}),
                "display_name": ("STRING", {"default": "主角"}),
                "identity_description": _multiline("20-year-old Chinese man, recognizable natural face, calm but alert expression"),
                "face_features": _multiline("oval face, straight eyebrows, single eyelids, medium nose bridge, small scar near right eyebrow"),
                "hair": _multiline("short slightly messy black hair, fixed length and parting"),
                "body_features": _multiline("slim athletic build, average height, fixed shoulder width and limb proportions"),
                "default_wardrobe": _multiline("dark charcoal hooded jacket, washed black T-shirt, dark cargo pants, worn black sneakers"),
                "signature_props": _multiline("silver analog watch on left wrist"),
                "immutable_rules": _multiline("scar remains on right eyebrow, watch remains on left wrist, no wardrobe redesign"),
                "protected_state_fields": _multiline("wardrobe, props"),
                "reference_image_url": ("STRING", {"default": ""}),
                "reference_images_json": _multiline("[]"),
            }
        }

    RETURN_TYPES = ("CHARACTER_LOCK", "STRING", "STRING")
    RETURN_NAMES = ("character_lock", "character_json", "identity_anchor")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def create(self, project_lock, character_id, display_name, identity_description, face_features, hair, body_features, default_wardrobe, signature_props, immutable_rules, protected_state_fields, reference_image_url, reference_images_json):
        character = build_character(project_lock, character_id, display_name, identity_description, face_features, hair, body_features, default_wardrobe, signature_props, immutable_rules, reference_image_url, protected_state_fields, reference_images_json)
        return (character, to_json(character), character["identity_anchor"])


class CDSceneLock:
    SEARCH_ALIASES = ["场景锁", "scene consistency"]
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_lock": ("PROJECT_LOCK",),
                "character_lock": ("CHARACTER_LOCK",),
                "scene_id": ("STRING", {"default": "scene-01"}),
                "location": _multiline("abandoned underground parking garage"),
                "time_of_day": ("STRING", {"default": "late night"}),
                "weather": ("STRING", {"default": "heavy rain outside"}),
                "lighting": _multiline("cold fluorescent ceiling lights, weak red emergency light from camera right"),
                "environment_details": _multiline("wet concrete floor, numbered pillars, one damaged sedan, shallow puddles"),
                "screen_direction": _multiline("character generally moves from screen left to screen right"),
                "persistent_objects": _multiline("damaged sedan at pillar B7, red fire cabinet, yellow floor line"),
            }
        }

    RETURN_TYPES = ("SCENE_LOCK", "STRING")
    RETURN_NAMES = ("scene_lock", "scene_json")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def create(self, project_lock, character_lock, scene_id, location, time_of_day, weather, lighting, environment_details, screen_direction, persistent_objects):
        scene = build_scene(project_lock, character_lock, scene_id, location, time_of_day, weather, lighting, environment_details, screen_direction, persistent_objects)
        return (scene, to_json(scene))


class CDShotDirector:
    SEARCH_ALIASES = ["镜头导演", "shot prompt"]
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_lock": ("PROJECT_LOCK",),
                "character_lock": ("CHARACTER_LOCK",),
                "scene_lock": ("SCENE_LOCK",),
                "shot_id": ("STRING", {"default": "shot-001"}),
                "duration_seconds": ("FLOAT", {"default": 5.0, "min": 0.1, "max": 120.0, "step": 0.1}),
                "action": _multiline("the character walks carefully toward the damaged sedan and raises a flashlight"),
                "emotion": ("STRING", {"default": "restrained tension"}),
                "dialogue": _multiline(""),
                "camera_shot": (list(CAMERA_SHOTS),),
                "camera_move": (list(CAMERA_MOVES),),
                "lens": ("STRING", {"default": "35mm"}),
                "composition": _multiline("character on left third, sedan in deep background, stable horizon"),
                "motion_rules": _multiline("natural walking pace, no sudden body morphing, hands remain anatomically stable"),
                "allowed_changes": _multiline("emotion, position"),
                "wardrobe_override": _multiline(""),
                "props_override": _multiline(""),
                "injuries": _multiline(""),
                "dirt_and_damage": _multiline(""),
                "position": _multiline("near pillar B6, facing screen right"),
                "custom_state_json": _multiline(""),
                "state_patch_json": _multiline(""),
                "transition_json": _multiline(""),
                "sequence_index": ("INT", {"default": 0, "min": 0, "max": 100000}),
                "seed_salt": ("STRING", {"default": ""}),
            },
            "optional": {"previous_shot": ("SHOT_MANIFEST",)},
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "SHOT_MANIFEST", "STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "seed", "shot_manifest", "manifest_json", "warnings")
    FUNCTION = "direct"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def direct(self, project_lock, character_lock, scene_lock, shot_id, duration_seconds, action, emotion, dialogue, camera_shot, camera_move, lens, composition, motion_rules, allowed_changes, wardrobe_override, props_override, injuries, dirt_and_damage, position, custom_state_json, state_patch_json, transition_json, sequence_index, seed_salt, previous_shot=None):
        manifest = build_shot(
            project_lock,
            character_lock,
            scene_lock,
            shot_id,
            duration_seconds,
            action,
            emotion,
            dialogue,
            camera_shot,
            camera_move,
            lens,
            composition,
            motion_rules,
            previous_shot,
            allowed_changes,
            wardrobe_override,
            props_override,
            injuries,
            dirt_and_damage,
            position,
            custom_state_json,
            state_patch_json,
            transition_json,
            sequence_index,
            seed_salt,
        )
        return (
            manifest["positive_prompt"],
            manifest["negative_prompt"],
            manifest["seed"],
            manifest,
            to_json(manifest),
            "\n".join(manifest["warnings"]),
        )


class CDBatchDirector:
    DESCRIPTION = "把 shots 数组编译成带父子指纹的完整镜头序列。"
    SEARCH_ALIASES = ["批量导演", "storyboard", "shot sequence"]

    @classmethod
    def INPUT_TYPES(cls):
        example = """{
  "sequence_id": "episode-01",
  "project": {"project_name": "连续短片", "master_seed": 20260619},
  "character": {"identity_description": "recognizable natural person", "default_wardrobe": "dark jacket"},
  "scene": {"location": "parking garage"},
  "shots": [
    {"shot_id": "shot-001", "action": "walks toward the car"},
    {"shot_id": "shot-002", "action": "opens the car door"}
  ]
}"""
        return {
            "required": {"sequence_brief_json": ("STRING", {"default": example, "multiline": True, "dynamicPrompts": False})},
            "optional": {"previous_shot": ("SHOT_MANIFEST",)},
        }

    RETURN_TYPES = ("SEQUENCE_MANIFEST", "STRING", "SHOT_MANIFEST", "INT", "FLOAT")
    RETURN_NAMES = ("sequence_manifest", "sequence_json", "last_shot", "shot_count", "total_duration_seconds")
    FUNCTION = "direct"
    CATEGORY = f"{CATEGORY}/02 Direct"

    @classmethod
    def VALIDATE_INPUTS(cls, sequence_brief_json):
        return _validate_json_text(sequence_brief_json, "sequence_brief_json")

    def direct(self, sequence_brief_json, previous_shot=None):
        sequence = build_sequence_from_brief(sequence_brief_json, previous_shot)
        return (sequence, to_json(sequence), sequence["shots"][-1], sequence["shot_count"], sequence["total_duration_seconds"])


class CDSequenceAudit:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sequence_manifest": ("SEQUENCE_MANIFEST",)}}

    RETURN_TYPES = ("INT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("score", "passed", "audit_json")
    FUNCTION = "audit"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def audit(self, sequence_manifest):
        report = audit_sequence(sequence_manifest)
        return (report["score"], report["passed"], to_json(report))


class CDPackageProject:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sequence_manifest": ("SEQUENCE_MANIFEST",),
                "provider": (list(PROVIDERS),),
                "filename_prefix": ("STRING", {"default": "continuity/sequence-package"}),
                "overwrite": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("package_path",)
    FUNCTION = "save"
    CATEGORY = f"{CATEGORY}/04 Export"
    OUTPUT_NODE = True

    def save(self, sequence_manifest, provider, filename_prefix, overwrite):
        try:
            import folder_paths  # type: ignore
            output_dir = Path(folder_paths.get_output_directory())
        except Exception:
            output_dir = Path.cwd() / "output"
        prefix = Path(filename_prefix)
        safe_parent = Path(*[slugify(part, "continuity") for part in prefix.parts[:-1]]) if len(prefix.parts) > 1 else Path()
        safe_name = slugify(prefix.name, "sequence-package")
        target = output_dir / safe_parent / f"{safe_name}.zip"
        saved = package_sequence(target, sequence_manifest, provider=provider, overwrite=bool(overwrite))
        return (str(saved),)


class CDContinuityAudit:
    SEARCH_ALIASES = ["连续性审计", "consistency score"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"previous_shot": ("SHOT_MANIFEST",), "current_shot": ("SHOT_MANIFEST",)}}

    RETURN_TYPES = ("INT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("score", "passed", "audit_json")
    FUNCTION = "audit"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def audit(self, previous_shot, current_shot):
        report = audit_manifests(previous_shot, current_shot)
        return (report["score"], report["passed"], to_json(report))


class CDManifestValidator:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "manifest_json": _multiline("{}"),
                "expected_type": (["auto", "project_lock", "character_lock", "scene_lock", "shot_manifest", "sequence_manifest"],),
            }
        }

    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("valid", "normalized_json", "validation_message")
    FUNCTION = "validate"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def validate(self, manifest_json, expected_type):
        try:
            expected = None if expected_type == "auto" else expected_type
            data = validate_object(manifest_json, expected)
            return (True, to_json(data), "校验通过")
        except Exception as exc:
            return (False, "", str(exc))


class CDManifestMigrate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"legacy_manifest_json": _multiline("{}")}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("migrated_json", "migration_message")
    FUNCTION = "migrate"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def migrate(self, legacy_manifest_json):
        migrated = migrate_object(legacy_manifest_json)
        return (to_json(migrated), f"已迁移到 schema {migrated.get('schema_version')}")


class CDProviderExport:
    SEARCH_ALIASES = ["平台导出", "provider adapter"]
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_manifest": ("SHOT_MANIFEST",),
                "provider": (list(PROVIDERS),),
                "reference_image_url": ("STRING", {"default": ""}),
                "provider_settings_json": _multiline("{}"),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("provider_payload_json",)
    FUNCTION = "export"
    CATEGORY = f"{CATEGORY}/04 Export"

    def export(self, shot_manifest, provider, reference_image_url, provider_settings_json):
        settings = json.loads(provider_settings_json) if provider_settings_json.strip() else {}
        return (to_json(provider_payload(shot_manifest, provider, reference_image_url, settings)),)


class CDSaveManifest:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_manifest": ("SHOT_MANIFEST",),
                "filename_prefix": ("STRING", {"default": "continuity/shot"}),
                "overwrite": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    FUNCTION = "save"
    CATEGORY = f"{CATEGORY}/04 Export"
    OUTPUT_NODE = True

    def save(self, shot_manifest, filename_prefix, overwrite):
        try:
            import folder_paths  # type: ignore

            output_dir = Path(folder_paths.get_output_directory())
        except Exception:
            output_dir = Path.cwd() / "output"

        prefix = Path(filename_prefix)
        safe_parent = Path(*[slugify(part, "continuity") for part in prefix.parts[:-1]]) if len(prefix.parts) > 1 else Path()
        safe_name = slugify(prefix.name, "shot")
        shot_id = slugify(shot_manifest.get("shot", {}).get("shot_id", "shot"), "shot")
        fingerprint = slugify(shot_manifest.get("fingerprint", "manifest"), "manifest")
        target = output_dir / safe_parent / f"{safe_name}-{shot_id}-{fingerprint}.json"
        saved = atomic_write_json(target, shot_manifest, overwrite=bool(overwrite))
        return (str(saved),)


class CDCastLock:
    DESCRIPTION = "从角色配置数组创建多角色演员表锁。"
    SEARCH_ALIASES = ["演员表", "多角色", "cast lock"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_lock": ("PROJECT_LOCK",),
                "characters_json": _multiline('{"characters":[{"character_id":"hero","display_name":"主角","identity_description":"recognizable natural person"}]}'),
            }
        }

    RETURN_TYPES = ("CAST_LOCK", "STRING", "INT")
    RETURN_NAMES = ("cast_lock", "cast_json", "character_count")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def create(self, project_lock, characters_json):
        config = json.loads(characters_json)
        cast = normalize_cast(project_lock, config.get("characters", []))
        return (cast, to_json(cast), cast["character_count"])


class CDTakeVariants:
    DESCRIPTION = "为同一镜头生成确定性 Take，避免无规则重复抽卡。"
    SEARCH_ALIASES = ["多次生成", "镜头重试", "take variants"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "brief_json": _multiline('{"project":{"project_name":"film"},"character":{"identity_description":"person"},"scene":{"location":"room"},"shot":{"action":"turns around"}}'),
                "take_count": ("INT", {"default": 3, "min": 1, "max": 32}),
                "strategy": (["seed_only", "camera_micro_variation"],),
            },
            "optional": {"previous_shot": ("SHOT_MANIFEST",)},
        }

    RETURN_TYPES = ("TAKE_GROUP", "STRING", "SHOT_MANIFEST", "INT")
    RETURN_NAMES = ("take_group", "take_group_json", "first_take", "take_count")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def build(self, brief_json, take_count, strategy, previous_shot=None):
        group = build_take_variants(brief_json, int(take_count), previous_shot, strategy)
        return (group, to_json(group), group["takes"][0], group["take_count"])


class CDSequenceRepair:
    DESCRIPTION = "预览或应用镜头序号、重复 ID 与父指纹链修复。"
    SEARCH_ALIASES = ["序列修复", "repair sequence"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sequence_manifest": ("SEQUENCE_MANIFEST",), "apply_fixes": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("SEQUENCE_MANIFEST", "BOOLEAN", "STRING")
    RETURN_NAMES = ("repaired_sequence", "changed", "repair_report_json")
    FUNCTION = "repair"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def repair(self, sequence_manifest, apply_fixes):
        result = repair_sequence(sequence_manifest, bool(apply_fixes))
        return (result["sequence"], result["changed"], to_json(result))


class CDProductionReport:
    DESCRIPTION = "生成序列生产就绪评分、阻断项和平台能力差异报告。"
    SEARCH_ALIASES = ["生产报告", "就绪评分", "production report"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sequence_manifest": ("SEQUENCE_MANIFEST",), "provider": (list(PROVIDERS),)}}

    RETURN_TYPES = ("INT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("readiness_score", "ready", "report_json")
    FUNCTION = "report"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def report(self, sequence_manifest, provider):
        report = production_report(sequence_manifest, provider)
        return (report["readiness_score"], report["ready"], to_json(report))


class CDPackageVerify:
    DESCRIPTION = "检查项目 ZIP 的必要文件、路径安全与 SHA-256 完整性。"
    SEARCH_ALIASES = ["项目包验证", "校验压缩包", "verify package"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"package_path": ("STRING", {"default": "output/continuity/sequence-package.zip"})}}

    RETURN_TYPES = ("BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("valid", "checked_files", "verification_json")
    FUNCTION = "verify"
    CATEGORY = f"{CATEGORY}/04 Export"

    def verify(self, package_path):
        result = verify_sequence_package(package_path)
        return (result["valid"], result["checked_files"], to_json(result))


class CDReferenceRegistry:
    DESCRIPTION = "登记角色、场景、首尾帧参考图，并管理批准与退役状态。"
    SEARCH_ALIASES = ["参考帧库", "reference registry", "角色参考图"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_lock": ("PROJECT_LOCK",), "frames_json": _multiline("[]")}}

    RETURN_TYPES = ("REFERENCE_REGISTRY", "STRING", "INT")
    RETURN_NAMES = ("reference_registry", "registry_json", "frame_count")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def build(self, project_lock, frames_json):
        registry = build_reference_registry(project_lock, frames_json)
        return (registry, to_json(registry), registry["frame_count"])


class CDReferenceStatus:
    DESCRIPTION = "批准、拒绝或退役一张参考帧。"
    SEARCH_ALIASES = ["参考帧状态", "approve reference"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"reference_registry": ("REFERENCE_REGISTRY",), "frame_id": ("STRING", {"default": "ref-001"}), "status": (["candidate", "approved", "rejected", "retired"],), "notes": _multiline("")}}

    RETURN_TYPES = ("REFERENCE_REGISTRY", "STRING")
    RETURN_NAMES = ("reference_registry", "registry_json")
    FUNCTION = "update"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def update(self, reference_registry, frame_id, status, notes):
        registry = update_reference_status(reference_registry, frame_id, status, notes)
        return (registry, to_json(registry))


class CDPresencePlan:
    DESCRIPTION = "检查多角色在每个镜头的入场、在场、离场与缺席状态。"
    SEARCH_ALIASES = ["角色出入场", "presence plan"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"cast_lock": ("CAST_LOCK",), "sequence_manifest": ("SEQUENCE_MANIFEST",), "presence_json": _multiline("[]")}}

    RETURN_TYPES = ("PRESENCE_PLAN", "BOOLEAN", "STRING")
    RETURN_NAMES = ("presence_plan", "valid", "plan_json")
    FUNCTION = "plan"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def plan(self, cast_lock, sequence_manifest, presence_json):
        result = plan_character_presence(cast_lock, sequence_manifest, presence_json)
        return (result, result["valid"], to_json(result))


class CDSequenceTimeline:
    DESCRIPTION = "把镜头时长转换为精确帧区间与 HH:MM:SS:FF 时间码。"
    SEARCH_ALIASES = ["序列时间线", "timecode", "frame timeline"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sequence_manifest": ("SEQUENCE_MANIFEST",), "start_timecode": ("STRING", {"default": "00:00:00:00"}), "handle_frames": ("INT", {"default": 0, "min": 0, "max": 240})}}

    RETURN_TYPES = ("SEQUENCE_TIMELINE", "INT", "STRING")
    RETURN_NAMES = ("timeline", "total_frames", "timeline_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def build(self, sequence_manifest, start_timecode, handle_frames):
        result = build_sequence_timeline(sequence_manifest, start_timecode, handle_frames)
        return (result, result["total_frames"], to_json(result))


class CDDependencyGraph:
    DESCRIPTION = "建立镜头依赖 DAG，检测循环和不存在的依赖。"
    SEARCH_ALIASES = ["镜头依赖图", "dependency graph", "DAG"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"sequence_manifest": ("SEQUENCE_MANIFEST",), "extra_dependencies_json": _multiline("[]")}}

    RETURN_TYPES = ("DEPENDENCY_GRAPH", "BOOLEAN", "STRING")
    RETURN_NAMES = ("dependency_graph", "valid", "graph_json")
    FUNCTION = "compile"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def compile(self, sequence_manifest, extra_dependencies_json):
        result = compile_dependency_graph(sequence_manifest, extra_dependencies_json)
        return (result, result["valid"], to_json(result))


class CDRetryPolicy:
    DESCRIPTION = "生成可复现重试策略，控制尝试次数、种子变化和退避时间。"
    SEARCH_ALIASES = ["失败重试", "retry policy"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"max_attempts": ("INT", {"default": 3, "min": 1, "max": 10}), "seed_strategy": (["same", "increment", "stable_variant"],), "backoff_json": _multiline("[0, 2, 5]"), "retryable_codes": ("STRING", {"default": "timeout,rate_limit,provider_error,oom"})}}

    RETURN_TYPES = ("RETRY_POLICY", "STRING")
    RETURN_NAMES = ("retry_policy", "policy_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def build(self, max_attempts, seed_strategy, backoff_json, retryable_codes):
        backoff = json.loads(backoff_json)
        codes = [item.strip() for item in retryable_codes.split(",") if item.strip()]
        result = build_retry_policy(max_attempts, seed_strategy, backoff, codes)
        return (result, to_json(result))


class CDModelProfile:
    DESCRIPTION = "创建不执行代码、不保存密钥的声明式视频模型配置。"
    SEARCH_ALIASES = ["模型配置", "model profile"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"profile_json": _multiline('{"profile_id":"local-general-video","transport":"local_workflow","supports_seed":true,"supports_identity_reference":true,"supports_first_frame":true,"supports_last_frame":false,"supports_negative_prompt":true,"max_reference_images":4,"max_duration_seconds":10,"supported_fps":[24]}')}}

    RETURN_TYPES = ("MODEL_PROFILE", "STRING")
    RETURN_NAMES = ("model_profile", "profile_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def build(self, profile_json):
        result = validate_model_profile(profile_json)
        return (result, to_json(result))


class CDReferenceSelector:
    DESCRIPTION = "按镜头、角色、场景、权重和模型能力自动选择参考帧。"
    SEARCH_ALIASES = ["参考图选择", "reference selector"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"reference_registry": ("REFERENCE_REGISTRY",), "shot_manifest": ("SHOT_MANIFEST",), "model_profile": ("MODEL_PROFILE",), "preferred_roles": ("STRING", {"default": "identity,face,wardrobe,first_frame,last_frame"})}}

    RETURN_TYPES = ("REFERENCE_SELECTION", "INT", "STRING")
    RETURN_NAMES = ("reference_selection", "selected_count", "selection_json")
    FUNCTION = "select"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def select(self, reference_registry, shot_manifest, model_profile, preferred_roles):
        roles = [item.strip() for item in preferred_roles.split(",") if item.strip()]
        result = select_reference_frames(reference_registry, shot_manifest, model_profile, roles)
        return (result, result["selected_count"], to_json(result))


class CDExecutionPlan:
    DESCRIPTION = "一次编译模型能力、参考帧、依赖图、并行波次、任务队列、重试策略和成本估算。"
    SEARCH_ALIASES = ["执行计划", "generation plan", "生产调度"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sequence_manifest": ("SEQUENCE_MANIFEST",),
                "model_profile": ("MODEL_PROFILE",),
                "provider": (list(PROVIDERS),),
                "max_parallel": ("INT", {"default": 2, "min": 1, "max": 64}),
                "take_count": ("INT", {"default": 1, "min": 1, "max": 16}),
                "extra_dependencies_json": _multiline("[]"),
            },
            "optional": {"reference_registry": ("REFERENCE_REGISTRY",), "retry_policy": ("RETRY_POLICY",)},
        }

    RETURN_TYPES = ("EXECUTION_PLAN", "GENERATION_QUEUE", "BOOLEAN", "STRING")
    RETURN_NAMES = ("execution_plan", "task_queue", "blocked", "plan_json")
    FUNCTION = "compile"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def compile(self, sequence_manifest, model_profile, provider, max_parallel, take_count, extra_dependencies_json, reference_registry=None, retry_policy=None):
        result = compile_execution_plan(sequence_manifest, model_profile, reference_registry, provider, max_parallel, take_count, retry_policy, extra_dependencies_json)
        return (result, result["task_queue"], result["blocked"], to_json(result))


class CDTaskReconcile:
    DESCRIPTION = "把外部或本地生成任务结果安全回填到任务队列。"
    SEARCH_ALIASES = ["任务结果回填", "task reconciliation"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"generation_queue": ("GENERATION_QUEUE",), "results_json": _multiline("[]")}}

    RETURN_TYPES = ("TASK_RECONCILIATION", "BOOLEAN", "BOOLEAN", "STRING")
    RETURN_NAMES = ("reconciliation", "valid", "complete", "report_json")
    FUNCTION = "reconcile"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def reconcile(self, generation_queue, results_json):
        result = reconcile_task_results(generation_queue, results_json)
        return (result, result["valid"], result["complete"], to_json(result))


class CDFailureClassifier:
    DESCRIPTION = "识别超时、限流、显存不足、审核拦截和参数错误，并给出恢复动作。"
    SEARCH_ALIASES = ["错误分类", "failure classifier", "恢复建议"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"error_text": _multiline("")}}

    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("category", "retryable", "recommended_action", "classification_json")
    FUNCTION = "classify"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def classify(self, error_text):
        result = classify_generation_failure(error_text)
        return (result["category"], result["retryable"], result["recommended_action"], to_json(result))


class CDExecutionDiagnostics:
    DESCRIPTION = "分析关键路径、并行利用率、参考帧覆盖、重复任务和阻断项。"
    SEARCH_ALIASES = ["执行诊断", "bottleneck analysis", "生产诊断"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"execution_plan": ("EXECUTION_PLAN",)}}

    RETURN_TYPES = ("INT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("score", "ready", "diagnostic_json")
    FUNCTION = "diagnose"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def diagnose(self, execution_plan):
        result = diagnose_execution_plan(execution_plan)
        return (result["score"], result["ready"], to_json(result))


class CDWorkflowTemplate:
    DESCRIPTION = "校验声明式 ComfyUI/API 工作流模板，不执行任意代码。"
    SEARCH_ALIASES = ["工作流模板", "workflow template"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template_json": _multiline('{"template_id":"video-workflow","nodes":[{"node_id":"prompt","class_type":"CLIPTextEncode","inputs":{"text":"${positive_prompt}"}}]}')}}

    RETURN_TYPES = ("WORKFLOW_TEMPLATE", "STRING", "INT")
    RETURN_NAMES = ("workflow_template", "template_json", "node_count")
    FUNCTION = "validate"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def validate(self, template_json):
        result = validate_workflow_template(template_json)
        return (result, to_json(result), result["node_count"])


class CDWorkflowBind:
    DESCRIPTION = "把镜头、种子和参考图安全绑定到工作流占位符。"
    SEARCH_ALIASES = ["工作流绑定", "bind workflow"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"workflow_template": ("WORKFLOW_TEMPLATE",), "values_json": _multiline("{}"), "allow_missing": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("BOUND_WORKFLOW", "BOOLEAN", "STRING")
    RETURN_NAMES = ("bound_workflow", "ready", "workflow_json")
    FUNCTION = "bind"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def bind(self, workflow_template, values_json, allow_missing):
        result = bind_workflow_template(workflow_template, values_json, bool(allow_missing))
        return (result, result["ready"], to_json(result))


class CDRunSnapshot:
    DESCRIPTION = "生成可复现且已移除密钥的运行配置快照。"
    SEARCH_ALIASES = ["运行快照", "run snapshot"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_lock": ("PROJECT_LOCK",), "sequence_manifest": ("SEQUENCE_MANIFEST",), "model_profile": ("MODEL_PROFILE",), "workflow_template": ("WORKFLOW_TEMPLATE",), "settings_json": _multiline("{}")}}

    RETURN_TYPES = ("RUN_SNAPSHOT", "STRING", "INT")
    RETURN_NAMES = ("run_snapshot", "snapshot_json", "redacted_count")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def build(self, project_lock, sequence_manifest, model_profile, workflow_template, settings_json):
        result = build_run_snapshot(project_lock, sequence_manifest, model_profile, workflow_template, settings_json)
        return (result, to_json(result), len(result["redacted_paths"]))


class CDQueueState:
    DESCRIPTION = "把生成任务队列转换为可持久化、可恢复的调度状态。"
    SEARCH_ALIASES = ["持久化队列", "queue state"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"generation_queue": ("GENERATION_QUEUE",)}, "optional": {"run_snapshot": ("RUN_SNAPSHOT",)}}

    RETURN_TYPES = ("PERSISTENT_QUEUE", "STRING", "INT")
    RETURN_NAMES = ("queue_state", "queue_json", "task_count")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def build(self, generation_queue, run_snapshot=None):
        result = create_queue_state(generation_queue, run_snapshot)
        return (result, to_json(result), result["task_count"])


class CDQueueClaim:
    DESCRIPTION = "按依赖和优先级领取任务，并创建防重复租约。"
    SEARCH_ALIASES = ["任务领取", "claim tasks", "worker lease"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"queue_state": ("PERSISTENT_QUEUE",), "worker_id": ("STRING", {"default": "worker-01"}), "limit": ("INT", {"default": 1, "min": 1, "max": 128}), "lease_seconds": ("INT", {"default": 300, "min": 1, "max": 86400})}}

    RETURN_TYPES = ("PERSISTENT_QUEUE", "STRING", "INT")
    RETURN_NAMES = ("queue_state", "claimed_json", "claimed_count")
    FUNCTION = "claim"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def claim(self, queue_state, worker_id, limit, lease_seconds):
        result = claim_ready_tasks(queue_state, worker_id, limit, lease_seconds)
        return (result["queue_state"], to_json({"claimed": result["claimed"]}), result["claimed_count"])


class CDQueueReap:
    DESCRIPTION = "回收过期租约，把失联任务重新排队或标记失败。"
    SEARCH_ALIASES = ["租约回收", "reap leases"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"queue_state": ("PERSISTENT_QUEUE",), "max_attempts": ("INT", {"default": 3, "min": 1, "max": 100})}}

    RETURN_TYPES = ("PERSISTENT_QUEUE", "INT", "INT", "STRING")
    RETURN_NAMES = ("queue_state", "requeued_count", "failed_count", "report_json")
    FUNCTION = "reap"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def reap(self, queue_state, max_attempts):
        result = reap_expired_leases(queue_state, max_attempts=max_attempts)
        return (result["queue_state"], len(result["requeued_task_ids"]), len(result["failed_task_ids"]), to_json(result))


class CDAssetIndex:
    DESCRIPTION = "建立生成视频、图片、音频、字幕和元数据的素材索引。"
    SEARCH_ALIASES = ["素材索引", "asset index"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"assets_json": _multiline("[]"), "project_id": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("ASSET_INDEX", "STRING", "INT", "INT")
    RETURN_NAMES = ("asset_index", "index_json", "asset_count", "duplicate_count")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/04 Export"

    def build(self, assets_json, project_id):
        result = build_asset_index(assets_json, project_id)
        return (result, to_json(result), result["asset_count"], result["duplicate_count"])


class CDQualityGate:
    DESCRIPTION = "定义身份、时序、动作、灯光和转场的加权验收门槛。"
    SEARCH_ALIASES = ["质量门槛", "quality gate"]

    @classmethod
    def INPUT_TYPES(cls):
        default = '{"gate_id":"production","pass_score":75,"warning_score":60,"max_remakes":2,"dimensions":{"identity_consistency":{"threshold":80,"weight":3,"required":true},"temporal_stability":{"threshold":75,"weight":2,"required":true},"prompt_alignment":{"threshold":70,"weight":1,"required":true}}}'
        return {"required": {"gate_json": _multiline(default)}}

    RETURN_TYPES = ("QUALITY_GATE", "STRING")
    RETURN_NAMES = ("quality_gate", "gate_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def build(self, gate_json):
        result = validate_quality_gate(gate_json)
        return (result, to_json(result))


class CDQualityEvaluate:
    DESCRIPTION = "评估一个 Take 的各项质量指标并给出 pass/warning/fail。"
    SEARCH_ALIASES = ["质量评估", "evaluate take"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"quality_gate": ("QUALITY_GATE",), "metrics_json": _multiline("{}"), "task_id": ("STRING", {"default": ""}), "shot_id": ("STRING", {"default": ""}), "take_index": ("INT", {"default": 1, "min": 0, "max": 999})}}

    RETURN_TYPES = ("QUALITY_EVALUATION", "FLOAT", "STRING", "STRING")
    RETURN_NAMES = ("quality_evaluation", "overall_score", "decision", "evaluation_json")
    FUNCTION = "evaluate"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def evaluate(self, quality_gate, metrics_json, task_id, shot_id, take_index):
        result = evaluate_take_quality(quality_gate, metrics_json, task_id, shot_id, take_index)
        return (result, result["overall_score"], result["decision"], to_json(result))


class CDTakeSelection:
    DESCRIPTION = "从多个质量评估中为每个镜头选择最佳 Take。"
    SEARCH_ALIASES = ["最佳 Take", "take selection"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"evaluations_json": _multiline("[]"), "require_pass": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("TAKE_SELECTION", "BOOLEAN", "STRING")
    RETURN_NAMES = ("take_selection", "complete", "selection_json")
    FUNCTION = "select"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def select(self, evaluations_json, require_pass):
        result = select_best_takes(evaluations_json, bool(require_pass))
        return (result, result["complete"], to_json(result))


class CDRemakePlan:
    DESCRIPTION = "根据失败质量维度生成有次数上限的定向重做方案。"
    SEARCH_ALIASES = ["自动重做", "remake plan"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"evaluations_json": _multiline("[]"), "quality_gate": ("QUALITY_GATE",), "previous_remakes_json": _multiline("{}")}}

    RETURN_TYPES = ("REMAKE_PLAN", "INT", "STRING")
    RETURN_NAMES = ("remake_plan", "request_count", "plan_json")
    FUNCTION = "plan"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def plan(self, evaluations_json, quality_gate, previous_remakes_json):
        result = plan_remakes(evaluations_json, quality_gate, previous_remakes_json)
        return (result, result["request_count"], to_json(result))


class CDTraceEvent:
    DESCRIPTION = "创建或追加带时间、级别和指纹的运行追踪事件。"
    SEARCH_ALIASES = ["运行追踪", "trace log"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"run_id": ("STRING", {"default": "run-001"}), "event_type": ("STRING", {"default": "task.started"}), "level": (["debug", "info", "warning", "error"],), "payload_json": _multiline("{}")}, "optional": {"trace_log": ("TRACE_LOG",)}}

    RETURN_TYPES = ("TRACE_LOG", "STRING", "INT")
    RETURN_NAMES = ("trace_log", "trace_json", "event_count")
    FUNCTION = "append"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def append(self, run_id, event_type, level, payload_json, trace_log=None):
        log = trace_log or create_trace_log(run_id)
        result = append_trace_event(log, event_type, payload_json, level=level)
        return (result, to_json(result), result["event_count"])


class CDTraceSummary:
    DESCRIPTION = "汇总运行事件、错误数量和端到端耗时。"
    SEARCH_ALIASES = ["追踪汇总", "trace summary"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"trace_log": ("TRACE_LOG",)}}

    RETURN_TYPES = ("BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("has_errors", "duration_ms", "summary_json")
    FUNCTION = "summarize"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def summarize(self, trace_log):
        result = summarize_trace_log(trace_log)
        return (result["has_errors"], result["duration_ms"], to_json(result))


class CDRunBundlePackage:
    DESCRIPTION = "打包可恢复运行快照、队列、质量门槛、素材索引和追踪日志。"
    SEARCH_ALIASES = ["运行包", "package run"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"run_snapshot": ("RUN_SNAPSHOT",), "queue_state": ("PERSISTENT_QUEUE",), "filename_prefix": ("STRING", {"default": "continuity/run-bundle"}), "overwrite": ("BOOLEAN", {"default": False})}, "optional": {"quality_gate": ("QUALITY_GATE",), "asset_index": ("ASSET_INDEX",), "trace_log": ("TRACE_LOG",)}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    FUNCTION = "package"
    CATEGORY = f"{CATEGORY}/04 Export"
    OUTPUT_NODE = True

    def package(self, run_snapshot, queue_state, filename_prefix, overwrite, quality_gate=None, asset_index=None, trace_log=None):
        try:
            import folder_paths  # type: ignore
            output_dir = Path(folder_paths.get_output_directory())
        except Exception:
            output_dir = Path.cwd() / "output"
        prefix = Path(filename_prefix)
        safe_parent = Path(*[slugify(part, "continuity") for part in prefix.parts[:-1]]) if len(prefix.parts) > 1 else Path()
        safe_name = slugify(prefix.name, "run-bundle")
        target = output_dir / safe_parent / f"{safe_name}.zip"
        saved = package_run_bundle(target, run_snapshot, queue_state, quality_gate, asset_index, trace_log, bool(overwrite))
        return (str(saved),)


class CDRunBundleVerify:
    DESCRIPTION = "验证可恢复运行包的路径安全和 SHA-256 完整性。"
    SEARCH_ALIASES = ["运行包验证", "verify run bundle"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"package_path": ("STRING", {"default": "output/continuity/run-bundle.zip"})}}

    RETURN_TYPES = ("BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("valid", "checked_files", "verification_json")
    FUNCTION = "verify"
    CATEGORY = f"{CATEGORY}/04 Export"

    def verify(self, package_path):
        result = verify_run_bundle(package_path)
        return (result["valid"], result["checked_files"], to_json(result))



class CDMediaProbe:
    DESCRIPTION = "使用本地 ffprobe 读取生成视频的流、时长、帧率、分辨率和编码信息。"
    SEARCH_ALIASES = ["视频探测", "media probe", "ffprobe"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_path": ("STRING", {"default": "output/shot-001.mp4"}), "ffprobe_binary": ("STRING", {"default": "ffprobe"}), "timeout_seconds": ("INT", {"default": 30, "min": 1, "max": 600}), "include_file_hash": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("MEDIA_PROBE", "STRING", "FLOAT", "INT", "INT", "FLOAT")
    RETURN_NAMES = ("media_probe", "probe_json", "duration_seconds", "width", "height", "fps")
    FUNCTION = "probe"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def probe(self, media_path, ffprobe_binary, timeout_seconds, include_file_hash):
        result = probe_media_file(media_path, ffprobe_binary, timeout_seconds, bool(include_file_hash))
        primary = result.get("primary_video") or {}
        return (result, to_json(result), float(result.get("duration_seconds") or 0), int(primary.get("width") or 0), int(primary.get("height") or 0), float(primary.get("fps") or 0))


class CDFrameExtractionPlan:
    DESCRIPTION = "规划首帧、尾帧、均匀采样帧或自定义时间点抽帧。"
    SEARCH_ALIASES = ["抽帧计划", "frame extraction"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_probe": ("MEDIA_PROBE",), "output_subdir": ("STRING", {"default": "continuity/frames"}), "mode": (["boundary", "uniform", "custom"],), "sample_count": ("INT", {"default": 2, "min": 1, "max": 1000}), "custom_timestamps_json": _multiline("[]"), "image_format": (["png", "jpg", "webp"],), "filename_prefix": ("STRING", {"default": "frame"})}}

    RETURN_TYPES = ("FRAME_EXTRACTION_PLAN", "STRING", "INT")
    RETURN_NAMES = ("extraction_plan", "plan_json", "frame_count")
    FUNCTION = "plan"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def plan(self, media_probe, output_subdir, mode, sample_count, custom_timestamps_json, image_format, filename_prefix):
        try:
            import folder_paths  # type: ignore
            root = Path(folder_paths.get_output_directory())
        except Exception:
            root = Path.cwd() / "output"
        parts = [slugify(part, "frames") for part in Path(output_subdir).parts if part not in {"", ".", ".."}]
        output_dir = root.joinpath(*parts)
        result = build_frame_extraction_plan(media_probe, output_dir, mode, sample_count, custom_timestamps_json, image_format, filename_prefix)
        return (result, to_json(result), result["frame_count"])


class CDFrameExtractionExecute:
    DESCRIPTION = "按已验证计划调用本地 FFmpeg 抽帧。"
    SEARCH_ALIASES = ["执行抽帧", "extract frames"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"extraction_plan": ("FRAME_EXTRACTION_PLAN",), "ffmpeg_binary": ("STRING", {"default": "ffmpeg"}), "timeout_seconds": ("INT", {"default": 120, "min": 1, "max": 3600}), "overwrite": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("FRAME_EXTRACTION_RESULT", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("extraction_result", "complete", "extracted_count", "result_json")
    FUNCTION = "execute"
    CATEGORY = f"{CATEGORY}/04 Export"
    OUTPUT_NODE = True

    def execute(self, extraction_plan, ffmpeg_binary, timeout_seconds, overwrite):
        result = execute_frame_extraction(extraction_plan, ffmpeg_binary, timeout_seconds, bool(overwrite))
        return (result, result["complete"], result["extracted_count"], to_json(result))


class CDTechnicalQC:
    DESCRIPTION = "根据流信息和可选检测指标检查分辨率、帧率、时长、音轨、黑帧、冻结和解码错误。"
    SEARCH_ALIASES = ["技术质检", "technical qc"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"media_probe": ("MEDIA_PROBE",), "policy_json": _multiline("{}"), "expected_duration_seconds": ("FLOAT", {"default": 0.0, "min": 0.0}), "expected_fps": ("FLOAT", {"default": 0.0, "min": 0.0}), "analysis_metrics_json": _multiline("{}")}}

    RETURN_TYPES = ("TECHNICAL_QC", "BOOLEAN", "FLOAT", "STRING", "STRING")
    RETURN_NAMES = ("technical_qc", "passed", "score", "decision", "report_json")
    FUNCTION = "evaluate"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def evaluate(self, media_probe, policy_json, expected_duration_seconds, expected_fps, analysis_metrics_json):
        result = evaluate_technical_quality(media_probe, policy_json, expected_duration_seconds or None, expected_fps or None, analysis_metrics_json)
        return (result, result["passed"], result["score"], result["decision"], to_json(result))


class CDExternalMetrics:
    DESCRIPTION = "把外部身份、时序、动作或审美模型输出声明式映射到 0-100 分。"
    SEARCH_ALIASES = ["外部指标", "identity metrics adapter"]

    @classmethod
    def INPUT_TYPES(cls):
        default = '{"adapter_id":"face-model","metrics":{"identity_similarity":{"path":"similarity","scale":"0-1"}}}'
        return {"required": {"adapter_json": _multiline(default), "payload_json": _multiline('{"similarity":0.9}')}}

    RETURN_TYPES = ("NORMALIZED_METRICS", "BOOLEAN", "STRING")
    RETURN_NAMES = ("normalized_metrics", "valid", "metrics_json")
    FUNCTION = "normalize"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def normalize(self, adapter_json, payload_json):
        result = normalize_external_metrics(adapter_json, payload_json)
        return (result, result["valid"], to_json(result))


class CDBoundaryContinuity:
    DESCRIPTION = "比较上一镜尾帧和下一镜首帧，输出身份、构图、光线、色彩和运动连续性。"
    SEARCH_ALIASES = ["边界连续性", "shot boundary"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"previous_shot": ("SHOT_MANIFEST",), "next_shot": ("SHOT_MANIFEST",), "previous_frames": ("FRAME_EXTRACTION_RESULT",), "next_frames": ("FRAME_EXTRACTION_RESULT",), "metrics_json": _multiline('{"identity_similarity":90,"composition_match":80,"lighting_match":80,"color_match":80,"motion_continuity":80}'), "thresholds_json": _multiline("{}")}}

    RETURN_TYPES = ("BOUNDARY_REPORT", "BOOLEAN", "FLOAT", "STRING")
    RETURN_NAMES = ("boundary_report", "passed", "overall_score", "report_json")
    FUNCTION = "evaluate"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def evaluate(self, previous_shot, next_shot, previous_frames, next_frames, metrics_json, thresholds_json):
        result = evaluate_boundary_continuity(previous_shot, next_shot, previous_frames, next_frames, metrics_json, thresholds_json)
        return (result, result["passed"], result["overall_score"], to_json(result))


class CDAssemblyPlan:
    DESCRIPTION = "把已选最佳 Take 编译成确定性 FFmpeg 拼接计划。"
    SEARCH_ALIASES = ["拼接计划", "assembly plan", "EDL"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"clips_json": _multiline("[]"), "filename_prefix": ("STRING", {"default": "continuity/final-video"}), "strategy": (["transcode", "copy"],), "video_codec": ("STRING", {"default": "libx264"}), "audio_codec": ("STRING", {"default": "aac"}), "target_fps": ("FLOAT", {"default": 24.0, "min": 0.0, "max": 240.0}), "metadata_json": _multiline("{}")}}

    RETURN_TYPES = ("ASSEMBLY_PLAN", "STRING", "INT")
    RETURN_NAMES = ("assembly_plan", "plan_json", "clip_count")
    FUNCTION = "plan"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def plan(self, clips_json, filename_prefix, strategy, video_codec, audio_codec, target_fps, metadata_json):
        try:
            import folder_paths  # type: ignore
            root = Path(folder_paths.get_output_directory())
        except Exception:
            root = Path.cwd() / "output"
        prefix = Path(filename_prefix)
        safe_parent = Path(*[slugify(part, "continuity") for part in prefix.parts[:-1]]) if len(prefix.parts) > 1 else Path()
        target = root / safe_parent / f"{slugify(prefix.name, 'final-video')}.mp4"
        result = build_sequence_assembly_plan(clips_json, target, strategy, video_codec, audio_codec, target_fps or None, metadata_json)
        return (result, to_json(result), result["clip_count"])


class CDAssemblyExecute:
    DESCRIPTION = "执行拼接计划并自动探测最终视频。"
    SEARCH_ALIASES = ["执行拼接", "assemble video"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"assembly_plan": ("ASSEMBLY_PLAN",), "ffmpeg_binary": ("STRING", {"default": "ffmpeg"}), "timeout_seconds": ("INT", {"default": 1800, "min": 1, "max": 86400}), "overwrite": ("BOOLEAN", {"default": False}), "verify_sources": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("ASSEMBLY_RESULT", "BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("assembly_result", "success", "output_path", "result_json")
    FUNCTION = "execute"
    CATEGORY = f"{CATEGORY}/04 Export"
    OUTPUT_NODE = True

    def execute(self, assembly_plan, ffmpeg_binary, timeout_seconds, overwrite, verify_sources):
        result = execute_sequence_assembly(assembly_plan, ffmpeg_binary, timeout_seconds, bool(overwrite), bool(verify_sources))
        return (result, bool(result.get("success")), str(result.get("output_path", "")), to_json(result))


class CDVersionSnapshot:
    DESCRIPTION = "创建可校验、可比较、可回滚的内容寻址项目快照。"
    SEARCH_ALIASES = ["版本快照", "version snapshot"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"state_json": _multiline("{}"), "label": ("STRING", {"default": "checkpoint"}), "metadata_json": _multiline("{}")}, "optional": {"parent_snapshot": ("VERSION_SNAPSHOT",)}}

    RETURN_TYPES = ("VERSION_SNAPSHOT", "STRING", "STRING")
    RETURN_NAMES = ("version_snapshot", "snapshot_id", "snapshot_json")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def create(self, state_json, label, metadata_json, parent_snapshot=None):
        result = create_version_snapshot(state_json, label, parent_snapshot, metadata_json)
        return (result, result["snapshot_id"], to_json(result))


class CDStructuredDiff:
    DESCRIPTION = "递归比较两个对象或版本快照，标记身份、服装、种子和模型配置等关键变化。"
    SEARCH_ALIASES = ["结构化差异", "manifest diff"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"before_json": _multiline("{}"), "after_json": _multiline("{}"), "ignore_paths_json": _multiline("[]"), "max_changes": ("INT", {"default": 5000, "min": 1, "max": 100000})}}

    RETURN_TYPES = ("STRUCTURED_DIFF", "BOOLEAN", "INT", "INT", "STRING")
    RETURN_NAMES = ("structured_diff", "identical", "change_count", "critical_change_count", "diff_json")
    FUNCTION = "compare"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def compare(self, before_json, after_json, ignore_paths_json, max_changes):
        result = build_structured_diff(before_json, after_json, ignore_paths_json, max_changes)
        return (result, result["identical"], result["change_count"], result["critical_change_count"], to_json(result))


class CDRollbackPlan:
    DESCRIPTION = "基于两个版本快照生成完整或局部回滚计划。"
    SEARCH_ALIASES = ["回滚计划", "rollback plan"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"current_snapshot": ("VERSION_SNAPSHOT",), "target_snapshot": ("VERSION_SNAPSHOT",), "scope_paths_json": _multiline("[]")}}

    RETURN_TYPES = ("ROLLBACK_PLAN", "INT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("rollback_plan", "operation_count", "no_op", "plan_json")
    FUNCTION = "plan"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def plan(self, current_snapshot, target_snapshot, scope_paths_json):
        result = build_rollback_plan(current_snapshot, target_snapshot, scope_paths_json)
        return (result, result["operation_count"], result["no_op"], to_json(result))


class CDRollbackApply:
    DESCRIPTION = "仅在当前状态指纹仍匹配时应用回滚计划。"
    SEARCH_ALIASES = ["应用回滚", "apply rollback"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"current_state_json": _multiline("{}"), "rollback_plan": ("ROLLBACK_PLAN",), "require_fingerprint_match": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("restored_state_json", "success", "result_json")
    FUNCTION = "apply"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def apply(self, current_state_json, rollback_plan, require_fingerprint_match):
        result = apply_rollback_plan(current_state_json, rollback_plan, bool(require_fingerprint_match))
        return (to_json(result["state"]), result["success"], to_json(result))


class CDBatchRerunPlan:
    DESCRIPTION = "只为质检失败、边界失败或手动选择的镜头生成批量重跑任务。"
    SEARCH_ALIASES = ["批量重跑", "batch rerun"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"queue_state": ("PERSISTENT_QUEUE",), "quality_evaluations_json": _multiline("[]"), "boundary_reports_json": _multiline("[]"), "selected_shot_ids_json": _multiline("[]"), "max_tasks": ("INT", {"default": 100, "min": 1, "max": 10000}), "priority_boost": ("INT", {"default": 10, "min": -1000, "max": 1000})}}

    RETURN_TYPES = ("BATCH_RERUN_PLAN", "INT", "STRING")
    RETURN_NAMES = ("rerun_plan", "request_count", "plan_json")
    FUNCTION = "plan"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def plan(self, queue_state, quality_evaluations_json, boundary_reports_json, selected_shot_ids_json, max_tasks, priority_boost):
        result = plan_batch_rerun(queue_state, quality_evaluations_json, boundary_reports_json, selected_shot_ids_json, max_tasks, priority_boost)
        return (result, result["request_count"], to_json(result))


class CDBatchRerunApply:
    DESCRIPTION = "将未过期的批量重跑计划原子追加到持久化队列。"
    SEARCH_ALIASES = ["应用重跑", "apply rerun"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"queue_state": ("PERSISTENT_QUEUE",), "rerun_plan": ("BATCH_RERUN_PLAN",)}}

    RETURN_TYPES = ("PERSISTENT_QUEUE", "INT", "STRING")
    RETURN_NAMES = ("queue_state", "added_count", "result_json")
    FUNCTION = "apply"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def apply(self, queue_state, rerun_plan):
        result = apply_batch_rerun_plan(queue_state, rerun_plan)
        return (result["queue_state"], result["added_count"], to_json(result))


class CDResourceQuota:
    DESCRIPTION = "定义任务数、并发量、GPU秒数、预算、存储和重做次数上限。"
    SEARCH_ALIASES = ["资源配额", "resource quota"]

    @classmethod
    def INPUT_TYPES(cls):
        default = '{"quota_id":"default","limits":{"tasks":100,"concurrent_tasks":2,"gpu_seconds":3600,"estimated_cost":20,"storage_bytes":10737418240,"remakes":20}}'
        return {"required": {"quota_json": _multiline(default)}}

    RETURN_TYPES = ("RESOURCE_QUOTA", "STRING")
    RETURN_NAMES = ("resource_quota", "quota_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/01 Locks"

    def build(self, quota_json):
        result = build_resource_quota(quota_json)
        return (result, to_json(result))


class CDQuotaEvaluate:
    DESCRIPTION = "检查一批任务是否会超过资源配额。"
    SEARCH_ALIASES = ["配额评估", "quota evaluate"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"resource_quota": ("RESOURCE_QUOTA",), "requested_json": _multiline('{"tasks":1,"concurrent_tasks":1,"gpu_seconds":30,"estimated_cost":0,"storage_bytes":0,"remakes":0}')}}

    RETURN_TYPES = ("QUOTA_EVALUATION", "BOOLEAN", "STRING")
    RETURN_NAMES = ("quota_evaluation", "allowed", "evaluation_json")
    FUNCTION = "evaluate"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def evaluate(self, resource_quota, requested_json):
        result = evaluate_resource_quota(resource_quota, requested_json)
        return (result, result["allowed"], to_json(result))


class CDQuotaReserve:
    DESCRIPTION = "在配额评估仍有效时登记资源预留。"
    SEARCH_ALIASES = ["配额预留", "reserve quota"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"resource_quota": ("RESOURCE_QUOTA",), "quota_evaluation": ("QUOTA_EVALUATION",), "reservation_id": ("STRING", {"default": "batch-001"}), "metadata_json": _multiline("{}")}}

    RETURN_TYPES = ("RESOURCE_QUOTA", "STRING")
    RETURN_NAMES = ("resource_quota", "quota_json")
    FUNCTION = "reserve"
    CATEGORY = f"{CATEGORY}/02 Direct"

    def reserve(self, resource_quota, quota_evaluation, reservation_id, metadata_json):
        result = reserve_resource_quota(resource_quota, quota_evaluation, reservation_id, metadata_json)
        return (result, to_json(result))


class CDObservabilityMetrics:
    DESCRIPTION = "汇总队列、追踪、素材和质检指标，并生成 Prometheus 文本。"
    SEARCH_ALIASES = ["可观测指标", "prometheus metrics"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"namespace": ("STRING", {"default": "continuity_director"}), "qc_reports_json": _multiline("[]")}, "optional": {"queue_state": ("PERSISTENT_QUEUE",), "trace_summary_json": ("STRING", {"default": "{}", "multiline": True}), "asset_index": ("ASSET_INDEX",)}}

    RETURN_TYPES = ("OBSERVABILITY_METRICS", "STRING", "STRING")
    RETURN_NAMES = ("metrics", "prometheus_text", "metrics_json")
    FUNCTION = "collect"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def collect(self, namespace, qc_reports_json, queue_state=None, trace_summary_json=None, asset_index=None):
        trace = trace_summary_json if trace_summary_json and trace_summary_json.strip() not in {"", "{}"} else None
        result = collect_observability_metrics(queue_state, trace, asset_index, qc_reports_json, namespace)
        return (result, result["prometheus_text"], to_json(result))


class CDSystemHealth:
    DESCRIPTION = "检查过期租约、停滞任务、追踪错误、配额压力和质检失败。"
    SEARCH_ALIASES = ["系统健康", "health report"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"quality_reports_json": _multiline("[]"), "stalled_task_seconds": ("INT", {"default": 900, "min": 1, "max": 86400})}, "optional": {"queue_state": ("PERSISTENT_QUEUE",), "trace_summary_json": ("STRING", {"default": "{}", "multiline": True}), "resource_quota": ("RESOURCE_QUOTA",)}}

    RETURN_TYPES = ("SYSTEM_HEALTH", "STRING", "INT", "STRING")
    RETURN_NAMES = ("health_report", "status", "score", "report_json")
    FUNCTION = "check"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def check(self, quality_reports_json, stalled_task_seconds, queue_state=None, trace_summary_json=None, resource_quota=None):
        trace = trace_summary_json if trace_summary_json and trace_summary_json.strip() not in {"", "{}"} else None
        result = build_system_health_report(queue_state, trace, resource_quota, quality_reports_json, stalled_task_seconds=stalled_task_seconds)
        return (result, result["status"], result["score"], to_json(result))


class CDRegressionBaseline:
    DESCRIPTION = "保存可复现输出指纹和指标，作为插件升级后的回归基线。"
    SEARCH_ALIASES = ["回归基线", "regression baseline"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"results_json": _multiline("[]"), "suite_id": ("STRING", {"default": "default-suite"}), "metadata_json": _multiline("{}")}}

    RETURN_TYPES = ("REGRESSION_BASELINE", "STRING", "INT")
    RETURN_NAMES = ("regression_baseline", "baseline_json", "case_count")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def create(self, results_json, suite_id, metadata_json):
        result = create_regression_baseline(results_json, suite_id, metadata_json)
        return (result, to_json(result), result["case_count"])


class CDRegressionCompare:
    DESCRIPTION = "比较当前结果与回归基线，检测输出指纹和指标漂移。"
    SEARCH_ALIASES = ["回归比较", "regression compare"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"regression_baseline": ("REGRESSION_BASELINE",), "current_results_json": _multiline("[]"), "metric_tolerances_json": _multiline("{}"), "allow_output_change": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("REGRESSION_COMPARISON", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("regression_comparison", "passed", "failure_count", "comparison_json")
    FUNCTION = "compare"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def compare(self, regression_baseline, current_results_json, metric_tolerances_json, allow_output_change):
        result = compare_regression_results(regression_baseline, current_results_json, metric_tolerances_json, bool(allow_output_change))
        return (result, result["passed"], result["failure_count"], to_json(result))


class CDConfigBundlePackage:
    DESCRIPTION = "导出无密钥、带 SHA-256 的模型配置、工作流模板和质量门槛包。"
    SEARCH_ALIASES = ["配置包导出", "config bundle export"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"configurations_json": _multiline("{}"), "filename_prefix": ("STRING", {"default": "continuity/config-bundle"}), "overwrite": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("saved_path",)
    FUNCTION = "package"
    CATEGORY = f"{CATEGORY}/04 Export"
    OUTPUT_NODE = True

    def package(self, configurations_json, filename_prefix, overwrite):
        try:
            import folder_paths  # type: ignore
            root = Path(folder_paths.get_output_directory())
        except Exception:
            root = Path.cwd() / "output"
        prefix = Path(filename_prefix)
        safe_parent = Path(*[slugify(part, "continuity") for part in prefix.parts[:-1]]) if len(prefix.parts) > 1 else Path()
        target = root / safe_parent / f"{slugify(prefix.name, 'config-bundle')}.zip"
        return (str(package_configuration_bundle(target, configurations_json, bool(overwrite))),)


class CDConfigBundleLoad:
    DESCRIPTION = "校验并读取配置包，不执行其中任何代码。"
    SEARCH_ALIASES = ["配置包导入", "config bundle load"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"package_path": ("STRING", {"default": "output/continuity/config-bundle.zip"})}}

    RETURN_TYPES = ("BOOLEAN", "STRING", "INT")
    RETURN_NAMES = ("valid", "configurations_json", "configuration_count")
    FUNCTION = "load"
    CATEGORY = f"{CATEGORY}/04 Export"

    def load(self, package_path):
        result = load_configuration_bundle(package_path)
        return (result["valid"], to_json(result["configurations"]), result.get("configuration_count", 0))


class CDLineageGraph:
    DESCRIPTION = "建立提示词、参考帧、视频、重做结果与最终成片的产物血缘 DAG。"
    SEARCH_ALIASES = ["产物血缘", "artifact lineage"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"records_json": _multiline("[]")}}

    RETURN_TYPES = ("LINEAGE_GRAPH", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("lineage_graph", "valid", "node_count", "graph_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def build(self, records_json):
        result = build_artifact_lineage(records_json)
        return (result, result["valid"], result["node_count"], to_json(result))


class CDLineageTrace:
    DESCRIPTION = "追踪一个产物的全部上游来源和下游派生结果。"
    SEARCH_ALIASES = ["血缘追踪", "trace lineage"]

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"lineage_graph": ("LINEAGE_GRAPH",), "artifact_id": ("STRING", {"default": "final-video"})}}

    RETURN_TYPES = ("LINEAGE_TRACE", "INT", "INT", "STRING")
    RETURN_NAMES = ("lineage_trace", "ancestor_count", "descendant_count", "trace_json")
    FUNCTION = "trace"
    CATEGORY = f"{CATEGORY}/03 Audit"

    def trace(self, lineage_graph, artifact_id):
        result = trace_artifact_lineage(lineage_graph, artifact_id)
        return (result, result["ancestor_count"], result["descendant_count"], to_json(result))



class CDCollaborationManifest:
    DESCRIPTION = "创建带角色权限和审批策略的多人协作项目。"
    SEARCH_ALIASES = ["协作项目", "collaboration manifest"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_id": ("STRING", {"default": "my-project"}), "members_json": _multiline('[{"member_id":"owner","role":"owner"},{"member_id":"editor","role":"editor"}]'), "created_by": ("STRING", {"default": "owner"}), "policy_json": _multiline("{}")}}
    RETURN_TYPES = ("COLLABORATION_MANIFEST", "STRING", "INT")
    RETURN_NAMES = ("collaboration", "collaboration_json", "member_count")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/01 Locks"
    def create(self, project_id, members_json, created_by, policy_json):
        result = create_collaboration_manifest(project_id, members_json, created_by, policy_json)
        return (result, to_json(result), result["member_count"])


class CDEditLockAcquire:
    DESCRIPTION = "按资源获取或续期带修订号的编辑租约。"
    SEARCH_ALIASES = ["编辑锁", "acquire edit lock"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "lock_state_json": _multiline('{}'), "member_id": ("STRING", {"default": "editor"}), "resource_type": ("STRING", {"default": "shot"}), "resource_id": ("STRING", {"default": "shot-001"}), "ttl_seconds": ("INT", {"default": 900, "min": 30, "max": 86400}), "expected_revision": ("INT", {"default": -1, "min": -1})}}
    RETURN_TYPES = ("EDIT_LOCK_STATE", "STRING", "INT")
    RETURN_NAMES = ("lock_state", "lock_state_json", "revision")
    FUNCTION = "acquire"
    CATEGORY = f"{CATEGORY}/01 Locks"
    def acquire(self, collaboration, lock_state_json, member_id, resource_type, resource_id, ttl_seconds, expected_revision):
        state = json.loads(lock_state_json) if lock_state_json.strip() and lock_state_json.strip() != '{}' else None
        result = acquire_edit_lock(collaboration, state, member_id, resource_type, resource_id, ttl_seconds, None if expected_revision < 0 else expected_revision)
        return (result, to_json(result), result["revision"])


class CDEditLockRelease:
    DESCRIPTION = "释放自己的编辑锁；owner 可强制释放。"
    SEARCH_ALIASES = ["释放编辑锁", "release edit lock"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "lock_state": ("EDIT_LOCK_STATE",), "member_id": ("STRING", {"default": "editor"}), "resource_type": ("STRING", {"default": "shot"}), "resource_id": ("STRING", {"default": "shot-001"}), "lease_token": ("STRING", {"default": ""}), "force": ("BOOLEAN", {"default": False})}}
    RETURN_TYPES = ("EDIT_LOCK_STATE", "STRING", "INT")
    RETURN_NAMES = ("lock_state", "lock_state_json", "revision")
    FUNCTION = "release"
    CATEGORY = f"{CATEGORY}/01 Locks"
    def release(self, collaboration, lock_state, member_id, resource_type, resource_id, lease_token, force):
        result = release_edit_lock(collaboration, lock_state, member_id, resource_type, resource_id, lease_token, bool(force))
        return (result, to_json(result), result["revision"])


class CDApprovalCreate:
    DESCRIPTION = "为镜头、场景或成片创建审批记录。"
    SEARCH_ALIASES = ["创建审批", "approval create"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "resource_type": ("STRING", {"default": "shot"}), "resource_id": ("STRING", {"default": "shot-001"}), "author_id": ("STRING", {"default": "editor"}), "content_fingerprint": ("STRING", {"default": ""}), "title": ("STRING", {"default": "镜头审批"})}}
    RETURN_TYPES = ("APPROVAL_RECORD", "STRING")
    RETURN_NAMES = ("approval_record", "approval_json")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def create(self, collaboration, resource_type, resource_id, author_id, content_fingerprint, title):
        result = create_approval_record(collaboration, resource_type, resource_id, author_id, content_fingerprint, title)
        return (result, to_json(result))


class CDApprovalTransition:
    DESCRIPTION = "提交、要求修改、批准、拒绝或废止审批记录。"
    SEARCH_ALIASES = ["审批流转", "approval transition"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "approval_record": ("APPROVAL_RECORD",), "actor_id": ("STRING", {"default": "owner"}), "action": (["submit", "resubmit", "approve", "request_changes", "reject", "revise", "supersede"],), "comment": _multiline(""), "expected_revision": ("INT", {"default": -1, "min": -1})}}
    RETURN_TYPES = ("APPROVAL_RECORD", "STRING", "STRING")
    RETURN_NAMES = ("approval_record", "approval_json", "state")
    FUNCTION = "transition"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def transition(self, collaboration, approval_record, actor_id, action, comment, expected_revision):
        result = transition_approval(collaboration, approval_record, actor_id, action, comment, None if expected_revision < 0 else expected_revision)
        return (result, to_json(result), result["state"])


class CDChangeRequestCreate:
    DESCRIPTION = "针对结构化资源创建可评审变更请求。"
    SEARCH_ALIASES = ["变更请求", "change request"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "requester_id": ("STRING", {"default": "editor"}), "target_resource_json": _multiline("{}"), "proposed_patch_json": _multiline("{}"), "summary": _multiline(""), "reviewers_json": _multiline("[]")}}
    RETURN_TYPES = ("CHANGE_REQUEST", "STRING")
    RETURN_NAMES = ("change_request", "change_request_json")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def create(self, collaboration, requester_id, target_resource_json, proposed_patch_json, summary, reviewers_json):
        result = create_change_request(collaboration, requester_id, target_resource_json, proposed_patch_json, summary, reviewers_json)
        return (result, to_json(result))


class CDChangeRequestReview:
    DESCRIPTION = "批准、拒绝或要求修改一个变更请求。"
    SEARCH_ALIASES = ["评审变更", "review change request"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "change_request": ("CHANGE_REQUEST",), "reviewer_id": ("STRING", {"default": "owner"}), "decision": (["approve", "request_changes", "reject"],), "comment": _multiline(""), "expected_revision": ("INT", {"default": -1, "min": -1})}}
    RETURN_TYPES = ("CHANGE_REQUEST", "STRING", "STRING")
    RETURN_NAMES = ("change_request", "change_request_json", "status")
    FUNCTION = "review"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def review(self, collaboration, change_request, reviewer_id, decision, comment, expected_revision):
        result = review_change_request(collaboration, change_request, reviewer_id, decision, comment, None if expected_revision < 0 else expected_revision)
        return (result, to_json(result), result["status"])


class CDAuditAppend:
    DESCRIPTION = "向不可篡改的协作审计哈希链追加事件。"
    SEARCH_ALIASES = ["审计事件", "audit append"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audit_log_json": _multiline("{}"), "project_id": ("STRING", {"default": "my-project"}), "actor_id": ("STRING", {"default": "owner"}), "event_type": ("STRING", {"default": "shot-updated"}), "payload_json": _multiline("{}")}}
    RETURN_TYPES = ("COLLAB_AUDIT_LOG", "STRING", "INT")
    RETURN_NAMES = ("audit_log", "audit_log_json", "event_count")
    FUNCTION = "append"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def append(self, audit_log_json, project_id, actor_id, event_type, payload_json):
        log = json.loads(audit_log_json) if audit_log_json.strip() and audit_log_json.strip() != '{}' else None
        result = append_audit_event(log, project_id, actor_id, event_type, payload_json)
        return (result, to_json(result), result["event_count"])


class CDAuditVerify:
    DESCRIPTION = "验证协作审计链的序号、前序哈希和事件哈希。"
    SEARCH_ALIASES = ["审计验证", "audit verify"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audit_log": ("COLLAB_AUDIT_LOG",)}}
    RETURN_TYPES = ("AUDIT_VERIFICATION", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("verification", "valid", "issue_count", "verification_json")
    FUNCTION = "verify"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def verify(self, audit_log):
        result = verify_audit_log(audit_log)
        return (result, result["valid"], result["issue_count"], to_json(result))


class CDThreeWayMerge:
    DESCRIPTION = "对基础版、我的修改和对方修改执行结构化三方合并。"
    SEARCH_ALIASES = ["三方合并", "three way merge"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"base_json": _multiline("{}"), "ours_json": _multiline("{}"), "theirs_json": _multiline("{}"), "conflict_strategy": (["manual", "ours", "theirs"],)}}
    RETURN_TYPES = ("THREE_WAY_MERGE", "STRING", "BOOLEAN", "INT")
    RETURN_NAMES = ("merge_report", "merged_json", "clean", "conflict_count")
    FUNCTION = "merge"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def merge(self, base_json, ours_json, theirs_json, conflict_strategy):
        result = three_way_merge(base_json, ours_json, theirs_json, conflict_strategy)
        return (result, to_json(result["merged"]), result["clean"], result["conflict_count"])


class CDWorkerRegister:
    DESCRIPTION = "注册或更新一个带能力与容量声明的生成工作节点。"
    SEARCH_ALIASES = ["工作节点注册", "worker register"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"worker_registry_json": _multiline("{}"), "worker_id": ("STRING", {"default": "worker-01"}), "capabilities_json": _multiline('{"model_profiles":["default"],"vram_gb":24}'), "labels_json": _multiline("{}"), "capacity": ("INT", {"default": 1, "min": 1, "max": 128})}}
    RETURN_TYPES = ("WORKER_REGISTRY", "STRING", "INT")
    RETURN_NAMES = ("worker_registry", "registry_json", "worker_count")
    FUNCTION = "register"
    CATEGORY = f"{CATEGORY}/02 Runtime"
    def register(self, worker_registry_json, worker_id, capabilities_json, labels_json, capacity):
        registry = json.loads(worker_registry_json) if worker_registry_json.strip() and worker_registry_json.strip() != '{}' else None
        result = register_worker(registry, worker_id, capabilities_json, labels_json, capacity)
        return (result, to_json(result), result["worker_count"])


class CDWorkerHeartbeat:
    DESCRIPTION = "更新工作节点心跳、状态、活动任务数和指标。"
    SEARCH_ALIASES = ["工作节点心跳", "worker heartbeat"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"worker_registry": ("WORKER_REGISTRY",), "worker_id": ("STRING", {"default": "worker-01"}), "state": (["online", "busy", "draining", "offline"],), "active_tasks": ("INT", {"default": 0, "min": 0}), "metrics_json": _multiline("{}")}}
    RETURN_TYPES = ("WORKER_REGISTRY", "STRING")
    RETURN_NAMES = ("worker_registry", "registry_json")
    FUNCTION = "heartbeat"
    CATEGORY = f"{CATEGORY}/02 Runtime"
    def heartbeat(self, worker_registry, worker_id, state, active_tasks, metrics_json):
        result = update_worker_heartbeat(worker_registry, worker_id, state, active_tasks, metrics_json)
        return (result, to_json(result))


class CDWorkerHealth:
    DESCRIPTION = "识别超过心跳阈值的失联工作节点。"
    SEARCH_ALIASES = ["工作节点健康", "worker health"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"worker_registry": ("WORKER_REGISTRY",), "stale_after_seconds": ("INT", {"default": 120, "min": 10})}}
    RETURN_TYPES = ("WORKER_REGISTRY_HEALTH", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("worker_health", "healthy", "stale_count", "health_json")
    FUNCTION = "check"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def check(self, worker_registry, stale_after_seconds):
        result = detect_stale_workers(worker_registry, stale_after_seconds)
        return (result, result["healthy"], result["stale_worker_count"], to_json(result))


class CDDistributedSchedule:
    DESCRIPTION = "按模型、传输方式、显存、标签和容量分配队列任务。"
    SEARCH_ALIASES = ["分布式调度", "distributed schedule"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"generation_queue": ("GENERATION_QUEUE",), "worker_registry": ("WORKER_REGISTRY",), "max_assignments": ("INT", {"default": 100, "min": 1, "max": 10000})}}
    RETURN_TYPES = ("DISTRIBUTED_SCHEDULE", "STRING", "INT", "INT")
    RETURN_NAMES = ("schedule", "schedule_json", "assignment_count", "blocked_count")
    FUNCTION = "schedule"
    CATEGORY = f"{CATEGORY}/02 Runtime"
    def schedule(self, generation_queue, worker_registry, max_assignments):
        result = schedule_distributed_tasks(generation_queue, worker_registry, max_assignments)
        return (result, to_json(result), result["assignment_count"], result["blocked_count"])


class CDCompatibilityMatrix:
    DESCRIPTION = "批量检查 Python、ComfyUI、插件、模型、FFmpeg 和显存兼容性。"
    SEARCH_ALIASES = ["兼容矩阵", "compatibility matrix"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"environments_json": _multiline("[]"), "requirements_json": _multiline("{}")}}
    RETURN_TYPES = ("COMPATIBILITY_MATRIX", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("compatibility_matrix", "all_compatible", "compatible_count", "matrix_json")
    FUNCTION = "evaluate"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def evaluate(self, environments_json, requirements_json):
        result = build_compatibility_matrix(environments_json, requirements_json)
        return (result, result["all_compatible"], result["compatible_count"], to_json(result))


class CDEnvironmentLockfile:
    DESCRIPTION = "冻结可复现的 Python、ComfyUI、插件、模型和硬件环境。"
    SEARCH_ALIASES = ["环境锁文件", "environment lockfile"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"environment_json": _multiline("{}"), "project_id": ("STRING", {"default": "my-project"}), "generated_by": ("STRING", {"default": "owner"})}}
    RETURN_TYPES = ("ENVIRONMENT_LOCKFILE", "STRING")
    RETURN_NAMES = ("environment_lockfile", "lockfile_json")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/02 Runtime"
    def create(self, environment_json, project_id, generated_by):
        result = create_environment_lockfile(environment_json, project_id, generated_by)
        return (result, to_json(result))


class CDBulkImport:
    DESCRIPTION = "安全导入 CSV 或 JSONL 镜头与任务记录，并返回逐行错误。"
    SEARCH_ALIASES = ["批量导入", "bulk import"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"payload": _multiline(""), "input_format": (["jsonl", "csv"],), "required_fields_json": _multiline("[]"), "id_field": ("STRING", {"default": "shot_id"}), "max_records": ("INT", {"default": 10000, "min": 1, "max": 100000})}}
    RETURN_TYPES = ("BULK_IMPORT_RESULT", "STRING", "INT", "INT")
    RETURN_NAMES = ("import_result", "records_json", "valid_count", "error_count")
    FUNCTION = "load"
    CATEGORY = f"{CATEGORY}/00 Quick Start"
    def load(self, payload, input_format, required_fields_json, id_field, max_records):
        result = import_bulk_records(payload, input_format, required_fields_json, id_field, max_records)
        return (result, json.dumps(result["records"], ensure_ascii=False, indent=2), result["valid_count"], result["error_count"])


class CDTemplateManifestValidate:
    DESCRIPTION = "校验可共享模板包的版本、许可证、入口、文件路径和 SHA-256。"
    SEARCH_ALIASES = ["模板包校验", "template manifest validate"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template_manifest_json": _multiline("{}")}}
    RETURN_TYPES = ("TEMPLATE_VALIDATION", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("template_validation", "valid", "issue_count", "validation_json")
    FUNCTION = "validate"
    CATEGORY = f"{CATEGORY}/04 Export"
    def validate(self, template_manifest_json):
        result = validate_template_manifest(template_manifest_json)
        return (result, result["valid"], result["issue_count"], to_json(result))


class CDTemplateTrust:
    DESCRIPTION = "按发布者允许列表和固定摘要判断模板包是否可信。"
    SEARCH_ALIASES = ["模板信任", "template trust"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template_validation": ("TEMPLATE_VALIDATION",), "publisher_id": ("STRING", {"default": "publisher"}), "publisher_digest": ("STRING", {"default": ""}), "trust_policy_json": _multiline('{"require_digest":true,"allowed_publishers":[]}')}}
    RETURN_TYPES = ("TEMPLATE_TRUST_REPORT", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("trust_report", "trusted", "issue_count", "trust_json")
    FUNCTION = "verify"
    CATEGORY = f"{CATEGORY}/04 Export"
    def verify(self, template_validation, publisher_id, publisher_digest, trust_policy_json):
        result = verify_template_trust(template_validation, publisher_id, publisher_digest, trust_policy_json)
        return (result, result["trusted"], result["issue_count"], to_json(result))


class CDFaultInjectionPlan:
    DESCRIPTION = "以确定性 dry-run 方式规划超时、失联、限流、显存不足等故障。"
    SEARCH_ALIASES = ["故障注入", "fault injection"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"generation_queue": ("GENERATION_QUEUE",), "scenarios_json": _multiline("[]"), "master_seed": ("INT", {"default": 0, "min": 0, "max": 2**63 - 1})}}
    RETURN_TYPES = ("FAULT_INJECTION_PLAN", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("fault_plan", "valid", "triggered_count", "plan_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def build(self, generation_queue, scenarios_json, master_seed):
        result = build_fault_injection_plan(generation_queue, scenarios_json, master_seed)
        return (result, result["valid"], result["triggered_count"], to_json(result))


class CDFaultRecoveryEvaluate:
    DESCRIPTION = "核对触发故障是否执行了预期恢复动作。"
    SEARCH_ALIASES = ["故障恢复评估", "fault recovery"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"fault_plan": ("FAULT_INJECTION_PLAN",), "observed_events_json": _multiline("[]")}}
    RETURN_TYPES = ("FAULT_RECOVERY_REPORT", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("recovery_report", "passed", "failure_count", "report_json")
    FUNCTION = "evaluate"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def evaluate(self, fault_plan, observed_events_json):
        result = evaluate_fault_recovery(fault_plan, observed_events_json)
        return (result, result["passed"], result["failure_count"], to_json(result))


class CDReplayManifest:
    DESCRIPTION = "固定运行快照、任务种子和输出指纹，生成可复现重放清单。"
    SEARCH_ALIASES = ["重放清单", "replay manifest"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"run_snapshot": ("RUN_SNAPSHOT",), "generation_queue": ("GENERATION_QUEUE",), "outputs_json": _multiline("[]")}}
    RETURN_TYPES = ("REPLAY_MANIFEST", "STRING", "STRING")
    RETURN_NAMES = ("replay_manifest", "replay_json", "replay_fingerprint")
    FUNCTION = "create"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def create(self, run_snapshot, generation_queue, outputs_json):
        result = build_replay_manifest(run_snapshot, generation_queue, outputs_json)
        return (result, to_json(result), result["replay_fingerprint"])


class CDReplayCompare:
    DESCRIPTION = "比较两次运行的快照、任务、种子和输出指纹是否完全一致。"
    SEARCH_ALIASES = ["重放比较", "replay compare"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"expected": ("REPLAY_MANIFEST",), "actual": ("REPLAY_MANIFEST",)}}
    RETURN_TYPES = ("REPLAY_COMPARISON", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("replay_comparison", "deterministic", "difference_count", "comparison_json")
    FUNCTION = "compare"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def compare(self, expected, actual):
        result = compare_replay_manifests(expected, actual)
        return (result, result["deterministic"], result["difference_count"], to_json(result))


class CDGenerationReleaseGate:
    DESCRIPTION = "综合审批、编辑锁、兼容环境和审计链决定是否允许进入生成。"
    SEARCH_ALIASES = ["生成放行", "generation release gate"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "approval_records_json": _multiline("[]"), "required_resource_ids_json": _multiline("[]")}, "optional": {"lock_state": ("EDIT_LOCK_STATE",), "compatibility_matrix": ("COMPATIBILITY_MATRIX",), "audit_verification": ("AUDIT_VERIFICATION",)}}
    RETURN_TYPES = ("GENERATION_RELEASE_GATE", "BOOLEAN", "INT", "STRING")
    RETURN_NAMES = ("release_gate", "ready", "score", "gate_json")
    FUNCTION = "evaluate"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def evaluate(self, collaboration, approval_records_json, required_resource_ids_json, lock_state=None, compatibility_matrix=None, audit_verification=None):
        result = evaluate_generation_gate(collaboration, approval_records_json, lock_state, compatibility_matrix, audit_verification, required_resource_ids_json)
        return (result, result["ready"], result["score"], to_json(result))


class CDCollaborationDashboard:
    DESCRIPTION = "汇总成员、编辑锁、审批、变更请求、工作节点和生成放行状态。"
    SEARCH_ALIASES = ["协作看板", "collaboration dashboard"]
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"collaboration": ("COLLABORATION_MANIFEST",), "approval_records_json": _multiline("[]"), "change_requests_json": _multiline("[]")}, "optional": {"lock_state": ("EDIT_LOCK_STATE",), "worker_registry": ("WORKER_REGISTRY",), "generation_gate": ("GENERATION_RELEASE_GATE",)}}
    RETURN_TYPES = ("COLLABORATION_DASHBOARD", "INT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("dashboard", "attention_count", "generation_ready", "dashboard_json")
    FUNCTION = "build"
    CATEGORY = f"{CATEGORY}/03 Audit"
    def build(self, collaboration, approval_records_json, change_requests_json, lock_state=None, worker_registry=None, generation_gate=None):
        result = build_collaboration_dashboard(collaboration, lock_state, approval_records_json, change_requests_json, worker_registry, generation_gate)
        return (result, result["attention_count"], result["generation_ready"], to_json(result))

NODE_CLASS_MAPPINGS = {
    "CDCollaborationManifest": CDCollaborationManifest,
    "CDEditLockAcquire": CDEditLockAcquire,
    "CDEditLockRelease": CDEditLockRelease,
    "CDApprovalCreate": CDApprovalCreate,
    "CDApprovalTransition": CDApprovalTransition,
    "CDChangeRequestCreate": CDChangeRequestCreate,
    "CDChangeRequestReview": CDChangeRequestReview,
    "CDAuditAppend": CDAuditAppend,
    "CDAuditVerify": CDAuditVerify,
    "CDThreeWayMerge": CDThreeWayMerge,
    "CDWorkerRegister": CDWorkerRegister,
    "CDWorkerHeartbeat": CDWorkerHeartbeat,
    "CDWorkerHealth": CDWorkerHealth,
    "CDDistributedSchedule": CDDistributedSchedule,
    "CDCompatibilityMatrix": CDCompatibilityMatrix,
    "CDEnvironmentLockfile": CDEnvironmentLockfile,
    "CDBulkImport": CDBulkImport,
    "CDTemplateManifestValidate": CDTemplateManifestValidate,
    "CDTemplateTrust": CDTemplateTrust,
    "CDFaultInjectionPlan": CDFaultInjectionPlan,
    "CDFaultRecoveryEvaluate": CDFaultRecoveryEvaluate,
    "CDReplayManifest": CDReplayManifest,
    "CDReplayCompare": CDReplayCompare,
    "CDGenerationReleaseGate": CDGenerationReleaseGate,
    "CDCollaborationDashboard": CDCollaborationDashboard,
    "CDMediaProbe": CDMediaProbe,
    "CDFrameExtractionPlan": CDFrameExtractionPlan,
    "CDFrameExtractionExecute": CDFrameExtractionExecute,
    "CDTechnicalQC": CDTechnicalQC,
    "CDExternalMetrics": CDExternalMetrics,
    "CDBoundaryContinuity": CDBoundaryContinuity,
    "CDAssemblyPlan": CDAssemblyPlan,
    "CDAssemblyExecute": CDAssemblyExecute,
    "CDVersionSnapshot": CDVersionSnapshot,
    "CDStructuredDiff": CDStructuredDiff,
    "CDRollbackPlan": CDRollbackPlan,
    "CDRollbackApply": CDRollbackApply,
    "CDBatchRerunPlan": CDBatchRerunPlan,
    "CDBatchRerunApply": CDBatchRerunApply,
    "CDResourceQuota": CDResourceQuota,
    "CDQuotaEvaluate": CDQuotaEvaluate,
    "CDQuotaReserve": CDQuotaReserve,
    "CDObservabilityMetrics": CDObservabilityMetrics,
    "CDSystemHealth": CDSystemHealth,
    "CDRegressionBaseline": CDRegressionBaseline,
    "CDRegressionCompare": CDRegressionCompare,
    "CDConfigBundlePackage": CDConfigBundlePackage,
    "CDConfigBundleLoad": CDConfigBundleLoad,
    "CDLineageGraph": CDLineageGraph,
    "CDLineageTrace": CDLineageTrace,
    "CDWorkflowTemplate": CDWorkflowTemplate,
    "CDWorkflowBind": CDWorkflowBind,
    "CDRunSnapshot": CDRunSnapshot,
    "CDQueueState": CDQueueState,
    "CDQueueClaim": CDQueueClaim,
    "CDQueueReap": CDQueueReap,
    "CDAssetIndex": CDAssetIndex,
    "CDQualityGate": CDQualityGate,
    "CDQualityEvaluate": CDQualityEvaluate,
    "CDTakeSelection": CDTakeSelection,
    "CDRemakePlan": CDRemakePlan,
    "CDTraceEvent": CDTraceEvent,
    "CDTraceSummary": CDTraceSummary,
    "CDRunBundlePackage": CDRunBundlePackage,
    "CDRunBundleVerify": CDRunBundleVerify,
    "CDReferenceRegistry": CDReferenceRegistry,
    "CDReferenceStatus": CDReferenceStatus,
    "CDPresencePlan": CDPresencePlan,
    "CDSequenceTimeline": CDSequenceTimeline,
    "CDDependencyGraph": CDDependencyGraph,
    "CDRetryPolicy": CDRetryPolicy,
    "CDModelProfile": CDModelProfile,
    "CDReferenceSelector": CDReferenceSelector,
    "CDExecutionPlan": CDExecutionPlan,
    "CDTaskReconcile": CDTaskReconcile,
    "CDFailureClassifier": CDFailureClassifier,
    "CDExecutionDiagnostics": CDExecutionDiagnostics,
    "CDOneClickDirector": CDOneClickDirector,
    "CDProjectLock": CDProjectLock,
    "CDCharacterLock": CDCharacterLock,
    "CDCastLock": CDCastLock,
    "CDSceneLock": CDSceneLock,
    "CDShotDirector": CDShotDirector,
    "CDBatchDirector": CDBatchDirector,
    "CDTakeVariants": CDTakeVariants,
    "CDSequenceAudit": CDSequenceAudit,
    "CDSequenceRepair": CDSequenceRepair,
    "CDProductionReport": CDProductionReport,
    "CDPackageProject": CDPackageProject,
    "CDPackageVerify": CDPackageVerify,
    "CDContinuityAudit": CDContinuityAudit,
    "CDManifestValidator": CDManifestValidator,
    "CDManifestMigrate": CDManifestMigrate,
    "CDProviderExport": CDProviderExport,
    "CDSaveManifest": CDSaveManifest,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CDCollaborationManifest": "①B 协作项目 Collaboration Manifest",
    "CDEditLockAcquire": "①C 获取编辑锁 Acquire Edit Lock",
    "CDEditLockRelease": "①D 释放编辑锁 Release Edit Lock",
    "CDApprovalCreate": "⑤ZD 创建审批 Approval Create",
    "CDApprovalTransition": "⑤ZE 审批流转 Approval Transition",
    "CDChangeRequestCreate": "⑤ZF 变更请求 Change Request",
    "CDChangeRequestReview": "⑤ZG 变更评审 Change Review",
    "CDAuditAppend": "⑤ZH 审计追加 Audit Append",
    "CDAuditVerify": "⑤ZI 审计验证 Audit Verify",
    "CDThreeWayMerge": "⑤ZJ 三方合并 Three-Way Merge",
    "CDWorkerRegister": "④S 工作节点注册 Worker Register",
    "CDWorkerHeartbeat": "④T 工作节点心跳 Worker Heartbeat",
    "CDWorkerHealth": "⑤ZK 工作节点健康 Worker Health",
    "CDDistributedSchedule": "④U 分布式调度 Distributed Schedule",
    "CDCompatibilityMatrix": "⑤ZL 兼容矩阵 Compatibility Matrix",
    "CDEnvironmentLockfile": "③F 环境锁文件 Environment Lockfile",
    "CDBulkImport": "⓪B 批量导入 Bulk Import",
    "CDTemplateManifestValidate": "⑧H 模板包校验 Template Validate",
    "CDTemplateTrust": "⑧I 模板信任 Template Trust",
    "CDFaultInjectionPlan": "⑤ZM 故障注入 Fault Injection",
    "CDFaultRecoveryEvaluate": "⑤ZN 故障恢复 Fault Recovery",
    "CDReplayManifest": "⑤ZO 重放清单 Replay Manifest",
    "CDReplayCompare": "⑤ZP 重放比较 Replay Compare",
    "CDGenerationReleaseGate": "⑤ZQ 生成放行 Generation Gate",
    "CDCollaborationDashboard": "⑤ZR 协作看板 Collaboration Dashboard",
    "CDMediaProbe": "⑤O 视频探测 Media Probe",
    "CDFrameExtractionPlan": "④N 抽帧计划 Frame Extraction Plan",
    "CDFrameExtractionExecute": "⑦C 执行抽帧 Frame Extraction Execute",
    "CDTechnicalQC": "⑤P 技术质检 Technical QC",
    "CDExternalMetrics": "⑤Q 外部指标 External Metrics",
    "CDBoundaryContinuity": "⑤R 边界连续性 Boundary Continuity",
    "CDAssemblyPlan": "④O 拼接计划 Assembly Plan",
    "CDAssemblyExecute": "⑧E 执行拼接 Assembly Execute",
    "CDVersionSnapshot": "⑤S 版本快照 Version Snapshot",
    "CDStructuredDiff": "⑤T 结构化差异 Structured Diff",
    "CDRollbackPlan": "⑤U 回滚计划 Rollback Plan",
    "CDRollbackApply": "⑤V 应用回滚 Rollback Apply",
    "CDBatchRerunPlan": "④P 批量重跑 Batch Rerun Plan",
    "CDBatchRerunApply": "④Q 应用重跑 Batch Rerun Apply",
    "CDResourceQuota": "③E 资源配额 Resource Quota",
    "CDQuotaEvaluate": "⑤W 配额评估 Quota Evaluate",
    "CDQuotaReserve": "④R 配额预留 Quota Reserve",
    "CDObservabilityMetrics": "⑤X 可观测指标 Observability Metrics",
    "CDSystemHealth": "⑤Y 系统健康 System Health",
    "CDRegressionBaseline": "⑤Z 回归基线 Regression Baseline",
    "CDRegressionCompare": "⑤ZA 回归比较 Regression Compare",
    "CDConfigBundlePackage": "⑧F 配置包导出 Config Bundle Export",
    "CDConfigBundleLoad": "⑧G 配置包导入 Config Bundle Load",
    "CDLineageGraph": "⑤ZB 产物血缘 Lineage Graph",
    "CDLineageTrace": "⑤ZC 血缘追踪 Lineage Trace",
    "CDWorkflowTemplate": "③C 工作流模板 Workflow Template",
    "CDWorkflowBind": "④J 工作流绑定 Workflow Bind",
    "CDRunSnapshot": "④K 运行快照 Run Snapshot",
    "CDQueueState": "④L 持久化队列 Queue State",
    "CDQueueClaim": "④M 任务领取 Queue Claim",
    "CDQueueReap": "⑤I 租约回收 Queue Reap",
    "CDAssetIndex": "⑦B 素材索引 Asset Index",
    "CDQualityGate": "③D 质量门槛 Quality Gate",
    "CDQualityEvaluate": "⑤J 质量评估 Quality Evaluate",
    "CDTakeSelection": "⑤K 最佳 Take Take Selection",
    "CDRemakePlan": "⑤L 自动重做 Remake Plan",
    "CDTraceEvent": "⑤M 运行追踪 Trace Event",
    "CDTraceSummary": "⑤N 追踪汇总 Trace Summary",
    "CDRunBundlePackage": "⑧C 运行包 Run Bundle",
    "CDRunBundleVerify": "⑧D 运行包验证 Run Bundle Verify",
    "CDReferenceRegistry": "②C 参考帧库 Reference Registry",
    "CDReferenceStatus": "②D 参考帧状态 Reference Status",
    "CDPresencePlan": "④D 角色出入场 Presence Plan",
    "CDSequenceTimeline": "④E 序列时间线 Sequence Timeline",
    "CDDependencyGraph": "④F 镜头依赖图 Dependency Graph",
    "CDRetryPolicy": "④G 重试策略 Retry Policy",
    "CDModelProfile": "③B 模型配置 Model Profile",
    "CDReferenceSelector": "④H 参考帧选择 Reference Selector",
    "CDExecutionPlan": "④I 执行计划 Execution Plan",
    "CDTaskReconcile": "⑤F 任务回填 Task Reconcile",
    "CDFailureClassifier": "⑤G 错误分类 Failure Classifier",
    "CDExecutionDiagnostics": "⑤H 执行诊断 Execution Diagnostics",
    "CDOneClickDirector": "⓪ 一键导演 One-Click Director",
    "CDProjectLock": "① 项目锁 Project Lock",
    "CDCharacterLock": "② 角色锁 Character Lock",
    "CDCastLock": "②B 演员表锁 Cast Lock",
    "CDSceneLock": "③ 场景锁 Scene Lock",
    "CDShotDirector": "④ 镜头导演 Shot Director",
    "CDBatchDirector": "④B 批量导演 Batch Director",
    "CDTakeVariants": "④C Take 变体 Take Variants",
    "CDSequenceAudit": "⑤A 序列审计 Sequence Audit",
    "CDSequenceRepair": "⑤D 序列修复 Sequence Repair",
    "CDProductionReport": "⑤E 生产报告 Production Report",
    "CDPackageProject": "⑧ 项目打包 Package Project",
    "CDPackageVerify": "⑧B 项目包验证 Package Verify",
    "CDContinuityAudit": "⑤ 连续性审计 Continuity Audit",
    "CDManifestValidator": "⑤B 镜头包校验 Manifest Validator",
    "CDManifestMigrate": "⑤C 旧版迁移 Manifest Migrate",
    "CDProviderExport": "⑥ 平台导出 Provider Export",
    "CDSaveManifest": "⑦ 保存镜头包 Save Manifest",
}
