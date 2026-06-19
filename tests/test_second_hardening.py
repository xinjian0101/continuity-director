from __future__ import annotations

import copy
import importlib
import importlib.util
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "continuity_director_second_hardening"


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
nodes = importlib.import_module(f"{PACKAGE}.nodes")
ContinuityError = continuity.ContinuityError


class StrictJSONTests(unittest.TestCase):
    def test_nonfinite_json_and_python_values_are_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "Non-finite"):
            continuity.parse_json('{"value":NaN}')
        with self.assertRaisesRegex(ContinuityError, "Non-finite"):
            continuity.stable_json({"value": math.inf})

    def test_unsupported_values_and_nonstring_keys_are_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "key.*must be a string"):
            continuity.stable_json({1: "value"})
        with self.assertRaisesRegex(ContinuityError, "Unsupported JSON value"):
            continuity.stable_json({"value": {1, 2}})

    def test_long_identifiers_are_bounded_and_deterministic(self):
        first = continuity.build_lock("project", "x" * 300, {})
        second = continuity.build_lock("project", "x" * 300, {})
        self.assertEqual(first["id"], second["id"])
        self.assertLessEqual(len(first["id"]), 128)


class LockAndManifestIntegrityTests(unittest.TestCase):
    def test_tampered_lock_is_rejected(self):
        project = continuity.build_lock("project", "project-a", {"fps": 24})
        project["data"]["fps"] = 30
        with self.assertRaisesRegex(ContinuityError, "integrity verification"):
            continuity.build_manifest(project)

    def test_manifest_rejects_unknown_shot_references(self):
        project = continuity.build_lock("project", "project-a", {})
        shot = continuity.build_lock(
            "shot",
            "shot-a",
            {"project_id": "project-a", "scene_id": "missing-scene", "character_ids": ["missing-character"]},
        )
        with self.assertRaisesRegex(ContinuityError, "unknown scene"):
            continuity.build_manifest(project, [], [], [shot])


class GovernanceTests(unittest.TestCase):
    def test_diff_quotes_special_keys_and_accepts_string_ignore_paths(self):
        issues = continuity.continuity_diff({"a.b": 1}, {"a.b": 2})
        self.assertEqual(issues[0]["path"], '$["a.b"]')
        self.assertEqual(continuity.continuity_diff({"a.b": 1}, {"a.b": 2}, '$["a.b"]'), [])

    def test_diff_limit_reports_truncation(self):
        issues = continuity.continuity_diff({"a": 1, "b": 1}, {"a": 2, "b": 2}, max_issues=1)
        self.assertEqual(issues[-1]["type"], "truncated")
        self.assertEqual(issues[-1]["limit"], 1)

    def test_audit_predecessor_hash_is_validated(self):
        with self.assertRaisesRegex(ContinuityError, "previous_hash"):
            continuity.audit_event("approved", "tester", {}, "not-a-hash")

    def test_package_rejects_tampered_hashed_section(self):
        project = continuity.build_lock("project", "project-a", {})
        project["data"]["changed"] = True
        with self.assertRaisesRegex(ContinuityError, "integrity verification"):
            continuity.package_payload(project=project)


class StoryboardTests(unittest.TestCase):
    def test_lossy_integer_inputs_are_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "without truncation"):
            production.expand_storyboard([{"id": "shot-a"}], {}, 0, 1.5)
        with self.assertRaisesRegex(ContinuityError, "without truncation"):
            production.expand_storyboard([{"id": "shot-a"}], {}, 1.5, 1)

    def test_explicit_seed_produces_unique_take_seeds(self):
        chain = production.expand_storyboard([{"id": "shot-a", "seed": 7}], {}, 0, 3)
        self.assertEqual([item["seed"] for item in chain["takes"]], [7, 8, 9])

    def test_shot_dependencies_resolve_to_take_dependencies(self):
        chain = production.expand_storyboard(
            [{"id": "shot-a"}, {"id": "shot-b", "depends_on": ["shot-a"]}],
            {},
            0,
            2,
        )
        downstream = [item for item in chain["takes"] if item["shot_id"] == "shot-b"]
        expected = ["shot-a-take-01", "shot-a-take-02"]
        self.assertTrue(all(item["depends_on"] == expected for item in downstream))

    def test_storyboard_references_are_checked_against_manifest(self):
        project = continuity.build_lock("project", "project-a", {})
        scene = continuity.build_lock("scene", "scene-a", {})
        character = continuity.build_lock("character", "character-a", {})
        manifest = continuity.build_manifest(project, [character], [scene])
        with self.assertRaisesRegex(ContinuityError, "unknown scene"):
            production.expand_storyboard([{"id": "shot-a", "scene_id": "scene-b"}], manifest, 0, 1)
        with self.assertRaisesRegex(ContinuityError, "unknown characters"):
            production.expand_storyboard(
                [{"id": "shot-a", "scene_id": "scene-a", "character_ids": ["character-b"]}],
                manifest,
                0,
                1,
            )


