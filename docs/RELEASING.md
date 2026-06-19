# Release Process

This document defines the release workflow for Continuity Director.

## Release readiness

A release candidate must satisfy:

- CI passes on Python 3.10, 3.11, and 3.12.
- ComfyUI lifecycle import succeeds.
- Unit and frontend smoke tests pass.
- Release validation and installable ZIP validation pass.
- Public node identifiers and schema compatibility are reviewed.
- User-visible changes are documented in `CHANGELOG.md`.
- Supported-version and upgrade notes are current.

## Patch release checklist

1. Resolve or explicitly defer release-blocking Issues.
2. Update version references and changelog entries.
3. Run the full local validation sequence from `README.md`.
4. Open a release pull request and allow GitHub Actions to complete.
5. Merge only after all required checks pass.
6. Create a `v*` tag to trigger the release-package workflow.
7. Verify the generated ZIP structure and SHA-256 checksum.
8. Test installation from the generated artifact in a clean custom-node directory.
9. Publish release notes with known limitations and upgrade instructions.
10. Update roadmap Issues after publication.

## Version policy

- Patch releases fix defects, improve compatibility, or strengthen documentation and reliability without intentional breaking changes.
- Minor releases may add nodes or schema capabilities while preserving migration paths.
- Breaking changes require explicit migration documentation and a major-version decision.

## Rollback

If a release artifact is defective, mark the release notes clearly, keep the prior known-good release available, open a public corrective Issue, and prepare a tested patch release. Do not silently replace published artifacts without explanation.
