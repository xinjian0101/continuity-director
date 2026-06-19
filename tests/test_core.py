from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity_core import (  # noqa: E402
    atomic_write_json,
    audit_manifests,
    build_character,
    build_from_brief,
    build_project,
    build_scene,
    build_shot,
    manifest_fingerprint,
    provider_payload,
    stable_seed,
)


class ContinuityCoreTests(unittest.TestCase):
    def setUp(self):
        self.project = build_project(
            "test project",
            42,
            "9:16",
            24,
            "realistic",
            "neutral",
            "light from camera left",
        )
        self.character = build_character(
            self.project,
            "hero",
            "Hero",
            "young adult with recognizable face",
            "oval face",
            "short black hair",
            "slim build",
            "black jacket",
            "silver watch",
            "never remove watch",
        )
        self.scene = build_scene(
            self.project,
            self.character,
            "scene-1",
            "warehouse",
            "night",
            "rain",
            "cold light",
            "concrete floor",
            "left to right",
            "red door",
        )

    def make_shot(self, shot_id="s1", previous=None, **kwargs):
        defaults = dict(
            project=self.project,
            character=self.character,
            scene=self.scene,
            shot_id=shot_id,
            duration_seconds=5,
            action="walks forward",
            emotion="calm",
            dialogue="",
            camera_shot="medium shot",
            camera_move="locked camera",
            lens="35mm",
            composition="centered",
            motion_rules="natural motion",
            previous_shot=previous,
            allowed_changes="emotion, position",
            position="doorway",
        )
        defaults.update(kwargs)
        return build_shot(**defaults)

    def test_seed_is_deterministic(self):
        self.assertEqual(stable_seed(42, "a", "b"), stable_seed(42, "a", "b"))
        self.assertNotEqual(stable_seed(42, "a", "b"), stable_seed(42, "a", "c"))

    def test_manifest_reproducible(self):
        first = self.make_shot()
        second = self.make_shot()
        self.assertEqual(first["seed"], second["seed"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertIn("[IDENTITY LOCK]", first["positive_prompt"])

    def test_previous_state_is_inherited(self):
        first = self.make_shot(injuries="scratch on left cheek", allowed_changes="emotion, position, injuries")
        second = self.make_shot("s2", previous=first, emotion="afraid", position="inside room")
        self.assertEqual(second["continuity_state"]["injuries"], ["scratch on left cheek"])

    def test_unapproved_change_is_blocked_and_warned(self):
        first = self.make_shot()
        second = self.make_shot("s2", previous=first, wardrobe_override="white coat")
        self.assertEqual(second["continuity_state"]["wardrobe"], "black jacket")
        self.assertTrue(second["warnings"])

    def test_audit_detects_character_drift(self):
        first = self.make_shot()
        second = json.loads(json.dumps(first))
        second["character"]["locked"]["face_features"] = "round face"
        second["fingerprint"] = manifest_fingerprint(second)
        report = audit_manifests(first, second)
        self.assertFalse(report["passed"])
        self.assertLess(report["score"], 80)


    def test_one_click_brief(self):
        result = build_from_brief({
            "project": {"project_name": "one click", "master_seed": 7},
            "character": {"identity_description": "recognizable person", "default_wardrobe": "blue coat"},
            "scene": {"location": "street"},
            "shot": {"action": "turns around", "position": "crosswalk"},
        })
        self.assertEqual(result["manifest"]["continuity_state"]["wardrobe"], "blue coat")
        self.assertIn("turns around", result["manifest"]["positive_prompt"])

    def test_provider_payload(self):
        shot = self.make_shot()
        payload = provider_payload(shot, "veo", "https://example.com/ref.png")
        self.assertEqual(payload["provider"], "veo")
        self.assertEqual(payload["payload"]["reference_image_url"], "https://example.com/ref.png")
        self.assertEqual(payload["payload"]["seed"], shot["seed"])

    def test_atomic_write_avoids_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            first = atomic_write_json(path, {"a": 1})
            second = atomic_write_json(path, {"a": 2})
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["a"], 2)


if __name__ == "__main__":
    unittest.main()
