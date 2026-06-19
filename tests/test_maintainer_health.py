import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MaintainerHealthTests(unittest.TestCase):
    def test_repository_health_report_passes(self):
        result = subprocess.run(
            [sys.executable, "scripts/maintainer_health.py", "--format", "json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["healthy"])
        self.assertEqual(payload["passed"], payload["total"])
        self.assertGreaterEqual(payload["total"], 10)


if __name__ == "__main__":
    unittest.main()
