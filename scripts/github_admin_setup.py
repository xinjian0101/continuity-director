#!/usr/bin/env python3
"""Apply supported GitHub repository settings with GitHub CLI."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess

OWNER = "xinjian0101"
REPO = "continuity-director"
DESCRIPTION = "ComfyUI custom nodes for deterministic AI video continuity, quality control, batch reliability, and reproducible production workflows."
TOPICS = [
    "comfyui",
    "comfyui-custom-nodes",
    "ai-video",
    "video-workflow",
    "workflow-automation",
    "continuity",
    "quality-control",
    "reproducibility",
    "batch-processing",
    "production-tools",
    "custom-nodes",
    "python",
    "open-source",
]


def call_api(endpoint: str, method: str = "GET", payload: dict | None = None):
    command = ["gh", "api", endpoint, "--method", method]
    input_text = None
    if payload is not None:
        command.extend(["--input", "-"])
        input_text = json.dumps(payload)
    result = subprocess.run(command, input=input_text, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def ruleset_payload() -> dict:
    return {
        "name": "Protect main",
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "allowed_merge_methods": ["squash"],
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_approving_review_count": 0,
                    "required_review_thread_resolution": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": "validate (3.10)"},
                        {"context": "validate (3.11)"},
                        {"context": "validate (3.12)"},
                    ],
                },
            },
        ],
    }


def plan() -> dict:
    return {
        "profile": {"bio": "Maintainer of Continuity Director | ComfyUI and AI video workflow tooling"},
        "repository": {
            "description": DESCRIPTION,
            "has_issues": True,
            "allow_squash_merge": True,
            "allow_merge_commit": False,
            "allow_rebase_merge": False,
            "allow_auto_merge": True,
            "delete_branch_on_merge": True,
        },
        "topics": {"names": TOPICS},
        "ruleset": ruleset_payload(),
    }


def apply_settings(update_profile: bool) -> None:
    if shutil.which("gh") is None:
        raise RuntimeError("Install GitHub CLI and run `gh auth login` first.")

    settings = plan()
    endpoint = f"repos/{OWNER}/{REPO}"
    if update_profile:
        call_api("user", "PATCH", settings["profile"])
    call_api(endpoint, "PATCH", settings["repository"])
    call_api(f"{endpoint}/topics", "PUT", settings["topics"])
    call_api(f"{endpoint}/private-vulnerability-reporting", "PUT")

    existing = call_api(f"{endpoint}/rulesets") or []
    matched = next((item for item in existing if item.get("name") == "Protect main"), None)
    if matched:
        call_api(f"{endpoint}/rulesets/{matched['id']}", "PUT", settings["ruleset"])
    else:
        call_api(f"{endpoint}/rulesets", "POST", settings["ruleset"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-profile", action="store_true")
    args = parser.parse_args()

    print(json.dumps(plan(), indent=2, ensure_ascii=False))
    if not args.apply:
        print("Dry run only. Re-run with --apply after `gh auth login`.")
        return 0

    apply_settings(update_profile=not args.skip_profile)
    print("GitHub repository settings applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
