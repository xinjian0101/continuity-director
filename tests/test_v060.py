from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from continuity_core import SCHEMA_VERSION  # noqa: E402
from orchestration_core import create_queue_state  # noqa: E402
from postprocess_core import (  # noqa: E402
    apply_batch_rerun_plan,
    apply_rollback_plan,
    build_artifact_lineage,
    build_frame_extraction_plan,
    build_resource_quota,
    build_rollback_plan,
    build_sequence_assembly_plan,
    build_structured_diff,
    build_system_health_report,
    collect_observability_metrics,
    compare_regression_results,
    create_regression_baseline,
    create_version_snapshot,
    evaluate_boundary_continuity,
    evaluate_resource_quota,
    evaluate_technical_quality,
    execute_frame_extraction,
    execute_sequence_assembly,
    load_configuration_bundle,
    normalize_external_metrics,
    normalize_ffprobe_payload,
    package_configuration_bundle,
    plan_batch_rerun,
    probe_media_file,
    reserve_resource_quota,
    trace_artifact_lineage,
    verify_version_snapshot,
)


class ContinuityV060Tests(unittest.TestCase):
    def ffprobe_payload(self):
        return {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "24/1",
                    "nb_frames": "48",
                    "pix_fmt": "yuv420p",
                }
            ],
            "format": {"filename": "shot.mp4", "duration": "2.0", "size": "1000", "bit_rate": "4000"},
        }

    def extraction(self, prefix: str, timestamps: list[float]):
        return {
            "schema_version": SCHEMA_VERSION,
            "type": "frame_extraction_result",
            "frames": [
                {"frame_id": f"{prefix}-{index}", "timestamp_seconds": value, "output_path": f"{prefix}-{index}.png"}
                for index, value in enumerate(timestamps)
            ],
        }

    def queue(self):
        return create_queue_state(
            {
                "type": "generation_queue",
                "tasks": [
                    {"task_id": "task-a", "shot_id": "a", "status": "succeeded", "seed": 10, "priority": 0},
                    {"task_id": "task-b", "shot_id": "b", "status": "failed", "seed": 20, "priority": 0},
                ],
            },
            now_ms=100,
        )

    def test_schema_version(self):
        self.assertEqual(SCHEMA_VERSION, "1.6")

    def test_normalize_ffprobe(self):
        result = normalize_ffprobe_payload(self.ffprobe_payload())
        self.assertEqual(result["video_stream_count"], 1)
        self.assertEqual(result["primary_video"]["fps"], 24.0)
        self.assertEqual(result["duration_seconds"], 2.0)

    def test_frame_plan_boundary(self):
        probe = normalize_ffprobe_payload(self.ffprobe_payload(), "/tmp/shot.mp4")
        plan = build_frame_extraction_plan(probe, "/tmp/frames", "boundary", 2)
        self.assertEqual(plan["frame_count"], 2)
        self.assertEqual(plan["frames"][0]["timestamp_seconds"], 0.0)
        self.assertLess(plan["frames"][-1]["timestamp_seconds"], 2.0)

    def test_technical_qc_pass(self):
        probe = normalize_ffprobe_payload(self.ffprobe_payload())
        result = evaluate_technical_quality(probe, {"min_width": 512, "min_height": 512}, 2.0, 24.0)
        self.assertTrue(result["passed"])
        self.assertEqual(result["decision"], "pass")

    def test_technical_qc_detects_black_frames(self):
        probe = normalize_ffprobe_payload(self.ffprobe_payload())
        result = evaluate_technical_quality(probe, {}, analysis_metrics={"black_frame_ratio": 0.5})
        self.assertFalse(result["passed"])

    def test_external_metric_adapter(self):
        result = normalize_external_metrics(
            {"adapter_id": "face", "metrics": {"identity_similarity": {"path": "face.sim", "scale": "0-1"}}},
            {"face": {"sim": 0.91}},
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["metrics"]["identity_similarity"], 91.0)

    def test_external_distance_adapter(self):
        result = normalize_external_metrics(
            {"metrics": {"identity_similarity": {"path": "distance", "scale": "distance-0-1"}}},
            {"distance": 0.2},
        )
        self.assertEqual(result["metrics"]["identity_similarity"], 80.0)

    def test_boundary_continuity(self):
        previous = {"shot_id": "a", "transition": {"exit_frame": "hero by door"}}
        nxt = {"shot_id": "b", "transition": {"entry_frame": "hero by door"}}
        metrics = {"identity_similarity": 90, "composition_match": 80, "lighting_match": 80, "color_match": 80, "motion_continuity": 80}
        result = evaluate_boundary_continuity(previous, nxt, self.extraction("a", [0, 2]), self.extraction("b", [0, 2]), metrics)
        self.assertTrue(result["passed"])
        self.assertGreater(result["overall_score"], 80)

    def test_boundary_identity_failure(self):
        previous = {"shot_id": "a"}
        nxt = {"shot_id": "b"}
        metrics = {"identity_similarity": 20, "composition_match": 90, "lighting_match": 90, "color_match": 90, "motion_continuity": 90}
        result = evaluate_boundary_continuity(previous, nxt, self.extraction("a", [0]), self.extraction("b", [0]), metrics)
        self.assertFalse(result["passed"])

    def test_assembly_plan_orders_clips(self):
        plan = build_sequence_assembly_plan(
            [{"shot_id": "b", "path": "b.mp4", "order": 2}, {"shot_id": "a", "path": "a.mp4", "order": 1}],
            "/tmp/final.mp4",
        )
        self.assertEqual([item["shot_id"] for item in plan["clips"]], ["a", "b"])

    def test_version_snapshot_and_verification(self):
        snapshot = create_version_snapshot({"project": {"seed": 1}}, "v1")
        self.assertTrue(verify_version_snapshot(snapshot)["valid"])
        snapshot["state"]["project"]["seed"] = 2
        self.assertFalse(verify_version_snapshot(snapshot)["valid"])

    def test_structured_diff_critical(self):
        result = build_structured_diff({"project": {"master_seed": 1}}, {"project": {"master_seed": 2}})
        self.assertEqual(result["change_count"], 1)
        self.assertEqual(result["critical_change_count"], 1)

    def test_full_rollback(self):
        target = create_version_snapshot({"project": {"seed": 1}, "shots": [1]}, "target")
        current = create_version_snapshot({"project": {"seed": 2}, "shots": [1, 2]}, "current", target)
        plan = build_rollback_plan(current, target)
        result = apply_rollback_plan(current["state"], plan)
        self.assertEqual(result["state"], target["state"])

    def test_partial_rollback(self):
        target = create_version_snapshot({"project": {"seed": 1}, "name": "old"}, "target")
        current = create_version_snapshot({"project": {"seed": 2}, "name": "new"}, "current")
        plan = build_rollback_plan(current, target, ["project.seed"])
        result = apply_rollback_plan(current["state"], plan)
        self.assertEqual(result["state"]["project"]["seed"], 1)
        self.assertEqual(result["state"]["name"], "new")

    def test_batch_rerun(self):
        queue = self.queue()
        plan = plan_batch_rerun(queue, [{"shot_id": "b", "decision": "fail"}])
        self.assertEqual(plan["request_count"], 1)
        applied = apply_batch_rerun_plan(queue, plan, now_ms=200)
        self.assertEqual(applied["added_count"], 1)
        self.assertEqual(applied["queue_state"]["task_count"], 3)

    def test_quota_reservation(self):
        quota = build_resource_quota({"quota_id": "q", "limits": {"tasks": 2, "gpu_seconds": 100}})
        evaluation = evaluate_resource_quota(quota, {"tasks": 1, "gpu_seconds": 20})
        self.assertTrue(evaluation["allowed"])
        reserved = reserve_resource_quota(quota, evaluation, "r1")
        self.assertEqual(reserved["used"]["tasks"], 1)

    def test_quota_exceeded(self):
        quota = build_resource_quota({"limits": {"tasks": 1}})
        evaluation = evaluate_resource_quota(quota, {"tasks": 2})
        self.assertFalse(evaluation["allowed"])

    def test_observability_metrics(self):
        result = collect_observability_metrics(self.queue(), qc_reports=[{"decision": "pass", "score": 90}])
        self.assertIn("queue_tasks", result["prometheus_text"])
        self.assertGreater(result["sample_count"], 0)

    def test_health_report_expired_lease(self):
        queue = self.queue()
        queue["tasks"][0]["status"] = "running"
        queue["tasks"][0]["lease"] = {"expires_at_ms": 1}
        report = build_system_health_report(queue, now_ms=1000)
        self.assertEqual(report["status"], "unhealthy")

    def test_regression_baseline_pass(self):
        results = [{"case_id": "a", "output": {"x": 1}, "metrics": {"score": 90}}]
        baseline = create_regression_baseline(results, "suite")
        comparison = compare_regression_results(baseline, results)
        self.assertTrue(comparison["passed"])

    def test_regression_metric_drift(self):
        baseline = create_regression_baseline([{"case_id": "a", "output": {"x": 1}, "metrics": {"score": 90}}], "suite")
        comparison = compare_regression_results(baseline, [{"case_id": "a", "output": {"x": 1}, "metrics": {"score": 80}}], {"score": 2})
        self.assertFalse(comparison["passed"])

    def test_configuration_bundle_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = package_configuration_bundle(Path(tmp) / "configs.zip", {"profile": {"type": "model", "api_key": "secret", "value": 1}})
            loaded = load_configuration_bundle(path)
            self.assertTrue(loaded["valid"])
            self.assertEqual(loaded["configurations"]["profile"]["api_key"], "[REDACTED]")

    def test_configuration_bundle_detects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = package_configuration_bundle(Path(tmp) / "configs.zip", {"profile": {"value": 1}})
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("configs/profile.json", b"{}")
            loaded = load_configuration_bundle(path)
            self.assertFalse(loaded["valid"])

    def test_lineage_graph_and_trace(self):
        graph = build_artifact_lineage([
            {"artifact_id": "prompt", "artifact_type": "prompt"},
            {"artifact_id": "clip", "artifact_type": "video", "parents": ["prompt"]},
            {"artifact_id": "final", "artifact_type": "video", "parents": ["clip"]},
        ])
        self.assertTrue(graph["valid"])
        trace = trace_artifact_lineage(graph, "clip")
        self.assertEqual(trace["ancestor_ids"], ["prompt"])
        self.assertEqual(trace["descendant_ids"], ["final"])

    def test_lineage_cycle(self):
        graph = build_artifact_lineage([
            {"artifact_id": "a", "parents": ["b"]},
            {"artifact_id": "b", "parents": ["a"]},
        ])
        self.assertFalse(graph["valid"])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
    def test_real_media_probe_extract_and_assembly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.mp4"
            second = root / "second.mp4"
            for path, color in ((first, "red"), (second, "blue")):
                command = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"color=c={color}:s=64x64:r=10:d=0.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(path),
                ]
                subprocess.run(command, check=True)
            probe = probe_media_file(first)
            self.assertEqual(probe["primary_video"]["width"], 64)
            frame_plan = build_frame_extraction_plan(probe, root / "frames", "boundary", 2)
            extracted = execute_frame_extraction(frame_plan, overwrite=True)
            self.assertTrue(extracted["complete"])
            plan = build_sequence_assembly_plan(
                [{"shot_id": "a", "path": str(first)}, {"shot_id": "b", "path": str(second)}],
                root / "final.mp4",
                "transcode",
                target_fps=10,
            )
            assembled = execute_sequence_assembly(plan, overwrite=True)
            self.assertTrue(assembled["success"])
            self.assertEqual(assembled["media_probe"]["primary_video"]["width"], 64)


if __name__ == "__main__":
    unittest.main()
