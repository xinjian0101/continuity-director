from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTests(unittest.TestCase):
    def test_public_version_references_match(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

        init_text = (ROOT / "__init__.py").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        frontend = (ROOT / "js" / "continuity_director.js").read_text(encoding="utf-8")
        release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        release_notes = ROOT / "docs" / "releases" / f"v{version}.md"

        init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
        project_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        frontend_match = re.search(r'const VER\s*=\s*"([^"]+)"', frontend)

        self.assertIsNotNone(init_match)
        self.assertIsNotNone(project_match)
        self.assertIsNotNone(frontend_match)
        self.assertEqual(init_match.group(1), version)
        self.assertEqual(project_match.group(1), version)
        self.assertEqual(frontend_match.group(1), version)
        self.assertIn(f"version-{version}-", readme)
        self.assertIn(f"continuity-director-v{version}.zip", readme)
        self.assertIn("steps.version.outputs.version", release_workflow)
        self.assertNotIn(f"continuity-director-v{version}.zip\n", release_workflow)
        self.assertTrue(release_notes.is_file())


if __name__ == "__main__":
    unittest.main()
