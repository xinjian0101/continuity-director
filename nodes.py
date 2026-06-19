"""ComfyUI nodes for continuity planning and production governance."""

from __future__ import annotations

import math
import re
from typing import Any

from .collaboration_core import three_way_merge
from .continuity_core import (
    ContinuityError,
    audit_event,
    build_lock,
    build_manifest,
    continuity_diff,
    integrity_report,
    package_payload,
    parse_json,
    split_csv,
    stable_json,
)
from .production_core import expand_storyboard, quality_gate, rank_takes, reference_handoff
from .runtime_core import build_execution_plan

LOCKS = "Continuity Director/01 Locks"
DIRECT = "Continuity Director/02 Directing"
QC = "Continuity Director/03 Quality"
RUNTIME = "Continuity Director/04 Runtime"
COLLAB = "Continuity Director/05 Collaboration"
EXPORT = "Continuity Director/06 Export"


def js(value: Any) -> str:
    return stable_json(value, indent=2)


def _required_text(value: Any, field: str, maximum: int = 10000) -> str:
    if not isinstance(value, str):
        raise ContinuityError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ContinuityError(f"{field} must not be empty")
    if len(text) > maximum:
        raise ContinuityError(f"{field} exceeds {maximum} characters")
    return text


def _optional_text(value: Any, field: str, maximum: int = 10000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ContinuityError(f"{field} must be a string")
    text = value.strip()
    if len(text) > maximum:
        raise ContinuityError(f"{field} exceeds {maximum} characters")
    return text


def _strict_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ContinuityError(f"{field} must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ContinuityError(f"{field} must be an integer without truncation")
        number = int(value)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        number = int(value.strip())
    else:
        raise ContinuityError(f"{field} must be an integer")
    if number < minimum or number > maximum:
        raise ContinuityError(f"{field} must be between {minimum} and {maximum}")
    return number


def _strict_float(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ContinuityError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContinuityError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ContinuityError(f"{field} must be finite")
    if number < minimum or number > maximum:
        raise ContinuityError(f"{field} must be between {minimum} and {maximum}")
    return number


def _optional_lock_id(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ContinuityError(f"{field} must be a lock object")
    report = integrity_report(value)
    if not report["valid"]:
        raise ContinuityError(f"{field} failed integrity verification")
    item_id = str(value.get("id", "")).strip()
    if not item_id:
        raise ContinuityError(f"{field} is missing id")
    return item_id


class CDProjectLock:
    RETURN_TYPES = ("CD_PROJECT", "STRING", "STRING")
    RETURN_NAMES = ("project", "project_json", "project_hash")
    FUNCTION = "build"
    CATEGORY = LOCKS
    DESCRIPTION = "Creates an integrity-protected project lock with validated production metadata."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_id": ("STRING", {"default": "project-001"}), "title": ("STRING", {"default": "Untitled Production"}), "aspect_ratio": (["16:9", "9:16", "1:1", "4:3", "21:9"],), "fps": ("INT", {"default": 24, "min": 1, "max": 240}), "interface_language": (["en", "zh-CN", "bilingual"],), "notes": ("STRING", {"default": "", "multiline": True})}}

    def build(self, project_id, title, aspect_ratio, fps, interface_language, notes):
        payload = {"title": _required_text(title, "title", 512), "aspect_ratio": aspect_ratio, "fps": _strict_int(fps, "fps", 1, 240), "interface_language": interface_language, "notes": _optional_text(notes, "notes")}
        result = build_lock("project", project_id, payload)
        return result, js(result), result["hash"]


class CDCharacterLock:
    RETURN_TYPES = ("CD_CHARACTER", "STRING", "STRING")
    RETURN_NAMES = ("character", "character_json", "character_hash")
    FUNCTION = "build"
    CATEGORY = LOCKS
    DESCRIPTION = "Creates an integrity-protected character identity and wardrobe lock."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"character_id": ("STRING", {"default": "character-001"}), "display_name": ("STRING", {"default": "Lead"}), "appearance": ("STRING", {"default": "", "multiline": True}), "wardrobe": ("STRING", {"default": "", "multiline": True}), "forbidden_changes": ("STRING", {"default": "hair color, facial structure", "multiline": True}), "reference_ids": ("STRING", {"default": "", "multiline": True}), "identity_seed": ("INT", {"default": 1, "min": 0, "max": 2147483647})}}

    def build(self, character_id, display_name, appearance, wardrobe, forbidden_changes, reference_ids, identity_seed):
        payload = {"display_name": _required_text(display_name, "display_name", 512), "appearance": _optional_text(appearance, "appearance"), "wardrobe": _optional_text(wardrobe, "wardrobe"), "forbidden_changes": split_csv(forbidden_changes), "reference_ids": split_csv(reference_ids), "identity_seed": _strict_int(identity_seed, "identity_seed", 0, 2147483647)}
        result = build_lock("character", character_id, payload)
        return result, js(result), result["hash"]


class CDSceneLock:
    RETURN_TYPES = ("CD_SCENE", "STRING", "STRING")
    RETURN_NAMES = ("scene", "scene_json", "scene_hash")
    FUNCTION = "build"
    CATEGORY = LOCKS
    DESCRIPTION = "Creates an integrity-protected scene, lighting, and palette lock."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene_id": ("STRING", {"default": "scene-001"}), "location": ("STRING", {"default": "Unspecified location"}), "time_of_day": (["dawn", "day", "sunset", "night", "interior-controlled"],), "lighting": ("STRING", {"default": "soft natural light", "multiline": True}), "palette": ("STRING", {"default": "neutral", "multiline": True}), "environment_notes": ("STRING", {"default": "", "multiline": True})}}

    def build(self, scene_id, location, time_of_day, lighting, palette, environment_notes):
        payload = {"location": _required_text(location, "location", 1024), "time_of_day": time_of_day, "lighting": _required_text(lighting, "lighting"), "palette": _required_text(palette, "palette"), "environment_notes": _optional_text(environment_notes, "environment_notes")}
        result = build_lock("scene", scene_id, payload)
        return result, js(result), result["hash"]


class CDShotLock:
    RETURN_TYPES = ("CD_SHOT", "STRING", "STRING")
    RETURN_NAMES = ("shot", "shot_json", "shot_hash")
    FUNCTION = "build"
    CATEGORY = LOCKS
    DESCRIPTION = "Creates a shot lock and verifies optional upstream lock integrity."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"shot_id": ("STRING", {"default": "shot-001"}), "prompt": ("STRING", {"default": "Opening shot", "multiline": True}), "negative_prompt": ("STRING", {"default": "", "multiline": True}), "camera": ("STRING", {"default": "medium shot, eye level", "multiline": True}), "duration_seconds": ("FLOAT", {"default": 3.0, "min": 0.1, "max": 600.0, "step": 0.1}), "seed": ("INT", {"default": 1, "min": 0, "max": 2147483647})}, "optional": {"project": ("CD_PROJECT",), "scene": ("CD_SCENE",), "character": ("CD_CHARACTER",)}}

    def build(self, shot_id, prompt, negative_prompt, camera, duration_seconds, seed, project=None, scene=None, character=None):
        character_id = _optional_lock_id(character, "character")
        payload = {"project_id": _optional_lock_id(project, "project"), "scene_id": _optional_lock_id(scene, "scene"), "character_ids": [character_id] if character_id else [], "prompt": _required_text(prompt, "prompt"), "negative_prompt": _optional_text(negative_prompt, "negative_prompt"), "camera": _required_text(camera, "camera"), "duration_seconds": _strict_float(duration_seconds, "duration_seconds", 0.1, 600.0), "seed": _strict_int(seed, "seed", 0, 2147483647)}
        result = build_lock("shot", shot_id, payload)
        return result, js(result), result["hash"]


