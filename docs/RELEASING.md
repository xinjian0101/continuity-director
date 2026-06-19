# Release Process

This document defines the release workflow for Continuity Director.

## Version source

`VERSION` is the canonical public version and release trigger. The same value must appear in `__init__.py`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, and `docs/releases/v<version>.md`. The unit suite rejects inconsistent public version references.

## Release readiness

A release candidate must satisfy:

- CI passes on Python 3.10, 3.11, and 3.12.
- ComfyUI lifecycle import succeeds.
- Unit and frontend smoke tests pass.
- Release validation and installable ZIP validation pass.
- Maintainer-health checks pass.
- Public node identifiers and schema compatibility are reviewed.
- User-visible changes are documented in `CHANGELOG.md`.
- Supported-version, upgrade, and limitation notes are current.

## Automated patch release

1. Resolve or explicitly defer release-blocking Issues.
2. Update `VERSION` and all validated public references in a pull request.
3. Add `docs/releases/v<version>.md`.
4. Run the full validation sequence from `README.md`.
5. Merge only after the Python 3.10–3.12 CI matrix passes.
6. The `Publish release` workflow runs automatically on `main`.
7. The workflow validates the repository, builds the installable ZIP, creates a SHA-256 checksum, creates the `v<version>` tag, and publishes a GitHub prerelease.
8. Verify the release page and perform a clean installation from the published ZIP.
9. Record real compatibility results in the linked roadmap Issue.

## Manual recovery

The release workflow can also be started from the Actions page. If publication fails after validation, correct the workflow or repository state through a pull request and rerun it. Do not silently replace an already published release.

## Version policy

- Patch releases fix defects, improve compatibility, or strengthen documentation and reliability without intentional breaking changes.
- Minor releases may add nodes or schema capabilities while preserving migration paths.
- Breaking changes require explicit migration documentation and a major-version decision.

## Rollback

If a release artifact is defective, mark the release notes clearly, keep the prior known-good release available, open a public corrective Issue, and prepare a tested patch release.
