from __future__ import annotations

import importlib
import importlib.util
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "continuity_director_hardening"


def load_package():
    existing = sys.modules.get(PACKAGE)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Continuity Director package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


load_package()
continuity = importlib.import_module(f"{PACKAGE}.continuity_core")
production = importlib.import_module(f"{PACKAGE}.production_core")
runtime = importlib.import_module(f"{PACKAGE}.runtime_core")
collaboration = importlib.import_module(f"{PACKAGE}.collaboration_core")
validation = importlib.import_module(f"{PACKAGE}.validation_core")
ContinuityError = continuity.ContinuityError


class InputHardeningTests(unittest.TestCase):
    def test_whitespace_json_uses_default(self):
        self.assertEqual(continuity.parse_json("  \n\t ", default={}), {})

    def test_tuple_type_error_is_readable(self):
        with self.assertRaisesRegex(ContinuityError, "Expected list or dict"):
            continuity.parse_json("1", expected=(list, dict))

    def test_split_csv_deduplicates_and_preserves_order(self):
        self.assertEqual(
            continuity.split_csv(" alpha, beta;alpha\r\ngamma "),
            ["alpha", "beta", "gamma"],
        )
        with self.assertRaises(ContinuityError):
            continuity.split_csv({"bad": "mapping"})

    def test_ignore_path_covers_list_descendants(self):
        issues = continuity.continuity_diff(
            {"shots": [{"seed": 1, "prompt": "a"}]},
            {"shots": [{"seed": 2, "prompt": "a"}]},
            ["$.shots"],
        )
        self.assertEqual(issues, [])


class ManifestAndStoryboardTests(unittest.TestCase):
    def test_manifest_rejects_duplicate_lock_ids(self):
        project = continuity.build_lock("project", "p", {})
        character = continuity.build_lock("character", "lead", {})
        with self.assertRaisesRegex(ContinuityError, "Duplicate character lock id"):
            continuity.build_manifest(project, [character, character])

    def test_manifest_rejects_wrong_lock_kind(self):
        project = continuity.build_lock("project", "p", {})
        scene = continuity.build_lock("scene", "s", {})
        with self.assertRaisesRegex(ContinuityError, "Expected character lock"):
            continuity.build_manifest(project, [scene])

    def test_storyboard_normalizes_collections(self):
        chain = production.expand_storyboard(
            [{
                "id": "Shot A",
                "character_ids": "Lead, Support, Lead",
                "depends_on": ["Shot Zero", "Shot Zero"],
                "duration_seconds": 1.5,
            }],
            {},
            10,
            1,
        )
        take = chain["takes"][0]
        self.assertEqual(take["shot_id"], "Shot-A")
        self.assertEqual(take["character_ids"], ["Lead", "Support"])
        self.assertEqual(take["depends_on"], ["Shot-Zero"])

    def test_storyboard_rejects_duplicate_ids_and_nonfinite_duration(self):
        with self.assertRaisesRegex(ContinuityError, "Duplicate shot id"):
            production.expand_storyboard([{"id": "A B"}, {"id": "A-B"}], {}, 0, 1)
        with self.assertRaisesRegex(ContinuityError, "must be finite"):
            production.expand_storyboard([{"duration_seconds": math.nan}], {}, 0, 1)


class QualityAndRankingTests(unittest.TestCase):
    def test_quality_gate_validates_mode_and_is_deterministic(self):
        with self.assertRaisesRegex(ContinuityError, "mode"):
            production.quality_gate({}, {}, "invalid")
        report = production.quality_gate({"identity": 1.0}, {"zeta": 0.5}, "all")
        names = [item["metric"] for item in report["checks"]]
        self.assertEqual(names, sorted(names))
        self.assertIn("zeta", report["missing_metrics"])

    def test_ranking_rejects_duplicate_normalized_ids(self):
        with self.assertRaisesRegex(ContinuityError, "Duplicate take id"):
            production.rank_takes([
                {"take_id": "Take A", "metrics": {}},
                {"take_id": "Take-A", "metrics": {}},
            ])

    def test_ranking_rejects_nonfinite_weights(self):
        with self.assertRaisesRegex(ContinuityError, "must be finite"):
            production.rank_takes([{"take_id": "one", "metrics": {}}], {"identity": math.inf})