class CDManifestBuilder:
    RETURN_TYPES = ("CD_MANIFEST", "STRING", "STRING")
    RETURN_NAMES = ("manifest", "manifest_json", "manifest_hash")
    FUNCTION = "build"
    CATEGORY = LOCKS
    DESCRIPTION = "Verifies lock hashes, rejects duplicate IDs, and validates shot references."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project": ("CD_PROJECT",)}, "optional": {"character": ("CD_CHARACTER",), "scene": ("CD_SCENE",), "shot": ("CD_SHOT",), "extra_characters_json": ("STRING", {"default": "[]", "multiline": True}), "extra_scenes_json": ("STRING", {"default": "[]", "multiline": True}), "extra_shots_json": ("STRING", {"default": "[]", "multiline": True})}}

    def build(self, project, character=None, scene=None, shot=None, extra_characters_json="[]", extra_scenes_json="[]", extra_shots_json="[]"):
        characters = parse_json(extra_characters_json, default=[], expected=list)
        scenes = parse_json(extra_scenes_json, default=[], expected=list)
        shots = parse_json(extra_shots_json, default=[], expected=list)
        if character:
            characters.insert(0, character)
        if scene:
            scenes.insert(0, scene)
        if shot:
            shots.insert(0, shot)
        result = build_manifest(project, characters, scenes, shots)
        return result, js(result), result["hash"]


