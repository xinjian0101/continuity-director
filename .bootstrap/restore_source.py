from __future__ import annotations

import base64
import codecs
import hashlib
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / ".bootstrap"
ARCHIVE = Path("/tmp/continuity-director-v0.7.0.tar.xz")
SOURCE = Path("/tmp/continuity-source")
EXPECTED_SHA256 = "2070bfb77fbfbdb95ffc2f2f2f335dddc9ddbff6d0a409e775b7ce6d968967a2"
PARTS = [
    ("archive-00.txt", False), ("archive-01.txt", False), ("archive-02.txt", False),
    ("archive-03a.rot13", True), ("archive-03b.rot13", True),
    ("archive-03c.rot13", True), ("archive-03d.rot13", True),
    ("archive-04.txt", False), ("archive-05.txt", False),
    ("archive-06a.rot13", True), ("archive-06b.rot13", True),
    ("archive-06c.rot13", True), ("archive-06d.rot13", True),
    ("archive-07a.rot13", True), ("archive-07b.rot13", True),
    ("archive-07c.rot13", True), ("archive-07d.rot13", True),
    ("archive-08.txt", False),
]


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    encoded = []
    for name, rot13 in PARTS:
        value = (BOOTSTRAP / name).read_text(encoding="utf-8").strip()
        encoded.append(codecs.decode(value, "rot_13") if rot13 else value)
    archive = base64.b64decode("".join(encoded), validate=True)
    digest = hashlib.sha256(archive).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"archive digest mismatch: {digest}")
    ARCHIVE.write_bytes(archive)
    print(f"archive verified: {digest}")

    shutil.rmtree(SOURCE, ignore_errors=True)
    SOURCE.mkdir(parents=True)
    with tarfile.open(ARCHIVE, mode="r:xz") as bundle:
        bundle.extractall(SOURCE, filter="data")

    run(sys.executable, "-m", "compileall", "-q", ".", cwd=SOURCE)
    run("node", "--check", "js/continuity_director.js", cwd=SOURCE)
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", cwd=SOURCE)
    run(sys.executable, "scripts/validate_release.py", cwd=SOURCE)

    run("rsync", "-a", "--delete", "--exclude", ".git", f"{SOURCE}/", f"{ROOT}/")
    run("git", "config", "user.name", "github-actions[bot]", cwd=ROOT)
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=ROOT)
    run("git", "add", "-A", cwd=ROOT)
    run("git", "commit", "-m", "chore: restore complete v0.7.0 source tree", cwd=ROOT)
    run("git", "push", "origin", "HEAD:restore-source-v070", cwd=ROOT)


if __name__ == "__main__":
    main()