class QualityAndReferenceTests(unittest.TestCase):
    def test_reference_handoff_rejects_invalid_strategy_and_missing_data(self):
        with self.assertRaisesRegex(ContinuityError, "strategy"):
            production.reference_handoff({}, {}, "unknown")
        with self.assertRaisesRegex(ContinuityError, "No usable reference"):
            production.reference_handoff({}, {}, "last_to_first")

    def test_quality_gate_rejects_out_of_range_values(self):
        with self.assertRaisesRegex(ContinuityError, "between 0 and 1"):
            production.quality_gate({"identity": 1.2}, {"identity": 0.8})
        with self.assertRaisesRegex(ContinuityError, "between 0 and 1"):
            production.quality_gate({"identity": 0.9}, {"identity": -0.1})

    def test_ranking_rejects_invalid_metrics_names_and_ids(self):
        with self.assertRaisesRegex(ContinuityError, "between 0 and 1"):
            production.rank_takes([{"take_id": "one", "metrics": {"identity": 2}}])
        with self.assertRaisesRegex(ContinuityError, "colliding names"):
            production.rank_takes(
                [{"take_id": "one", "metrics": {"identity": 0.5}}],
                {"identity": 1, " identity ": 1},
            )
        with self.assertRaisesRegex(ContinuityError, "Duplicate take id"):
            production.rank_takes([
                {"take_id": "Take A", "metrics": {}},
                {"take_id": "Take-A", "metrics": {}},
            ])


class RuntimeAndMergeTests(unittest.TestCase):
    def test_cycle_diagnostic_contains_actionable_path(self):
        with self.assertRaisesRegex(ContinuityError, "a -> b -> a"):
            runtime.dependency_waves([
                {"id": "a", "depends_on": ["b"]},
                {"id": "b", "depends_on": ["a"]},
            ])

    def test_parallelism_outside_supported_range_is_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "between 1 and 64"):
            runtime.dependency_waves([{"id": "a"}], 999)

    def test_execution_plan_verifies_source_chain_hash(self):
        chain = production.expand_storyboard([{"id": "shot-a"}], {}, 0, 1)
        plan = runtime.build_execution_plan(chain, 1)
        self.assertTrue(plan["source_verified"])
        self.assertEqual(plan["source_hash"], chain["hash"])

    def test_independent_list_edits_merge_without_false_conflict(self):
        merged, conflicts = collaboration.three_way_merge([1, 1], [2, 1], [1, 2])
        self.assertEqual(merged, [2, 2])
        self.assertEqual(conflicts, [])


class ReliabilityTests(unittest.TestCase):
    def test_migration_downgrade_is_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "downgrade"):
            validation.migrate_payload({"schema": "continuity-director/item@2.0"}, "1.0")

    def test_retry_ceiling_below_base_is_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "greater than or equal"):
            validation.retry_policy(3, 10.0, 2.0, 5.0)

    def test_checkpoint_rejects_invalid_plan_hash(self):
        plan = {"hash": "bad", "waves": [{"tasks": [{"task_id": "a"}]}]}
        with self.assertRaisesRegex(ContinuityError, "integrity verification"):
            validation.queue_checkpoint(plan)

    def test_environment_lock_rejects_sensitive_fields(self):
        with self.assertRaisesRegex(ContinuityError, "sensitive field"):
            validation.environment_lock("unknown", "unknown", [{"name": "model", "api_key": "secret"}], "")


class NodeBoundaryTests(unittest.TestCase):
    def test_blank_project_title_is_rejected(self):
        with self.assertRaisesRegex(ContinuityError, "title must not be empty"):
            nodes.CDProjectLock().build("project-a", "   ", "16:9", 24, "en", "")

    def test_reference_handoff_default_payloads_are_executable(self):
        result, text = nodes.CDReferenceHandoff().handoff(
            '{"last_frame":"frame.png","anchor":"frame.png"}',
            '{"anchor":"frame.png","manual":"frame.png"}',
            "last_to_first",
        )
        self.assertEqual(result["selected_reference"], "frame.png")
        self.assertIn("selected_from", text)


if __name__ == "__main__":
    unittest.main()