class CDBatchDirector:
    RETURN_TYPES = ("CD_SHOT_CHAIN", "STRING", "INT")
    RETURN_NAMES = ("shot_chain", "shot_chain_json", "take_count")
    FUNCTION = "direct"
    CATEGORY = DIRECT
    DESCRIPTION = "Expands storyboard shots into uniquely seeded, dependency-safe Takes."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"manifest": ("CD_MANIFEST",), "storyboard_json": ("STRING", {"default": "[{\"id\":\"shot-001\",\"prompt\":\"Opening shot\"}]", "multiline": True}), "takes_per_shot": ("INT", {"default": 3, "min": 1, "max": 16}), "base_seed": ("INT", {"default": 1000, "min": 0, "max": 2147483647})}}

    def direct(self, manifest, storyboard_json, takes_per_shot, base_seed):
        result = expand_storyboard(storyboard_json, manifest, base_seed, takes_per_shot)
        return result, js(result), result["take_count"]


class CDReferenceHandoff:
    RETURN_TYPES = ("CD_REFERENCE", "STRING")
    RETURN_NAMES = ("reference_handoff", "reference_json")
    FUNCTION = "handoff"
    CATEGORY = DIRECT
    DESCRIPTION = "Selects a verified reference source and rejects missing strategy data."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"previous_reference_json": ("STRING", {"default": "{\"last_frame\":\"frame.png\",\"anchor\":\"frame.png\"}", "multiline": True}), "next_reference_json": ("STRING", {"default": "{\"anchor\":\"frame.png\",\"manual\":\"frame.png\"}", "multiline": True}), "strategy": (["last_to_first", "shared_anchor", "manual"],)}}

    def handoff(self, previous_reference_json, next_reference_json, strategy):
        result = reference_handoff(previous_reference_json, next_reference_json, strategy)
        return result, js(result)


class CDQualityGate:
    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING")
    RETURN_NAMES = ("passed", "gate_json", "failed_metrics")
    FUNCTION = "evaluate"
    CATEGORY = QC
    DESCRIPTION = "Evaluates finite 0–1 metrics against finite 0–1 thresholds."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"metrics_json": ("STRING", {"default": "{\"identity\":0.9,\"continuity\":0.82,\"technical\":0.88}", "multiline": True}), "thresholds_json": ("STRING", {"default": "{\"identity\":0.78,\"continuity\":0.72,\"technical\":0.70}", "multiline": True}), "mode": (["all", "any"],)}}

    def evaluate(self, metrics_json, thresholds_json, mode):
        result = quality_gate(metrics_json, thresholds_json, mode)
        return result["passed"], js(result), ", ".join(result["failed_metrics"])


class CDTakeRanker:
    RETURN_TYPES = ("STRING", "STRING", "FLOAT")
    RETURN_NAMES = ("best_take_id", "ranking_json", "best_score")
    FUNCTION = "rank"
    CATEGORY = QC
    DESCRIPTION = "Ranks Takes with validated metric values, weights, and unique IDs."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"takes_json": ("STRING", {"default": "[{\"take_id\":\"take-01\",\"metrics\":{\"identity\":0.9}}]", "multiline": True}), "weights_json": ("STRING", {"default": "{\"identity\":0.35,\"continuity\":0.25,\"technical\":0.2,\"motion\":0.1,\"prompt\":0.1}", "multiline": True})}}

    def rank(self, takes_json, weights_json):
        ranking = rank_takes(takes_json, weights_json)
        best = ranking[0] if ranking else {"take_id": "", "score": 0.0}
        return best["take_id"], js(ranking), float(best["score"])


class CDContinuityReport:
    RETURN_TYPES = ("BOOLEAN", "STRING", "INT")
    RETURN_NAMES = ("passed", "report_json", "issue_count")
    FUNCTION = "compare"
    CATEGORY = QC
    DESCRIPTION = "Compares canonical JSON values with bounded, path-aware diagnostics."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"expected_json": ("STRING", {"default": "{}", "multiline": True}), "actual_json": ("STRING", {"default": "{}", "multiline": True}), "ignore_paths": ("STRING", {"default": "$.timestamp,$.hash", "multiline": True})}, "optional": {"max_issues": ("INT", {"default": 10000, "min": 1, "max": 100000})}}

    def compare(self, expected_json, actual_json, ignore_paths, max_issues=10000):
        issues = continuity_diff(parse_json(expected_json, default={}), parse_json(actual_json, default={}), ignore_paths, max_issues)
        truncated = bool(issues and issues[-1].get("type") == "truncated")
        issue_count = len(issues) - (1 if truncated else 0)
        result = {"passed": not issues, "issue_count": issue_count, "truncated": truncated, "issues": issues}
        return not issues, js(result), issue_count


