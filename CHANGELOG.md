# Changelog

## Unreleased

## [0.8.42] - 2026-06-19

### Fixed

- Hardened whitespace JSON parsing and expected-type diagnostics.
- Normalized and deduplicated collection inputs while preserving order.
- Corrected ignored continuity paths for list descendants.
- Added manifest lock kind, structure, and duplicate-ID validation.
- Hardened storyboard IDs, collections, references, seeds, durations, and duplicate handling.
- Rejected non-finite production metrics, thresholds, weights, and delays.
- Validated quality-gate modes and made metric checks deterministic.
- Normalized Take IDs and rejected duplicate ranking identities.
- Normalized task dependencies, rejected self-dependencies, and bounded scheduler parallelism.
- Preserved deletion semantics in three-way merge conflict reports.
- Made same-version migrations true no-ops and validated target versions.
- Prevented retry exponent overflow and malformed checkpoint state.
- Added explicit hash-format and mismatch diagnostics with constant-time comparison.
- Canonicalized environment model inventories and missing version fields.
- Made release ZIP archives reproducible and excluded symlinks and OS junk files.
- Added rollback-safe frontend node creation and protected browser-storage access.

### Added

- Exactly 20 sequential hardening commits tracked in Issue #20 and PR #21.
- Comprehensive regression tests for input, manifest, storyboard, ranking, runtime, merge, migration, retry, checkpoint, hash, and environment boundaries.
- Stronger release validation across node metadata, documentation, versions, workflows, and package files.
- Public v0.8.42 iteration log and release notes.

## [0.8.22] - 2026-06-19

### Fixed

- Replaced fixed starter-chain coordinates with a size-aware column layout so generated nodes no longer overlap.
- Synchronized the frontend sidebar and about badge with the canonical project version.
- Removed hard-coded release artifact names from the tag-triggered package workflow.
- Enforced a minimum node height when Continuity Director styling is applied.

### Added

- Frontend regression coverage that uses realistic node dimensions and rejects any overlapping starter-chain nodes.
- Frontend version matching in the public version-consistency test.
- Public bug audit and Issue #17 as maintenance evidence for the patch release.

## [0.8.21] - 2026-06-19

### Added

- Primary maintainer declaration, CODEOWNERS, governance policy, public roadmap, ecosystem-value documentation, adoption policy, release process, and code of conduct.
- Structured opt-in adoption report form.
- Automated maintainer-health validation with unit-test coverage.
- Weekly maintainer-health workflow and GitHub Actions Dependabot configuration.
- Canonical `VERSION` source, automatic prerelease publication, release notes, ZIP creation, and SHA-256 generation.
- One-command GitHub administrator setup utility.

### Changed

- Expanded the README with public stewardship, ecosystem value, dynamic activity badges, and maintenance links.
- Updated the documentation hub and security support policy.
- Added maintainer-health validation to the Python 3.10–3.12 CI matrix.

## [0.8.20] - 2026-06-19

### Added

- ComfyUI lifecycle import smoke test and installation regression suite.
- Headless tests for the main dashboard, sidebar rendering, starter chain, reliability panel, and quick-add commands.
- Package integrity verification and schema migration nodes.
- Deterministic bounded retry policy and resumable queue checkpoint nodes.
- Stable idempotency-key and reproducible environment-lock nodes.
- Official English and Chinese localized help pages for reliability nodes.
- Installable ZIP builder and release artifact workflow.

### Changed

- Increased the registered node count from 14 to 20.
- Expanded CI to Python 3.10–3.12, both frontend panels, release structure, and ZIP validation.
- Updated the primary dashboard to expose reliability nodes and v0.8.20 status.
- Redesigned the GitHub repository homepage and contribution flow.

## [0.8.0] - 2026-06-19

- First installable release with 14 nodes and bilingual production dashboard.

## [0.7.0] - 2026-06-19

- Initial repository and architecture documentation baseline.
