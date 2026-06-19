from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARDENING_MODULES = [
    "strict_json_core.py",
    "lock_integrity_core.py",
    "payload_governance_core.py",
    "storyboard_hardening_core.py",
    "production_quality_core.py",
    "runtime_hardening_core.py",
    "merge_hardening_core.py",
    "validation_hardening_core.py",
]
REQUIRED = [
    "VERSION",
    "__init__.py",
    "nodes.py",
    "extended_nodes.py",
    "environment_nodes.py",
    "continuity_core.py",
    "production_core.py",
    "runtime_core.py",
    "collaboration_core.py",
    "validation_core.py",
    *HARDENING_MODULES,
    "js/continuity_director.js",
    "js/reliability_panel.js",
    "js/continuity_director.css",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "LICENSE",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/workflows/publish.yml",
]


def fail(message: str) -> None:
    raise SystemExit(f"release validation failed: {message}")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


for path in REQUIRED:
    candidate = ROOT / path
    if not candidate.is_file() or candidate.is_symlink():
        fail(f"missing or unsafe {path}")

version = read("VERSION").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    fail(f"invalid VERSION value: {version!r}")

python_files = sorted(list(ROOT.glob("*.py")) + list((ROOT / "scripts").glob("*.py")))
for path in python_files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

for path in HARDENING_MODULES:
    source = read(path)
    if "class " not in source or len(source.splitlines()) < 20:
        fail(f"hardening module appears incomplete: {path}")

if (ROOT / ".bootstrap").exists() and any((ROOT / ".bootstrap").iterdir()):
    fail("legacy bootstrap artifacts remain")

spec = importlib.util.spec_from_file_location("continuity_director_release", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
if spec is None or spec.loader is None:
    fail("unable to import package")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

if getattr(module, "__version__", None) != version:
    fail("Python package version does not match VERSION")
if len(module.NODE_CLASS_MAPPINGS) != 20:
    fail(f"expected 20 registered nodes, found {len(module.NODE_CLASS_MAPPINGS)}")
if set(module.NODE_CLASS_MAPPINGS) != set(module.NODE_DISPLAY_NAME_MAPPINGS):
    fail("display mappings do not match node mappings")

for node_name, node_class in module.NODE_CLASS_MAPPINGS.items():
    if not callable(getattr(node_class, "INPUT_TYPES", None)):
        fail(f"{node_name} is missing INPUT_TYPES")
    for attribute in ("FUNCTION", "RETURN_TYPES", "CATEGORY"):
        if not getattr(node_class, attribute, None):
            fail(f"{node_name} is missing {attribute}")
    function_name = getattr(node_class, "FUNCTION")
    if not callable(getattr(node_class, function_name, None)):
        fail(f"{node_name} FUNCTION does not resolve to a callable")
    if not (ROOT / "js" / "docs" / f"{node_name}.md").is_file():
        fail(f"missing fallback docs for {node_name}")

pyproject = read("pyproject.toml")
project_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
if not project_match or project_match.group(1) != version:
    fail("pyproject version does not match VERSION")

frontend = read("js/continuity_director.js")
frontend_match = re.search(r'const VER\s*=\s*"([^"]+)"', frontend)
if not frontend_match or frontend_match.group(1) != version:
    fail("frontend version does not match VERSION")

readme = read("README.md")
if f"version-{version}-" not in readme or f"continuity-director-v{version}.zip" not in readme:
    fail("README release references do not match VERSION")
if not (ROOT / "docs" / "releases" / f"v{version}.md").is_file():
    fail(f"missing release notes for v{version}")

release_workflow = read(".github/workflows/release.yml")
if "steps.version.outputs.version" not in release_workflow:
    fail("release workflow does not derive artifact paths from VERSION")
publish_workflow = read(".github/workflows/publish.yml")
for marker in ("scripts/build_release.py", "sha256sum", "softprops/action-gh-release@v2"):
    if marker not in publish_workflow:
        fail(f"publish workflow is missing {marker}")

storyboard = json.loads(read("examples/starter_storyboard.json"))
if not isinstance(storyboard.get("shots"), list) or not storyboard["shots"]:
    fail("starter storyboard has no shots")
for file_name in ("continuity_director.js", "reliability_panel.js"):
    source = read(f"js/{file_name}")
    if "app.registerExtension" not in source:
        fail(f"{file_name} does not register an extension")
    if "console.error" not in source:
        fail(f"{file_name} has no explicit frontend failure reporting")

print(f"release validation passed: v{version}, 20 nodes, {len(HARDENING_MODULES)} hardening modules, workflows, docs, and package metadata")
