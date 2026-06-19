from __future__ import annotations
import ast
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=["__init__.py","nodes.py","continuity_core.py","production_core.py","runtime_core.py","collaboration_core.py","js/continuity_director.js","js/continuity_director.css","pyproject.toml","README.md","LICENSE"]
def fail(message): raise SystemExit(f"release validation failed: {message}")
for path in REQUIRED:
    if not (ROOT/path).is_file(): fail(f"missing {path}")
for path in ROOT.glob("*.py"): ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
if 'WEB_DIRECTORY = "./js"' not in (ROOT/"__init__.py").read_text(encoding="utf-8"): fail("WEB_DIRECTORY is not exported")
text=(ROOT/"nodes.py").read_text(encoding="utf-8")
registered=set(re.findall(r'"(CD[A-Za-z0-9]+)"\s*:\s*CD[A-Za-z0-9]+',text))
if len(registered)!=14: fail(f"expected 14 registered nodes, found {len(registered)}")
storyboard=json.loads((ROOT/"examples/starter_storyboard.json").read_text(encoding="utf-8"))
if not isinstance(storyboard.get("shots"),list) or not storyboard["shots"]: fail("starter storyboard has no shots")
js=(ROOT/"js/continuity_director.js").read_text(encoding="utf-8")
for item in ("app.registerExtension","registerSidebarTab","bilingual","CDProjectLock"):
    if item not in js: fail(f"frontend is missing {item}")
print("release validation passed: 14 nodes, bilingual dashboard, examples, and package metadata")