class RuntimeHardeningTests(unittest.TestCase):
    def test_dependency_string_and_parallel_clamp(self):
        tasks = [
            {"id": "a"},
            {"id": "b", "depends_on": "a"},
        ]
        waves = runtime.dependency_waves(tasks, max_parallel=999)
        self.assertEqual([[task["task_id"] for task in wave] for wave in waves], [["a"], ["b"]])
        plan = runtime.build_execution_plan({"takes": tasks}, max_parallel=999)
        self.assertEqual(plan["max_parallel"], 64)

    def test_self_dependency_is_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "cannot depend on itself"):
            runtime.dependency_waves([{"id": "a", "depends_on": ["a"]}])


class MergeAndMigrationTests(unittest.TestCase):
    def test_merge_reports_delete_vs_change_without_null_ambiguity(self):
        merged, conflicts = collaboration.three_way_merge(
            {"value": 1},
            {},
            {"value": 2},
        )
        self.assertNotIn("value", merged)
        conflict = conflicts[0]
        self.assertEqual(conflict["kind"], "delete-vs-change")
        self.assertFalse(conflict["current_exists"])
        self.assertTrue(conflict["incoming_exists"])

    def test_noop_migration_preserves_payload(self):
        source = {"schema": "continuity-director/item@1.0", "value": 1, "hash": "original"}
        migrated, changes = validation.migrate_payload(source, "1.0")
        self.assertEqual(migrated, source)
        self.assertEqual(changes, [])

    def test_invalid_migration_target_is_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "target_version"):
            validation.migrate_payload({}, "latest")


class ReliabilityHardeningTests(unittest.TestCase):
    def test_retry_policy_is_overflow_safe(self):
        policy = validation.retry_policy(100, 1.0, 10.0, 60.0)
        self.assertEqual(len(policy["delays_seconds"]), 99)
        self.assertTrue(all(math.isfinite(value) and value <= 60.0 for value in policy["delays_seconds"]))
        with self.assertRaisesRegex(ContinuityError, "must be finite"):
            validation.retry_policy(3, math.nan, 2, 60)

    def test_checkpoint_preserves_plan_order(self):
        plan = {
            "hash": "plan",
            "waves": [
                {"tasks": [{"task_id": "b"}]},
                {"tasks": [{"task_id": "a"}, {"task_id": "c"}]},
            ],
        }
        checkpoint = validation.queue_checkpoint(plan, ["a"], [])
        self.assertEqual(checkpoint["completed"], ["a"])
        self.assertEqual(checkpoint["remaining"], ["b", "c"])

    def test_checkpoint_rejects_overlap_and_duplicate_plan_ids(self):
        plan = {"waves": [{"tasks": [{"task_id": "a"}]}]}
        with self.assertRaisesRegex(ContinuityError, "both completed and failed"):
            validation.queue_checkpoint(plan, ["a"], ["a"])
        duplicate = {"waves": [{"tasks": [{"task_id": "a"}, {"task_id": "a"}]}]}
        with self.assertRaisesRegex(ContinuityError, "Duplicate execution plan task id"):
            validation.queue_checkpoint(duplicate)

    def test_hash_report_distinguishes_format_and_mismatch(self):
        payload = {"schema": "test", "value": 1}
        valid_payload = dict(payload, hash=continuity.digest(payload))
        self.assertEqual(validation.verify_hashed_payload(valid_payload)["reason"], "valid")
        self.assertEqual(validation.verify_hashed_payload(dict(payload, hash="bad"))["reason"], "invalid-hash-format")
        wrong = "0" * 64
        self.assertEqual(validation.verify_hashed_payload(dict(payload, hash=wrong))["reason"], "hash-mismatch")

    def test_environment_lock_canonicalizes_models(self):
        lock = validation.environment_lock(" ", "", ["z-model", "a-model", "a-model"], " note ")
        self.assertEqual(lock["comfyui_version"], "unknown")
        self.assertEqual(lock["frontend_version"], "unknown")
        self.assertEqual(lock["models"], ["a-model", "z-model"])
        self.assertEqual(lock["notes"], "note")
        self.assertTrue(lock["platform_machine"])


if __name__ == "__main__":
    unittest.main()
