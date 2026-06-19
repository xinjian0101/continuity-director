from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = "ComfyUI-ContinuityDirector"
EXCLUDED_PARTS = {".git", ".github", "tests", "__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
REQUIRED = {"__init__.py", "nodes.py", "extended_nodes.py", "environment_nodes.py", "js/continuity_director.js", "pyproject.toml", "LICENSE"}


def release_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(relative)
    return sorted(files)


def validate(files: list[Path]) -> None:
    names = {path.as_posix() for path in files}
    missing = sorted(REQUIRED - names)
    if missing:
        raise SystemExit(f"release package missing: {', '.join(missing)}")
    if any(name.startswith(".bootstrap/") for name in names):
        raise SystemExit("legacy bootstrap artifacts must not be packaged")


def build(output: Path) -> dict[str, object]:
    files = release_files()
    validate(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            archive.write(ROOT / relative, f"{PACKAGE_DIR}/{relative.as_posix()}")
    return {"output": str(output), "file_count": len(files), "size_bytes": output.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "continuity-director-v0.8.20.zip")
    args = parser.parse_args()
    files = release_files()
    validate(files)
    if args.check:
        print(json.dumps({"valid": True, "file_count": len(files)}, sort_keys=True))
        return
    print(json.dumps(build(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
