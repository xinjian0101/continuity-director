# Roadmap

This roadmap describes intended work. Priorities may change when compatibility, security, or user-reported failures require attention.

## Current status

- Release line: `0.8.x`
- Current release: `0.8.42`
- Stability: maintained preview
- Public nodes: 20
- CI: Python 3.10, 3.11, and 3.12

## Completed: v0.8.21

- Published an installable GitHub Release with notes and checksum information.
- Verified installation from the release artifact.
- Recorded Windows and current ComfyUI compatibility evidence.
- Documented workflow save/reload and sidebar behavior.

Tracking: Issues #9 and #10.

## Completed: v0.8.22

- Corrected stale frontend version reporting.
- Replaced fixed starter-chain coordinates with size-aware layout.
- Added frontend overlap regression coverage.
- Derived release artifact names from the canonical `VERSION` file.
- Published a public bug audit and maintenance record.

Tracking: Issues #17 and #19.

## Completed: v0.8.42

- Completed exactly 20 sequential hardening iterations.
- Strengthened JSON, collection, lock, storyboard, quality, ranking, dependency, migration, retry, checkpoint, hash, and environment validation.
- Added deletion-aware merge diagnostics and deterministic execution-plan behavior.
- Made release ZIP output reproducible and symlink-safe.
- Added stronger release validation and comprehensive regression coverage.
- Added failure-safe frontend storage, node creation, and starter-chain rollback.

Tracking: Issues #20 and #22, PR #21.

## v0.9.0

- Add a sanitized end-to-end workflow pack.
- Add compatibility fixtures for older payload schemas.
- Improve package verification and migration messages.
- Add machine-readable production summaries for integrations.

## Adoption work

- Accept opt-in compatibility reports.
- Publish only verified user-submitted information.
- Track release downloads after public releases are available.
- Use stars, traffic, clones, and Issues as directional signals rather than quality guarantees.

Tracking: Issue #11.

## Long-term direction

- Distribution metadata for the wider ComfyUI ecosystem.
- More model-agnostic production reliability tools.
- Community-maintained integration examples.
- Additional maintainers when sustained contribution volume warrants shared ownership.
