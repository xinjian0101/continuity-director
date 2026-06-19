from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("github_admin_setup", ROOT / "scripts" / "github_admin_setup.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load administrator setup")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitHubAdminSetupTests(unittest.TestCase):
    def test_plan_contains_project_topics(self):
        module = load_module()
        settings = module.plan()
        self.assertIn("comfyui", settings["topics"]["names"])
        self.assertIn("open-source", settings["topics"]["names"])

    def test_ruleset_requires_ci_and_protects_main(self):
        module = load_module()
        payload = module.ruleset_payload()
        rule_types = {rule["type"] for rule in payload["rules"]}
        self.assertIn("pull_request", rule_types)
        self.assertIn("required_status_checks", rule_types)
        self.assertIn("non_fast_forward", rule_types)


if __name__ == "__main__":
    unittest.main()
