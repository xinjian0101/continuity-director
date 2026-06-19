from __future__ import annotations

import importlib
import json
import unittest

from _bootstrap import PACKAGE_NAME

continuity = importlib.import_module(f"{PACKAGE_NAME}.continuity_core")
extended = importlib.import_module(f"{PACKAGE_NAME}.extended_nodes")
environment_nodes = importlib.import_module(f"{PACKAGE_NAME}.environment_nodes")
validation = importlib.import_module(f"{PACKAGE_NAME}.validation_core")


class ReliabilityTests(unittest.TestCase):
    def test_verify_hashed_payload(self):
        payload = continuity.build_lock("project", "demo", {"fps": 24})
        self.assertTrue(validation.verify_hashed_payload(payload)["valid"])
        payload["data"]["fps"] = 30
        self.assertFalse(validation.verify_hashed_payload(payload)["valid"])

    def test_verify_node(self):
        payload = continuity.build_lock("project", "demo", {"fps": 24})
        valid, report_json, expected = extended.CDVerifyPackage().verify(json.dumps(payload))
        self.assertTrue(valid)
        self.assertEqual(json.loads(report_json)["expected_hash"], expected)

    def test_migration_node(self):
        payload = {"schema": "continuity-director/project@0.9", "id": "demo"}
        migrated_json, changes_json, changed = extended.CDMigratePayload().migrate(json.dumps(payload), "1.0")
        migrated = json.loads(migrated_json)
        self.assertTrue(changed)
        self.assertEqual(migrated["schema"], "continuity-director/project@1.0")
        self.assertEqual(json.loads(changes_json)[0]["path"], "$.schema")
        self.assertTrue(validation.verify_hashed_payload(migrated)["valid"])

    def test_retry_policy_is_bounded(self):
        policy, _, first = extended.CDRetryPolicy().build(5, 2.0, 3.0, 20.0)
        self.assertEqual(first, 2.0)
        self.assertEqual(policy["delays_seconds"], [2.0, 6.0, 18.0, 20.0])

    def test_queue_checkpoint(self):
        plan = {"hash": "plan", "waves": [{"tasks": [{"task_id": "a"}, {"task_id": "b"}]}]}
        checkpoint, _, remaining = extended.CDQueueCheckpoint().checkpoint(plan, '["a"]', "[]")
        self.assertEqual(remaining, 1)
        self.assertEqual(checkpoint["remaining"], ["b"])

    def test_idempotency_key_is_order_independent(self):
        key_a, canonical_a = extended.CDIdempotencyKey().create("generation", '{"b":2,"a":1}')
        key_b, canonical_b = extended.CDIdempotencyKey().create("generation", '{"a":1,"b":2}')
        self.assertEqual(key_a, key_b)
        self.assertEqual(canonical_a, canonical_b)

    def test_environment_lock(self):
        lock, text, lock_hash = environment_nodes.CDEnvironmentLock().build("0.3.x", "1.46.x", '["model-a"]', "test")
        self.assertEqual(json.loads(text)["hash"], lock_hash)
        self.assertEqual(lock["models"], ["model-a"])
        self.assertTrue(validation.verify_hashed_payload(lock)["valid"])


if __name__ == "__main__":
    unittest.main()
