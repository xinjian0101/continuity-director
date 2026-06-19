from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = "ComfyUI-ContinuityDirector"
EXCLUDED_PARTS = {".git", ".github", "tests", "dist", "__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
REQUIRED = {
    "VERSION",
    "__init__.py",
    "nodes.py",
    "extended_nodes.py",
    "environment_nodes.py",
    "js/continuity_director.js",
    "pyproject.toml",
    "LICENSE",
}


def read_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise SystemExit(f"invalid VERSION value: {version!r}")
    return version


VERSION = read_version()


def default_output() -> Path:
    return ROOT / "dist" / f"continuity-director-v{VERSION}.zip"


def release_files() -> list[Path]:
    files: list[Path] = []
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
    if any(name.startswith("dist/") for name in names):
        raise SystemExit("release output directory must not be packaged")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output: Path) -> dict[str, object]:
    files = release_files()
    validate(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            archive.write(ROOT / relative, f"{PACKAGE_DIR}/{relative.as_posix()}")
    return {
        "version": VERSION,
        "output": str(output),
        "file_count": len(files),
        "size_bytes": output.stat().st_size,
        "sha256": sha256(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=default_output())
    args = parser.parse_args()
    files = release_files()
    validate(files)
    if args.check:
        print(json.dumps({"valid": True, "version": VERSION, "file_count": len(files)}, sort_keys=True))
        return
    print(json.dumps(build(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
