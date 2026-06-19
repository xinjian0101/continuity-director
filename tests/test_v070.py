from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity_core import ContinuityValidationError, SCHEMA_VERSION, migrate_object  # noqa: E402
from orchestration_core import create_queue_state  # noqa: E402
from collaboration_core import (  # noqa: E402
    acquire_edit_lock,
    append_audit_event,
    build_collaboration_dashboard,
    build_compatibility_matrix,
    build_fault_injection_plan,
    build_replay_manifest,
    compare_replay_manifests,
    create_approval_record,
    create_change_request,
    create_collaboration_manifest,
    create_environment_lockfile,
    detect_stale_workers,
    evaluate_fault_recovery,
    evaluate_generation_gate,
    import_bulk_records,
    register_worker,
    release_edit_lock,
    review_change_request,
    schedule_distributed_tasks,
    three_way_merge,
    transition_approval,
    update_worker_heartbeat,
    validate_template_manifest,
    verify_audit_log,
    verify_template_trust,
)


class ContinuityV070Tests(unittest.TestCase):
    def collaboration(self, approvals: int = 1):
        return create_collaboration_manifest(
            "project-a",
            [
                {"member_id": "owner", "role": "owner"},
                {"member_id": "editor", "role": "editor"},
                {"member_id": "reviewer", "role": "reviewer"},
                {"member_id": "operator", "role": "operator"},
            ],
            "owner",
            {"minimum_approvals": approvals, "allow_self_approval": False},
            now_ms=1000,
        )

    def queue(self):
        return create_queue_state(
            {
                "type": "generation_queue",
                "tasks": [
                    {"task_id": "task-a", "shot_id": "shot-a", "status": "queued", "seed": 1, "priority": 2, "requirements": {"model_profile": "wan", "min_vram_gb": 16}},
                    {"task_id": "task-b", "shot_id": "shot-b", "status": "queued", "seed": 2, "priority": 1, "requirements": {"model_profile": "ltxv", "min_vram_gb": 8}},
                ],
            },
            now_ms=1000,
        )

    def test_schema_version(self):
        self.assertEqual(SCHEMA_VERSION, "1.6")

    def test_migrate_15_to_16(self):
        result = migrate_object({"schema_version": "1.5", "type": "sequence_manifest", "shots": []})
        self.assertEqual(result["schema_version"], "1.6")

    def test_collaboration_manifest_roles(self):
        result = self.collaboration()
        self.assertEqual(result["member_count"], 4)
        owner = next(item for item in result["members"] if item["member_id"] == "owner")
        self.assertIn("admin", owner["permissions"])

    def test_collaboration_requires_one_owner(self):
        with self.assertRaises(ContinuityValidationError):
            create_collaboration_manifest("p", [{"member_id": "a", "role": "editor"}], "a")

    def test_lock_acquire_and_release(self):
        collab = self.collaboration()
        state = acquire_edit_lock(collab, None, "editor", "shot", "shot-1", now_ms=1000)
        self.assertEqual(state["active_lock_count"], 1)
        released = release_edit_lock(collab, state, "editor", "shot", "shot-1", state["last_acquired"]["lease_token"], now_ms=2000)
        self.assertEqual(released["active_lock_count"], 0)

    def test_lock_conflict_and_revision(self):
        collab = self.collaboration()
        state = acquire_edit_lock(collab, None, "editor", "shot", "shot-1", now_ms=1000)
        with self.assertRaises(ContinuityValidationError):
            acquire_edit_lock(collab, state, "owner", "shot", "shot-1", now_ms=1100)
        with self.assertRaises(ContinuityValidationError):
            acquire_edit_lock(collab, state, "editor", "shot", "shot-2", expected_revision=0, now_ms=1100)

    def test_approval_workflow(self):
        collab = self.collaboration()
        record = create_approval_record(collab, "shot", "shot-1", "editor", "abc", now_ms=1000)
        record = transition_approval(collab, record, "editor", "submit", now_ms=1100)
        record = transition_approval(collab, record, "reviewer", "approve", now_ms=1200)
        self.assertEqual(record["state"], "approved")

    def test_approval_forbids_self_approval(self):
        collab = self.collaboration()
        record = create_approval_record(collab, "shot", "shot-1", "owner", "abc", now_ms=1000)
        record = transition_approval(collab, record, "owner", "submit", now_ms=1100)
        with self.assertRaises(ContinuityValidationError):
            transition_approval(collab, record, "owner", "approve", now_ms=1200)

    def test_approval_minimum_count(self):
        collab = create_collaboration_manifest(
            "p",
            [{"member_id": "owner", "role": "owner"}, {"member_id": "r1", "role": "reviewer"}, {"member_id": "r2", "role": "reviewer"}, {"member_id": "e", "role": "editor"}],
            "owner",
            {"minimum_approvals": 2},
            now_ms=1000,
        )
        record = create_approval_record(collab, "shot", "s", "e", "x", now_ms=1000)
        record = transition_approval(collab, record, "e", "submit", now_ms=1100)
        record = transition_approval(collab, record, "r1", "approve", now_ms=1200)
        self.assertEqual(record["state"], "in_review")
        record = transition_approval(collab, record, "r2", "approve", now_ms=1300)
        self.assertEqual(record["state"], "approved")

    def test_change_request_review(self):
        collab = self.collaboration()
        request = create_change_request(collab, "editor", {"shot_id": "s1", "seed": 1}, {"seed": 2}, "change seed", ["reviewer"], now_ms=1000)
        reviewed = review_change_request(collab, request, "reviewer", "approve", now_ms=1100)
        self.assertEqual(reviewed["status"], "approved")

    def test_change_request_requires_comment(self):
        collab = self.collaboration()
        request = create_change_request(collab, "editor", {"shot_id": "s1"}, {"action": "run"}, "change", ["reviewer"], now_ms=1000)
        with self.assertRaises(ContinuityValidationError):
            review_change_request(collab, request, "reviewer", "request_changes", "", now_ms=1100)

    def test_audit_chain_and_tamper_detection(self):
        log = append_audit_event(None, "p", "owner", "created", {"x": 1}, now_ms=1000)
        log = append_audit_event(log, "p", "editor", "updated", {"x": 2}, now_ms=1100)
        self.assertTrue(verify_audit_log(log)["valid"])
        tampered = deepcopy(log)
        tampered["events"][0]["payload"]["x"] = 9
        self.assertFalse(verify_audit_log(tampered)["valid"])

    def test_three_way_merge_clean(self):
        result = three_way_merge({"a": 1, "b": 1}, {"a": 2, "b": 1}, {"a": 1, "b": 3})
        self.assertTrue(result["clean"])
        self.assertEqual(result["merged"], {"a": 2, "b": 3})

    def test_three_way_merge_conflict(self):
        result = three_way_merge({"a": 1}, {"a": 2}, {"a": 3})
        self.assertFalse(result["clean"])
        self.assertEqual(result["conflict_count"], 1)

    def test_worker_registration_and_heartbeat(self):
        registry = register_worker(None, "w1", {"model_profiles": ["wan"], "vram_gb": 24}, capacity=2, now_ms=1000)
        registry = update_worker_heartbeat(registry, "w1", "busy", 1, {"temperature": 60}, now_ms=1100)
        self.assertEqual(registry["workers"][0]["active_tasks"], 1)
        self.assertEqual(registry["workers"][0]["state"], "busy")

    def test_stale_worker_detection(self):
        registry = register_worker(None, "w1", {}, now_ms=1000)
        health = detect_stale_workers(registry, 10, now_ms=12000)
        self.assertEqual(health["stale_worker_count"], 1)

    def test_distributed_scheduler_capabilities(self):
        queue = self.queue()
        registry = register_worker(None, "wan-worker", {"model_profiles": ["wan"], "vram_gb": 24}, capacity=1, now_ms=1000)
        registry = register_worker(registry, "ltx-worker", {"model_profiles": ["ltxv"], "vram_gb": 12}, capacity=1, now_ms=1000)
        schedule = schedule_distributed_tasks(queue, registry)
        self.assertEqual(schedule["assignment_count"], 2)
        self.assertEqual({item["worker_id"] for item in schedule["assignments"]}, {"wan-worker", "ltx-worker"})

    def test_distributed_scheduler_reports_blocked(self):
        queue = self.queue()
        registry = register_worker(None, "small", {"model_profiles": ["wan"], "vram_gb": 4}, capacity=1, now_ms=1000)
        schedule = schedule_distributed_tasks(queue, registry)
        self.assertEqual(schedule["assignment_count"], 0)
        self.assertGreaterEqual(schedule["blocked_count"], 1)

    def test_compatibility_matrix(self):
        matrix = build_compatibility_matrix(
            [{"environment_id": "ok", "python_version": "3.13", "plugins": {"x": "1"}, "models": ["wan"], "ffmpeg_available": True, "vram_gb": 24}],
            {"min_python": "3.10", "plugins": {"x": "1"}, "models": ["wan"], "ffmpeg_required": True, "min_vram_gb": 16},
        )
        self.assertTrue(matrix["all_compatible"])

    def test_compatibility_matrix_detects_missing(self):
        matrix = build_compatibility_matrix([{"environment_id": "bad", "python_version": "3.9", "plugins": {}, "models": []}], {"min_python": "3.10", "plugins": {"x": "1"}, "models": ["wan"]})
        self.assertFalse(matrix["all_compatible"])
        self.assertGreater(matrix["environments"][0]["issue_count"], 0)

    def test_environment_lockfile_is_sorted(self):
        lockfile = create_environment_lockfile({"plugins": {"z": "2", "a": "1"}, "models": ["b", "a", "b"]}, "p", "owner")
        self.assertEqual(list(lockfile["environment"]["plugins"]), ["a", "z"])
        self.assertEqual(lockfile["environment"]["models"], ["a", "b"])

    def test_bulk_jsonl_import(self):
        result = import_bulk_records('{"shot_id":"a"}\n{"shot_id":"b"}', "jsonl", ["shot_id"])
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["error_count"], 0)

    def test_bulk_csv_duplicate_detection(self):
        result = import_bulk_records("shot_id,action\na,run\na,jump\n", "csv", ["shot_id"])
        self.assertEqual(result["valid_count"], 1)
        self.assertEqual(result["errors"][0]["code"], "duplicate_id")

    def test_template_validation_and_trust(self):
        digest = "a" * 64
        validation = validate_template_manifest({"template_id": "t", "name": "T", "version": "1.0.0", "license": "MIT", "entrypoint": "workflow.json", "files": [{"path": "workflow.json", "sha256": digest}]})
        self.assertTrue(validation["valid"])
        trust = verify_template_trust(validation, "pub", digest, {"allowed_publishers": ["pub"], "publisher_digests": {"pub": digest}})
        self.assertTrue(trust["trusted"])

    def test_template_rejects_unsafe_path(self):
        validation = validate_template_manifest({"template_id": "t", "version": "1.0.0", "license": "MIT", "entrypoint": "../x", "files": [{"path": "../x", "sha256": "a" * 64}]})
        self.assertFalse(validation["valid"])

    def test_fault_plan_is_deterministic(self):
        queue = self.queue()
        scenarios = [{"fault_type": "timeout", "task_id": "task-a", "probability": 0.5, "expected_recovery": "retry"}]
        first = build_fault_injection_plan(queue, scenarios, 123)
        second = build_fault_injection_plan(queue, scenarios, 123)
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertTrue(first["dry_run_only"])

    def test_fault_recovery_report(self):
        queue = self.queue()
        plan = build_fault_injection_plan(queue, [{"fault_type": "timeout", "task_id": "task-a", "probability": 1, "expected_recovery": "retry"}], 1)
        scenario_id = plan["scenarios"][0]["scenario_id"]
        report = evaluate_fault_recovery(plan, [{"scenario_id": scenario_id, "recovery_action": "retry", "status": "recovered"}])
        self.assertTrue(report["passed"])

    def test_replay_manifest_and_comparison(self):
        queue = self.queue()
        replay = build_replay_manifest({"type": "run_snapshot", "fingerprint": "snap"}, queue, [{"task_id": "task-a", "sha256": "a" * 64}])
        comparison = compare_replay_manifests(replay, deepcopy(replay))
        self.assertTrue(comparison["deterministic"])
        changed = deepcopy(replay)
        changed["outputs"][0]["sha256"] = "b" * 64
        self.assertFalse(compare_replay_manifests(replay, changed)["deterministic"])

    def test_generation_gate_ready(self):
        collab = self.collaboration()
        record = create_approval_record(collab, "shot", "shot-1", "editor", "abc", now_ms=1000)
        record = transition_approval(collab, record, "editor", "submit", now_ms=1100)
        record = transition_approval(collab, record, "reviewer", "approve", now_ms=1200)
        log = append_audit_event(None, "project-a", "owner", "created", {}, now_ms=1000)
        matrix = build_compatibility_matrix([{"environment_id": "ok", "python_version": "3.13"}], {"min_python": "3.10"})
        gate = evaluate_generation_gate(collab, [record], None, matrix, verify_audit_log(log), ["shot-1"], now_ms=1300)
        self.assertTrue(gate["ready"])

    def test_generation_gate_blocks_active_lock(self):
        collab = self.collaboration()
        lock = acquire_edit_lock(collab, None, "editor", "shot", "shot-1", now_ms=1000)
        gate = evaluate_generation_gate(collab, [], lock, None, None, [], now_ms=1100)
        self.assertFalse(gate["ready"])
        self.assertEqual(gate["blockers"][0]["code"], "active_edit_lock")

    def test_collaboration_dashboard(self):
        collab = self.collaboration()
        gate = {"ready": False, "score": 50, "blocker_count": 2}
        dashboard = build_collaboration_dashboard(collab, None, [], [{"status": "open"}], None, gate)
        self.assertFalse(dashboard["generation_ready"])
        self.assertGreater(dashboard["attention_count"], 0)


if __name__ == "__main__":
    unittest.main()
