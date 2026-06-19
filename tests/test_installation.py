from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallationTests(unittest.TestCase):
    def test_lifecycle_smoke_script(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smoke_import.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("ComfyUI lifecycle smoke passed", result.stdout)

    def test_frontend_directory_exists(self):
        self.assertTrue((ROOT / "js" / "continuity_director.js").is_file())
        self.assertTrue((ROOT / "js" / "continuity_director.css").is_file())


if __name__ == "__main__":
    unittest.main()
