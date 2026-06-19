from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity_core import (  # noqa: E402
    ContinuityValidationError,
    audit_sequence,
    build_character,
    build_from_brief,
    build_project,
    build_scene,
    build_sequence_from_brief,
    build_shot,
    compile_prompt_sections,
    migrate_object,
    package_sequence,
    provider_payload,
)


class ContinuityV020Tests(unittest.TestCase):
    def base(self):
        project = build_project("p", 1, "9:16", 24, "realistic", "neutral", "left key")
        character = build_character(
            project,
            "hero",
            "Hero",
            "recognizable person",
            "oval face",
            "short hair",
            "slim",
            "black jacket",
            "silver watch",
            "watch remains",
        )
        scene = build_scene(project, character, "s", "garage", "night", "rain", "cold", "wet floor", "left to right", "red car")
        return project, character, scene

    def shot(self, project, character, scene, shot_id="shot-001", previous=None, **kwargs):
        values = dict(
            project=project,
            character=character,
            scene=scene,
            shot_id=shot_id,
            duration_seconds=4,
            action="walks",
            emotion="calm",
            dialogue="",
            camera_shot="medium shot",
            camera_move="locked camera",
            lens="35mm",
            composition="center",
            motion_rules="natural",
            previous_shot=previous,
            allowed_changes="emotion, position",
            position="door",
        )
        values.update(kwargs)
        return build_shot(**values)

    def test_rejects_invalid_aspect_ratio(self):
        with self.assertRaises(ContinuityValidationError):
            build_project("p", 1, "vertical", 24, "", "", "")

    def test_rejects_cross_project_character(self):
        project, character, _ = self.base()
        other = build_project("other", 2, "9:16", 24, "", "", "")
        with self.assertRaises(ContinuityValidationError):
            build_scene(other, character, "s", "x", "", "", "", "")

    def test_migrates_v1_shot(self):
        project, character, scene = self.base()
        old = self.shot(project, character, scene)
        old["schema_version"] = "1.0"
        old.pop("lineage", None)
        migrated = migrate_object(old)
        self.assertEqual(migrated["schema_version"], "1.6")
        self.assertIn("lineage", migrated)

    def test_state_patch_add_remove_and_clear(self):
        project, character, scene = self.base()
        first = self.shot(project, character, scene, allowed_changes="emotion, position, injuries, props, unlock:props", injuries="scratch")
        patch = {"add": {"injuries": ["bruise"]}, "remove": {"injuries": ["scratch"]}, "clear": ["position"]}
        second = self.shot(
            project,
            character,
            scene,
            "shot-002",
            previous=first,
            allowed_changes="emotion, position, injuries",
            state_patch_json=json.dumps(patch),
        )
        self.assertEqual(second["continuity_state"]["injuries"], ["bruise"])
        self.assertEqual(second["continuity_state"]["position"], "")

    def test_hard_lock_requires_explicit_unlock(self):
        project, character, scene = self.base()
        blocked = self.shot(project, character, scene, wardrobe_override="white coat", allowed_changes="wardrobe")
        self.assertEqual(blocked["continuity_state"]["wardrobe"], "black jacket")
        unlocked = self.shot(project, character, scene, wardrobe_override="white coat", allowed_changes="wardrobe, unlock:wardrobe")
        self.assertEqual(unlocked["continuity_state"]["wardrobe"], "white coat")

    def test_multi_reference_images_are_normalized(self):
        project = build_project("p", 1, "9:16", 24, "", "", "")
        character = build_character(
            project, "hero", "Hero", "person", "", "", "", "coat", reference_images=[
                {"source": "input/face.png", "role": "face", "weight": 1.2},
                {"source": "input/face.png", "role": "face", "weight": 1.2},
            ]
        )
        self.assertEqual(len(character["reference_images"]), 1)
        self.assertEqual(character["reference_images"][0]["role"], "face")

    def test_transition_inherits_previous_exit_frame(self):
        project, character, scene = self.base()
        first = self.shot(project, character, scene, transition_json=json.dumps({"exit_frame": "hand on door"}))
        second = self.shot(project, character, scene, "shot-002", previous=first)
        self.assertEqual(second["transition"]["entry_frame"], "hand on door")
        self.assertEqual(second["lineage"]["parent_fingerprint"], first["fingerprint"])

    def test_provider_payload_reports_portability(self):
        project, character, scene = self.base()
        shot = self.shot(project, character, scene)
        payload = provider_payload(shot, "runway", provider_settings={"model": "user-selected"})
        self.assertEqual(payload["capabilities"]["seed_mode"], "adapter_hint")
        self.assertTrue(payload["compatibility_warnings"])
        self.assertEqual(payload["payload"]["provider_settings"]["model"], "user-selected")

    def test_sequence_build_and_audit(self):
        sequence = build_sequence_from_brief({
            "project": {"project_name": "seq", "master_seed": 3},
            "character": {"identity_description": "person", "default_wardrobe": "coat"},
            "scene": {"location": "street"},
            "shots": [
                {"shot_id": "a", "action": "walk", "transition": {"exit_frame": "at gate"}},
                {"shot_id": "b", "action": "opens gate"},
            ],
        })
        self.assertEqual(sequence["shot_count"], 2)
        self.assertEqual(sequence["shots"][1]["transition"]["entry_frame"], "at gate")
        report = audit_sequence(sequence)
        self.assertTrue(report["passed"])

    def test_sequence_audit_detects_broken_parent(self):
        sequence = build_sequence_from_brief({
            "project": {"project_name": "seq"},
            "character": {"identity_description": "person"},
            "scene": {"location": "room"},
            "shots": [{"shot_id": "a"}, {"shot_id": "b"}],
        })
        broken = deepcopy(sequence)
        broken["shots"][1]["lineage"]["parent_fingerprint"] = "wrong"
        report = audit_sequence(broken)
        self.assertFalse(report["passed"])
        self.assertTrue(report["structural_issues"])

    def test_sequence_package_contains_checksums(self):
        sequence = build_sequence_from_brief({
            "project": {"project_name": "seq"},
            "character": {"identity_description": "person"},
            "scene": {"location": "room"},
            "shots": [{"shot_id": "a"}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = package_sequence(Path(tmp) / "package.zip", sequence)
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                self.assertIn("index.json", names)
                self.assertIn("checksums.sha256.json", names)
                self.assertIn("sequence.json", names)

    def test_prompt_compiler_truncates_safely(self):
        prompt, warnings, stats = compile_prompt_sections(["x" * 100], max_chars=20)
        self.assertLessEqual(len(prompt), 20)
        self.assertTrue(warnings)
        self.assertEqual(stats["original_characters"], 100)

    def test_one_click_accepts_advanced_fields(self):
        result = build_from_brief({
            "project": {"project_name": "advanced"},
            "character": {"identity_description": "person", "protected_state_fields": "wardrobe"},
            "scene": {"location": "room"},
            "shot": {"action": "turns", "transition": {"exit_frame": "profile"}, "seed_salt": "take-2"},
        })
        self.assertEqual(result["manifest"]["transition"]["exit_frame"], "profile")
        self.assertEqual(result["manifest"]["seed_salt"], "take-2")


if __name__ == "__main__":
    unittest.main()
