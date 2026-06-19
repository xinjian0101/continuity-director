from __future__ import annotations

import importlib
import json
import unittest

from _bootstrap import PACKAGE_NAME

continuity = importlib.import_module(f"{PACKAGE_NAME}.continuity_core")
extended = importlib.import_module(f"{PACKAGE_NAME}.extended_nodes")
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


if __name__ == "__main__":
    unittest.main()
