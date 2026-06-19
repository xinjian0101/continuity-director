#!/usr/bin/env python3
"""Validate repository maintenance and community-health metadata."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    "MAINTAINERS.md",
    "GOVERNANCE.md",
    "ROADMAP.md",
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/INTERFACE.md",
    "docs/ECOSYSTEM.md",
    "docs/ADOPTION.md",
    "docs/RELEASING.md",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/adoption_report.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def read_text(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def collect_checks(root: Path = ROOT) -> list[Check]:
    checks: list[Check] = []

    missing = [item for item in REQUIRED_FILES if not (root / item).is_file()]
    checks.append(Check(
        "required_files",
        not missing,
        "all required files are present" if not missing else f"missing: {', '.join(missing)}",
    ))

    readme = read_text(root, "README.md")
    readme_links = (
        "MAINTAINERS.md",
        "GOVERNANCE.md",
        "ROADMAP.md",
        "docs/ECOSYSTEM.md",
        "docs/ADOPTION.md",
    )
    checks.append(Check(
        "readme_stewardship_links",
        all(item in readme for item in readme_links),
        "README links stewardship and ecosystem documents",
    ))

    checks.append(Check(
        "codeowners",
        "@xinjian0101" in read_text(root, ".github/CODEOWNERS"),
        "primary maintainer is declared in CODEOWNERS",
    ))

    maintainers = read_text(root, "MAINTAINERS.md")
    checks.append(Check(
        "maintainer_responsibilities",
        all(item in maintainers for item in ("Primary maintainer", "issue triage", "releases", "security")),
        "maintainer responsibilities are documented",
    ))

    governance = read_text(root, "GOVERNANCE.md")
    checks.append(Check(
        "governance_process",
        all(item in governance for item in ("Issue triage", "Pull-request review", "Releases", "Security")),
        "governance covers triage, review, releases, and security",
    ))

    security = read_text(root, "SECURITY.md").lower()
    checks.append(Check(
        "security_reporting",
        "supported versions" in security and "private vulnerability" in security,
        "security policy defines support and private reporting",
    ))

    release_workflow = read_text(root, ".github/workflows/release.yml")
    checks.append(Check(
        "release_automation",
        all(item in release_workflow for item in ('tags: ["v*"]', "build_release.py", "upload-artifact")),
        "tag-triggered release packaging is configured",
    ))

    dependabot = read_text(root, ".github/dependabot.yml")
    checks.append(Check(
        "action_dependency_updates",
        'package-ecosystem: "github-actions"' in dependabot and 'interval: "weekly"' in dependabot,
        "weekly GitHub Actions updates are configured",
    ))

    form_paths = (
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/adoption_report.yml",
    )
    forms_valid = all(
        all(key in read_text(root, path) for key in ("name:", "description:", "body:"))
        for path in form_paths
    )
    checks.append(Check(
        "structured_issue_forms",
        forms_valid,
        "bug, feature, and adoption forms are structured",
    ))

    adoption = read_text(root, "docs/ADOPTION.md")
    checks.append(Check(
        "honest_adoption_metrics",
        "does not include telemetry" in adoption and "verifiable source" in adoption,
        "adoption policy rejects unverifiable usage claims",
    ))

    return checks


def build_report(root: Path = ROOT) -> dict[str, object]:
    checks = collect_checks(root)
    passed = sum(item.passed for item in checks)
    return {
        "project": "continuity-director",
        "passed": passed,
        "total": len(checks),
        "healthy": passed == len(checks),
        "checks": [asdict(item) for item in checks],
    }


def render_text(report: dict[str, object]) -> str:
    lines = [f"Project health: {report['passed']}/{report['total']} checks passed"]
    for item in report["checks"]:
        marker = "PASS" if item["passed"] else "FAIL"
        lines.append(f"[{marker}] {item['name']}: {item['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    report = build_report(args.root.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else render_text(report))
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