class CDExecutionPlan:
    RETURN_TYPES = ("CD_EXECUTION_PLAN", "STRING", "INT")
    RETURN_NAMES = ("execution_plan", "execution_plan_json", "wave_count")
    FUNCTION = "plan"
    CATEGORY = RUNTIME
    DESCRIPTION = "Verifies shot-chain integrity and creates bounded dependency waves."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"shot_chain": ("CD_SHOT_CHAIN",), "max_parallel": ("INT", {"default": 4, "min": 1, "max": 64})}}

    def plan(self, shot_chain, max_parallel):
        result = build_execution_plan(shot_chain, max_parallel)
        return result, js(result), result["wave_count"]


class CDAuditEvent:
    RETURN_TYPES = ("CD_AUDIT_EVENT", "STRING", "STRING")
    RETURN_NAMES = ("audit_event", "audit_json", "audit_hash")
    FUNCTION = "append"
    CATEGORY = COLLAB
    DESCRIPTION = "Creates a canonical audit event and validates the predecessor hash."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"event_type": ("STRING", {"default": "generation-approved"}), "actor": ("STRING", {"default": "local-user"}), "payload_json": ("STRING", {"default": "{}", "multiline": True}), "previous_hash": ("STRING", {"default": ""})}}

    def append(self, event_type, actor, payload_json, previous_hash):
        result = audit_event(event_type, _required_text(actor, "actor", 256), parse_json(payload_json, default={}), previous_hash)
        return result, js(result), result["hash"]


class CDThreeWayMerge:
    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("merged_json", "conflicts_json", "has_conflicts")
    FUNCTION = "merge"
    CATEGORY = COLLAB
    DESCRIPTION = "Merges dictionaries and independently edited lists with explicit conflicts."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"base_json": ("STRING", {"default": "{}", "multiline": True}), "current_json": ("STRING", {"default": "{}", "multiline": True}), "incoming_json": ("STRING", {"default": "{}", "multiline": True})}}

    def merge(self, base_json, current_json, incoming_json):
        merged, conflicts = three_way_merge(base_json, current_json, incoming_json)
        return js(merged), js(conflicts), bool(conflicts)


class CDExportPackage:
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("package_json", "package_hash")
    FUNCTION = "export"
    CATEGORY = EXPORT
    DESCRIPTION = "Creates a package and verifies the integrity of nested hashed sections."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"manifest": ("CD_MANIFEST",)}, "optional": {"shot_chain": ("CD_SHOT_CHAIN",), "execution_plan": ("CD_EXECUTION_PLAN",), "audit_event": ("CD_AUDIT_EVENT",)}}

    def export(self, manifest, shot_chain=None, execution_plan=None, audit_event=None):
        result = package_payload(manifest=manifest, shot_chain=shot_chain, execution_plan=execution_plan, audit_event=audit_event)
        return js(result), result["hash"]


NODE_CLASS_MAPPINGS = {"CDProjectLock": CDProjectLock, "CDCharacterLock": CDCharacterLock, "CDSceneLock": CDSceneLock, "CDShotLock": CDShotLock, "CDManifestBuilder": CDManifestBuilder, "CDBatchDirector": CDBatchDirector, "CDReferenceHandoff": CDReferenceHandoff, "CDQualityGate": CDQualityGate, "CDTakeRanker": CDTakeRanker, "CDContinuityReport": CDContinuityReport, "CDExecutionPlan": CDExecutionPlan, "CDAuditEvent": CDAuditEvent, "CDThreeWayMerge": CDThreeWayMerge, "CDExportPackage": CDExportPackage}
NODE_DISPLAY_NAME_MAPPINGS = {key: "CD · " + value for key, value in {"CDProjectLock": "Project Lock", "CDCharacterLock": "Character Lock", "CDSceneLock": "Scene Lock", "CDShotLock": "Shot Lock", "CDManifestBuilder": "Manifest Builder", "CDBatchDirector": "Batch Director", "CDReferenceHandoff": "Reference Handoff", "CDQualityGate": "Quality Gate", "CDTakeRanker": "Take Ranker", "CDContinuityReport": "Continuity Report", "CDExecutionPlan": "Execution Plan", "CDAuditEvent": "Audit Event", "CDThreeWayMerge": "Three-Way Merge", "CDExportPackage": "Export Package"}.items()}
