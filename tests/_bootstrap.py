from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PACKAGE_NAME="continuity_director_testpkg"
if PACKAGE_NAME not in sys.modules:
    spec=importlib.util.spec_from_file_location(PACKAGE_NAME,ROOT/"__init__.py",submodule_search_locations=[str(ROOT)])
    if spec is None or spec.loader is None: raise RuntimeError("Unable to load Continuity Director package")
    module=importlib.util.module_from_spec(spec); sys.modules[PACKAGE_NAME]=module; spec.loader.exec_module(module)
