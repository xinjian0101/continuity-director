from __future__ import annotations
import ast
import importlib.util
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=["__init__.py","nodes.py","extended_nodes.py","environment_nodes.py","continuity_core.py","production_core.py","runtime_core.py","collaboration_core.py","validation_core.py","js/continuity_director.js","js/reliability_panel.js","js/continuity_director.css","pyproject.toml","README.md","LICENSE"]
def fail(message): raise SystemExit(f"release validation failed: {message}")
for path in REQUIRED:
    if not (ROOT/path).is_file(): fail(f"missing {path}")
for path in ROOT.glob("*.py"): ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
if any((ROOT/".bootstrap").glob("*")) if (ROOT/".bootstrap").exists() else False: fail("legacy bootstrap artifacts remain")
spec=importlib.util.spec_from_file_location("continuity_director_release",ROOT/"__init__.py",submodule_search_locations=[str(ROOT)])
if spec is None or spec.loader is None: fail("unable to import package")
module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
if len(module.NODE_CLASS_MAPPINGS)!=20: fail(f"expected 20 registered nodes, found {len(module.NODE_CLASS_MAPPINGS)}")
if set(module.NODE_CLASS_MAPPINGS)!=set(module.NODE_DISPLAY_NAME_MAPPINGS): fail("display mappings do not match node mappings")
for node_name in module.NODE_CLASS_MAPPINGS:
    if not (ROOT/"js"/"docs"/f"{node_name}.md").is_file(): fail(f"missing fallback docs for {node_name}")
storyboard=json.loads((ROOT/"examples/starter_storyboard.json").read_text(encoding="utf-8"))
if not isinstance(storyboard.get("shots"),list) or not storyboard["shots"]: fail("starter storyboard has no shots")
for file_name in ("continuity_director.js","reliability_panel.js"):
    text=(ROOT/"js"/file_name).read_text(encoding="utf-8")
    if "app.registerExtension" not in text: fail(f"{file_name} does not register an extension")
print("release validation passed: 20 nodes, two frontend panels, localized docs, and package metadata")
