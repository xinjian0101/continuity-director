# v0.8.22 Bug Audit

## Audit scope

The audit covered frontend version reporting, starter-chain generation, release artifact naming, public version consistency, and existing CI checks.

## Confirmed defects

### Frontend version drift

`js/continuity_director.js` reported `0.8.20` while the canonical release was `0.8.21`.

**Impact:** the sidebar footer and about badge displayed stale maintenance information.

### Starter-chain node overlap

The starter chain used fixed coordinates and did not account for node dimensions. A real Windows ComfyUI validation screenshot reproduced severe overlap between generated nodes.

**Impact:** the one-click starter workflow was difficult to inspect and edit.

### Release artifact path drift

`.github/workflows/release.yml` hard-coded `v0.8.21` in the artifact name and ZIP path.

**Impact:** a later tag could build the correct ZIP but fail to upload it under the expected version.

## Corrections

- Added size-aware column layout based on actual node dimensions.
- Added minimum node width and height enforcement.
- Reduced starter creation to one final success notification instead of one notification per node.
- Added overlap detection to the frontend smoke test using realistic node heights.
- Added frontend version extraction to version-consistency tests.
- Made the release workflow read its artifact name and path from `VERSION`.
- Synchronized public metadata to `0.8.22`.

## Verification plan

- Python compilation.
- ComfyUI lifecycle import.
- Maintainer-health validation.
- Python 3.10, 3.11, and 3.12 unit tests.
- Frontend syntax validation.
- Main and reliability frontend smoke tests.
- Release structure and installable ZIP validation.

The public tracking record is Issue #17.
