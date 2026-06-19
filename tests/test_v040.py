from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity_core import build_project, build_sequence_from_brief  # noqa: E402
from production_core import normalize_cast  # noqa: E402
from runtime_core import (  # noqa: E402
    build_reference_registry,
    update_reference_status,
    plan_character_presence,
    build_sequence_timeline,
    compile_dependency_graph,
    schedule_execution_waves,
    build_retry_policy,
    derive_retry_attempt,
    compile_task_queue,
    reconcile_task_results,
    classify_generation_failure,
    validate_model_profile,
    match_sequence_to_model,
    compile_model_prompt,
    select_reference_frames,
    estimate_generation_cost,
    compile_execution_plan,
    diagnose_execution_plan,
)


class ContinuityV040Tests(unittest.TestCase):
    def project(self):
        return build_project("runtime", 44, "9:16", 24, "realistic", "neutral", "left key")

    def sequence(self):
        return build_sequence_from_brief({
            "sequence_id": "runtime-seq",
            "project": {"project_name": "runtime", "master_seed": 44, "fps": 24},
            "character": {"character_id": "hero", "identity_description": "recognizable person", "default_wardrobe": "black coat"},
            "scene": {"scene_id": "room", "location": "room"},
            "shots": [
                {"shot_id": "a", "duration_seconds": 2.0, "action": "walks", "transition": {"exit_frame": "at door"}},
                {"shot_id": "b", "duration_seconds": 3.0, "action": "opens door"},
                {"shot_id": "c", "duration_seconds": 1.0, "action": "looks back"},
            ],
        })

    def profile(self):
        return validate_model_profile({
            "profile_id": "test-model",
            "transport": "local_workflow",
            "supports_seed": True,
            "supports_identity_reference": True,
            "supports_first_frame": True,
            "supports_last_frame": True,
            "supports_negative_prompt": True,
            "max_reference_images": 2,
            "max_duration_seconds": 4,
            "supported_fps": [24],
            "base_cost_per_task": 1,
            "cost_per_second": 0.5,
            "prompt_template": "{shot_id}: {positive_prompt}",
        })

    def registry(self):
        registry = build_reference_registry(self.project(), [
            {"frame_id": "face", "source": "input/face.png", "role": "face", "status": "approved", "character_id": "hero", "weight": 1.5},
            {"frame_id": "first", "source": "input/first.png", "role": "first_frame", "status": "approved", "shot_id": "a"},
            {"frame_id": "old", "source": "input/old.png", "role": "identity", "status": "retired", "character_id": "hero"},
        ])
        return registry

    def test_reference_registry(self):
        registry = self.registry()
        self.assertEqual(registry["frame_count"], 3)
        self.assertEqual(registry["type"], "reference_registry")

    def test_reference_status_update(self):
        updated = update_reference_status(self.registry(), "old", "approved", "restored")
        item = next(x for x in updated["frames"] if x["frame_id"] == "old")
        self.assertEqual(item["status"], "approved")

    def test_presence_plan(self):
        cast = normalize_cast(self.project(), [
            {"character_id": "hero", "identity_description": "person"},
            {"character_id": "friend", "identity_description": "person"},
        ])
        plan = plan_character_presence(cast, self.sequence(), [
            {"shot_id": "a", "entrances": ["hero"], "present": ["hero"]},
            {"shot_id": "b", "entrances": ["friend"], "present": ["hero", "friend"]},
            {"shot_id": "c", "exits": ["friend"], "present": ["hero"]},
        ])
        self.assertTrue(plan["valid"])
        self.assertEqual(plan["shots"][1]["present"], ["friend", "hero"])

    def test_presence_invalid_exit(self):
        cast = normalize_cast(self.project(), [{"character_id": "hero", "identity_description": "person"}])
        plan = plan_character_presence(cast, self.sequence(), [{"shot_id": "a", "exits": ["hero"]}])
        self.assertFalse(plan["valid"])

    def test_timeline_frames(self):
        timeline = build_sequence_timeline(self.sequence(), "01:00:00:00", 8)
        self.assertEqual(timeline["total_frames"], 144)
        self.assertEqual(timeline["shots"][0]["source_in_frame"], 8)

    def test_dependency_graph(self):
        graph = compile_dependency_graph(self.sequence(), [{"shot_id": "c", "requires": ["a"]}])
        self.assertTrue(graph["valid"])
        self.assertEqual(graph["topological_order"], ["a", "b", "c"])

    def test_dependency_cycle(self):
        graph = compile_dependency_graph(self.sequence(), [{"shot_id": "a", "requires": ["c"]}])
        self.assertFalse(graph["valid"])

    def test_execution_waves(self):
        graph = compile_dependency_graph(self.sequence())
        waves = schedule_execution_waves(graph, 2)
        self.assertEqual(waves["wave_count"], 3)

    def test_retry_policy(self):
        policy = build_retry_policy(3, "stable_variant", [0, 1, 2], ["timeout"])
        shot = self.sequence()["shots"][0]
        first = derive_retry_attempt(shot, 1, policy)
        second = derive_retry_attempt(shot, 2, policy)
        self.assertNotEqual(first["seed"], second["seed"])

    def test_task_queue(self):
        queue = compile_task_queue(self.sequence(), "generic", self.profile(), take_count=2)
        self.assertEqual(queue["task_count"], 6)
        self.assertEqual(len({task["task_id"] for task in queue["tasks"]}), 6)

    def test_reconcile_results(self):
        queue = compile_task_queue(self.sequence(), "generic", self.profile())
        task_id = queue["tasks"][0]["task_id"]
        report = reconcile_task_results(queue, [{"task_id": task_id, "status": "succeeded", "output": {"path": "a.mp4"}}])
        self.assertEqual(report["counts"]["succeeded"], 1)
        self.assertFalse(report["complete"])

    def test_failure_classifier(self):
        result = classify_generation_failure("CUDA out of memory")
        self.assertEqual(result["category"], "oom")
        self.assertTrue(result["retryable"])

    def test_model_profile(self):
        profile = self.profile()
        self.assertEqual(profile["profile_id"], "test-model")
        self.assertEqual(profile["supported_fps"], [24])

    def test_model_match(self):
        profile = self.profile()
        profile["max_duration_seconds"] = 2.5
        report = match_sequence_to_model(self.sequence(), profile, self.registry())
        self.assertFalse(report["compatible"])
        self.assertTrue(any(i["code"] == "MODEL_DURATION_LIMIT" for i in report["issues"]))

    def test_prompt_adapter(self):
        result = compile_model_prompt(self.sequence()["shots"][0], self.profile())
        self.assertTrue(result["positive_prompt"].startswith("a:"))

    def test_reference_selector(self):
        result = select_reference_frames(self.registry(), self.sequence()["shots"][0], self.profile())
        self.assertEqual(result["selected_count"], 2)
        self.assertEqual(result["selected"][0]["frame_id"], "face")

    def test_cost_estimate(self):
        result = estimate_generation_cost(self.sequence(), self.profile(), 2)
        self.assertEqual(result["estimated_total"], 12.0)

    def test_execution_plan(self):
        result = compile_execution_plan(self.sequence(), self.profile(), self.registry(), take_count=2)
        self.assertFalse(result["blocked"])
        self.assertEqual(result["task_queue"]["task_count"], 6)

    def test_execution_diagnostics(self):
        plan = compile_execution_plan(self.sequence(), self.profile(), self.registry())
        report = diagnose_execution_plan(plan)
        self.assertIn("critical_path_depth", report["metrics"])
        self.assertGreaterEqual(report["score"], 0)

    def test_model_duration_blocks_execution(self):
        profile = self.profile()
        profile["max_duration_seconds"] = 1
        plan = compile_execution_plan(self.sequence(), profile, self.registry())
        self.assertTrue(plan["blocked"])


if __name__ == "__main__":
    unittest.main()
