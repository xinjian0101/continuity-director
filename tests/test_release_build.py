from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location("continuity_director_build_release", ROOT / "scripts" / "build_release.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load release builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseBuildTests(unittest.TestCase):
    def test_repeated_build_does_not_nest_previous_archive(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "continuity-director.zip"
            first = builder.build(output)
            second = builder.build(output)
            self.assertGreater(first["file_count"], 0)
            self.assertEqual(first["file_count"], second["file_count"])
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            self.assertFalse(any("/dist/" in name for name in names))
            self.assertFalse(any(name.endswith(".zip") for name in names))


if __name__ == "__main__":
    unittest.main()
