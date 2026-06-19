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

from continuity_core import build_project, build_sequence_from_brief, package_sequence  # noqa: E402
from production_core import (  # noqa: E402
    ContentAddressedCache,
    apply_provider_budget,
    build_branch_sequence,
    build_scene_topology,
    build_take_variants,
    cast_character,
    custom_provider_payload,
    load_checkpoint,
    negotiate_provider,
    normalize_cast,
    production_report,
    repair_sequence,
    save_checkpoint,
    sequence_from_ndjson,
    sequence_to_ndjson,
    validate_dialogue_turns,
    validate_provider_profile,
    validate_zone_transition,
    verify_sequence_package,
)


class ContinuityV030Tests(unittest.TestCase):
    def project(self):
        return build_project("production", 33, "9:16", 24, "realistic", "neutral", "left key")

    def sequence(self):
        return build_sequence_from_brief({
            "sequence_id": "seq",
            "project": {"project_name": "production", "master_seed": 33},
            "character": {"character_id": "hero", "identity_description": "recognizable person", "default_wardrobe": "black coat"},
            "scene": {"scene_id": "room", "location": "room"},
            "shots": [
                {"shot_id": "a", "action": "walks", "transition": {"exit_frame": "at door"}},
                {"shot_id": "b", "action": "opens door"},
            ],
        })

    def test_cast_and_lookup(self):
        cast = normalize_cast(self.project(), [
            {"character_id": "hero", "display_name": "Hero", "identity_description": "person"},
            {"character_id": "friend", "display_name": "Friend", "identity_description": "second person"},
        ])
        self.assertEqual(cast["character_count"], 2)
        self.assertEqual(cast_character(cast, "friend")["display_name"], "Friend")

    def test_dialogue_unknown_speaker(self):
        cast = normalize_cast(self.project(), [{"character_id": "hero", "identity_description": "person"}])
        report = validate_dialogue_turns(cast, [{"speaker_id": "ghost", "text": "hello"}])
        self.assertFalse(report["valid"])

    def test_topology_detects_jump(self):
        sequence = self.sequence()
        scene = sequence["shots"][0]["scene"]
        topology = build_scene_topology(scene, [{"zone_id": "door"}, {"zone_id": "hall"}], [])
        self.assertFalse(validate_zone_transition(topology, "door", "hall")["allowed"])

    def test_branch_sequence_tracks_root(self):
        base = self.sequence()
        branch = build_branch_sequence({
            "project": {"project_name": "production", "master_seed": 33},
            "character": {"character_id": "hero", "identity_description": "recognizable person", "default_wardrobe": "black coat"},
            "scene": {"scene_id": "room", "location": "room"},
            "shots": [{"shot_id": "branch-a", "action": "turns back"}],
        }, base["shots"][0], "alternate")
        self.assertEqual(branch["branch"]["branch_id"], "alternate")
        self.assertEqual(branch["shots"][0]["lineage"]["branch_index"], 1)

    def test_take_variants_have_unique_seeds(self):
        group = build_take_variants({
            "project": {"project_name": "takes", "master_seed": 1},
            "character": {"identity_description": "person"},
            "scene": {"location": "room"},
            "shot": {"action": "turns"},
        }, 3)
        self.assertEqual(group["take_count"], 3)
        self.assertEqual(len({item["seed"] for item in group["takes"]}), 3)

    def test_provider_budget_truncates(self):
        payload = {"payload": {"prompt": "x" * 6000, "negative_prompt": "y" * 3000, "reference_images": []}, "compatibility_warnings": []}
        result = apply_provider_budget(payload, "runway")
        self.assertLessEqual(len(result["payload"]["prompt"]), 4000)
        self.assertTrue(result["compatibility_warnings"])

    def test_custom_profile(self):
        profile = validate_provider_profile({"name": "local-x", "transport": "local_workflow", "seed_mode": "deterministic", "budget": {"prompt_chars": 500}})
        shot = self.sequence()["shots"][0]
        payload = custom_provider_payload(shot, profile)
        self.assertEqual(payload["provider"], "local-x")
        self.assertEqual(payload["profile"]["budget"]["prompt_chars"], 500)

    def test_negotiation_warns_about_seed(self):
        result = negotiate_provider(self.sequence()["shots"][0], "runway")
        self.assertTrue(any(issue["code"] == "SEED_NOT_GUARANTEED" for issue in result["issues"]))

    def test_content_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            key, path = cache.put({"a": 1})
            self.assertTrue(path.exists())
            self.assertEqual(cache.get(key), {"a": 1})

    def test_checkpoint_roundtrip(self):
        sequence = self.sequence()
        with tempfile.TemporaryDirectory() as tmp:
            path = save_checkpoint(Path(tmp) / "checkpoint.json", sequence, ["a"])
            loaded = load_checkpoint(path)
            self.assertEqual(loaded["completed_shot_ids"], ["a"])

    def test_package_verification(self):
        sequence = self.sequence()
        with tempfile.TemporaryDirectory() as tmp:
            path = package_sequence(Path(tmp) / "package.zip", sequence)
            report = verify_sequence_package(path)
            self.assertTrue(report["valid"])
            self.assertGreater(report["checked_files"], 0)

    def test_package_verification_detects_tamper(self):
        sequence = self.sequence()
        with tempfile.TemporaryDirectory() as tmp:
            path = package_sequence(Path(tmp) / "package.zip", sequence)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("sequence.json", b"{}")
            report = verify_sequence_package(path)
            self.assertFalse(report["valid"])

    def test_repair_sequence(self):
        sequence = self.sequence()
        broken = deepcopy(sequence)
        broken["shots"][1]["shot"]["shot_id"] = "a"
        broken["shots"][1]["lineage"]["parent_fingerprint"] = "bad"
        result = repair_sequence(broken, True)
        self.assertTrue(result["changed"])
        self.assertTrue(result["after"]["passed"])

    def test_ndjson_roundtrip(self):
        sequence = self.sequence()
        restored = sequence_from_ndjson(sequence_to_ndjson(sequence))
        self.assertEqual(restored["shot_count"], sequence["shot_count"])
        self.assertEqual(restored["shots"][0]["shot"]["shot_id"], "a")

    def test_production_report(self):
        report = production_report(self.sequence(), "comfyui")
        self.assertIn("readiness_score", report)
        self.assertEqual(report["metrics"]["shot_count"], 2)


if __name__ == "__main__":
    unittest.main()
