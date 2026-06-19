from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity_core import ContinuityValidationError, build_project, build_sequence_from_brief  # noqa: E402
from runtime_core import compile_task_queue, validate_model_profile  # noqa: E402
from orchestration_core import (  # noqa: E402
    PersistentQueueStore,
    append_trace_event,
    bind_workflow_template,
    build_asset_index,
    build_run_snapshot,
    claim_ready_tasks,
    create_queue_state,
    create_trace_log,
    evaluate_take_quality,
    merge_asset_indexes,
    package_run_bundle,
    plan_remakes,
    rank_take_results,
    reap_expired_leases,
    renew_task_leases,
    select_best_takes,
    summarize_trace_log,
    transition_task_state,
    validate_quality_gate,
    validate_workflow_template,
    verify_run_bundle,
)


class ContinuityV050Tests(unittest.TestCase):
    def project(self):
        return build_project("v05", 55, "9:16", 24, "realistic", "neutral", "left key")

    def sequence(self):
        return build_sequence_from_brief({
            "sequence_id": "v05-seq",
            "project": {"project_name": "v05", "master_seed": 55, "fps": 24},
            "character": {"character_id": "hero", "identity_description": "recognizable person", "default_wardrobe": "black coat"},
            "scene": {"scene_id": "room", "location": "room"},
            "shots": [
                {"shot_id": "a", "duration_seconds": 2, "action": "walks"},
                {"shot_id": "b", "duration_seconds": 2, "action": "turns"},
            ],
        })

    def profile(self):
        return validate_model_profile({
            "profile_id": "v05-model", "transport": "local_workflow", "supports_seed": True,
            "supports_identity_reference": True, "supports_first_frame": True, "supports_last_frame": True,
            "supports_negative_prompt": True, "max_reference_images": 4, "max_duration_seconds": 10,
            "supported_fps": [24],
        })

    def template(self):
        return validate_workflow_template({
            "template_id": "wf",
            "nodes": [
                {"node_id": "prompt", "class_type": "CLIPTextEncode", "inputs": {"text": "${positive_prompt}"}},
                {"node_id": "sampler", "class_type": "KSampler", "inputs": {"seed": "${seed}", "label": "shot-${shot_id}"}},
            ],
        })

    def gate(self):
        return validate_quality_gate({
            "gate_id": "gate", "pass_score": 75, "warning_score": 60, "max_remakes": 2,
            "dimensions": {
                "identity_consistency": {"threshold": 80, "weight": 2, "required": True},
                "temporal_stability": {"threshold": 70, "weight": 1, "required": True},
            },
        })

    def queue(self):
        return compile_task_queue(self.sequence(), "generic", self.profile())

    def test_workflow_template(self):
        template = self.template()
        self.assertEqual(template["node_count"], 2)
        self.assertEqual(template["required_fields"], ["positive_prompt", "seed", "shot_id"])

    def test_workflow_duplicate_node_rejected(self):
        with self.assertRaises(ContinuityValidationError):
            validate_workflow_template({"nodes": [{"node_id": "a", "class_type": "X", "inputs": {}}, {"node_id": "a", "class_type": "Y", "inputs": {}}]})

    def test_workflow_binding_preserves_types(self):
        result = bind_workflow_template(self.template(), {"positive_prompt": "hello", "seed": 123, "shot_id": "a"})
        sampler = result["nodes"][1]
        self.assertEqual(sampler["inputs"]["seed"], 123)
        self.assertEqual(sampler["inputs"]["label"], "shot-a")

    def test_workflow_missing_rejected(self):
        with self.assertRaises(ContinuityValidationError):
            bind_workflow_template(self.template(), {"positive_prompt": "x"})

    def test_run_snapshot_redacts_secrets(self):
        snapshot = build_run_snapshot(self.project(), self.sequence(), self.profile(), self.template(), {"api_key": "secret", "nested": {"token": "x"}})
        self.assertEqual(snapshot["settings"]["api_key"], "[REDACTED]")
        self.assertEqual(len(snapshot["redacted_paths"]), 2)

    def test_illegal_task_transition(self):
        with self.assertRaises(ContinuityValidationError):
            transition_task_state({"task_id": "a", "status": "queued"}, "running", 1)

    def test_queue_state(self):
        state = create_queue_state(self.queue(), now_ms=100)
        self.assertEqual(state["task_count"], 2)
        self.assertEqual(state["revision"], 1)

    def test_claim_respects_dependencies(self):
        queue = {"type": "generation_queue", "tasks": [
            {"task_id": "a", "status": "queued", "requires_tasks": []},
            {"task_id": "b", "status": "queued", "requires_tasks": ["a"]},
        ]}
        state = create_queue_state(queue, now_ms=100)
        result = claim_ready_tasks(state, "worker", 2, 10, now_ms=200)
        self.assertEqual([item["task_id"] for item in result["claimed"]], ["a"])

    def test_renew_lease(self):
        state = create_queue_state({"type": "generation_queue", "tasks": [{"task_id": "a", "status": "queued"}]}, now_ms=1)
        claimed = claim_ready_tasks(state, "w", 1, 10, now_ms=10)["queue_state"]
        renewed = renew_task_leases(claimed, "w", ["a"], 20, now_ms=20)
        self.assertEqual(renewed["renewed_count"], 1)
        self.assertEqual(renewed["queue_state"]["tasks"][0]["lease"]["expires_at_ms"], 20020)

    def test_reap_expired_lease(self):
        state = create_queue_state({"type": "generation_queue", "tasks": [{"task_id": "a", "status": "queued"}]}, now_ms=1)
        claimed = claim_ready_tasks(state, "w", 1, 1, now_ms=10)["queue_state"]
        reaped = reap_expired_leases(claimed, now_ms=2000, max_attempts=3)
        self.assertEqual(reaped["requeued_task_ids"], ["a"])
        self.assertEqual(reaped["queue_state"]["tasks"][0]["attempt"], 2)

    def test_persistent_store_roundtrip_and_conflict(self):
        state = create_queue_state(self.queue(), now_ms=1)
        with tempfile.TemporaryDirectory() as tmp:
            store = PersistentQueueStore(tmp)
            store.save(state)
            self.assertEqual(store.load(state["queue_id"])["queue_id"], state["queue_id"])
            with self.assertRaises(ContinuityValidationError):
                store.save(state, expected_revision=99)

    def test_asset_index_duplicates(self):
        digest = "a" * 64
        index = build_asset_index([
            {"asset_id": "a", "source": "a.mp4", "sha256": digest},
            {"asset_id": "b", "source": "b.mp4", "sha256": digest},
        ], "p")
        self.assertEqual(index["duplicate_count"], 1)

    def test_asset_merge_rejects_cross_project(self):
        first = build_asset_index([], "p1")
        second = build_asset_index([], "p2")
        with self.assertRaises(ContinuityValidationError):
            merge_asset_indexes(first, second)

    def test_quality_gate(self):
        gate = self.gate()
        self.assertEqual(gate["gate_id"], "gate")

    def test_quality_evaluation_pass(self):
        result = evaluate_take_quality(self.gate(), {"identity_consistency": 90, "temporal_stability": 85}, "t1", "a", 1)
        self.assertEqual(result["decision"], "pass")

    def test_quality_evaluation_hard_fail(self):
        result = evaluate_take_quality(self.gate(), {"identity_consistency": 50, "temporal_stability": 90}, "t1", "a", 1)
        self.assertEqual(result["decision"], "fail")

    def test_take_ranking(self):
        low = evaluate_take_quality(self.gate(), {"identity_consistency": 50, "temporal_stability": 90}, "low", "a", 1)
        high = evaluate_take_quality(self.gate(), {"identity_consistency": 90, "temporal_stability": 90}, "high", "a", 2)
        result = rank_take_results([low, high])
        self.assertEqual(result["best_task_id"], "high")

    def test_take_selection_unresolved(self):
        failed = evaluate_take_quality(self.gate(), {"identity_consistency": 20, "temporal_stability": 20}, "bad", "a", 1)
        result = select_best_takes([failed], True)
        self.assertFalse(result["complete"])
        self.assertEqual(result["unresolved_shot_ids"], ["a"])

    def test_remake_plan(self):
        failed = evaluate_take_quality(self.gate(), {"identity_consistency": 20, "temporal_stability": 90}, "bad", "a", 1)
        result = plan_remakes([failed], self.gate())
        self.assertEqual(result["request_count"], 1)
        self.assertIn("identity_consistency", result["requests"][0]["failed_dimensions"])

    def test_trace_summary(self):
        log = create_trace_log("r")
        log = append_trace_event(log, "task.started", {}, 100, "info")
        log = append_trace_event(log, "task.failed", {}, 250, "error")
        summary = summarize_trace_log(log)
        self.assertTrue(summary["has_errors"])
        self.assertEqual(summary["duration_ms"], 150)

    def test_run_bundle_verification(self):
        snapshot = build_run_snapshot(self.project(), self.sequence(), self.profile(), self.template())
        state = create_queue_state(self.queue(), snapshot, now_ms=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = package_run_bundle(Path(tmp) / "run.zip", snapshot, state, self.gate())
            result = verify_run_bundle(path)
            self.assertTrue(result["valid"])
            self.assertGreaterEqual(result["checked_files"], 3)

    def test_run_bundle_detects_tamper(self):
        snapshot = build_run_snapshot(self.project(), self.sequence(), self.profile(), self.template())
        state = create_queue_state(self.queue(), snapshot, now_ms=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = package_run_bundle(Path(tmp) / "run.zip", snapshot, state)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("run_snapshot.json", b"{}")
            result = verify_run_bundle(path)
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
