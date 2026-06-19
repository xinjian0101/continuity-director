# Continuity Director

A ComfyUI extension for deterministic AI-video continuity, orchestration, quality control, post-production governance, and multi-user collaboration.

Version **0.7.0** ships **95 nodes** and Manifest Schema **1.6**.

## Main capabilities

- Project, character, cast, scene, shot, state, seed, and reference-frame locks.
- Batch direction, deterministic takes, dependency graphs, persistent queues, leases, retries, and recovery.
- Media probing, frame extraction, technical QC, external metric normalization, boundary checks, and assembly.
- Quality gates, best-take selection, targeted remakes, version snapshots, diffs, rollback, and artifact lineage.
- Role-based collaboration, edit locks, approvals, change requests, tamper-evident audit logs, and release gates.
- Distributed worker registration, heartbeats, capability matching, and capacity-aware scheduling.
- Environment lockfiles, compatibility matrices, template manifest validation, publisher trust policies, fault injection, and replay comparison.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/xinjian0101/continuity-director.git ComfyUI-ContinuityDirector
```

Restart ComfyUI. Core features have no third-party Python runtime dependencies. FFmpeg/FFprobe are optional system tools required only for media probing, extraction, and assembly nodes.

## Verification

```bash
python -m compileall -q .
python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
```

The current regression suite contains 135 tests.

## Security boundaries

- External JSON is treated as data, not executable code.
- API keys, tokens, passwords, cookies, and authorization fields are removed from portable bundles.
- ZIP paths and SHA-256 digests are validated.
- Template trust is based on explicit allow/deny policies and pinned publisher digests, not remote execution.

## License

MIT.
