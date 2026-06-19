# Continuity Director

<p align="center">
  <strong>Production-grade continuity control, orchestration, quality review, and collaboration for ComfyUI video workflows.</strong>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.8.0--preview-2563eb">
  <img alt="ComfyUI" src="https://img.shields.io/badge/ComfyUI-custom%20nodes-7c3aed">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776ab">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-16a34a">
  <img alt="Interface" src="https://img.shields.io/badge/interface-English%20%7C%20中文%20%7C%20Bilingual-f97316">
</p>

<p align="center">
  <a href="#overview">Overview</a> ·
  <a href="#core-capabilities">Capabilities</a> ·
  <a href="#workflow">Workflow</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#interface-languages">Languages</a> ·
  <a href="#documentation">Documentation</a>
</p>

---

## Overview

Continuity Director is a ComfyUI extension for repeatable AI video production. It does not replace a video model. Instead, it turns characters, costumes, props, locations, shots, seeds, reference frames, task queues, approvals, and runtime environments into structured production data.

The goal is to reduce character drift, cross-shot inconsistency, failed handoffs, and collaboration conflicts while keeping every production decision traceable and reproducible.

> **Important:** No workflow manager can guarantee pixel-perfect continuity. Final output still depends on the selected model, reference quality, model version, sampler, motion range, and platform-level randomness.

## Core capabilities

| Area | What it provides |
|---|---|
| Continuity locks | Stable project, character, cast, costume, prop, location, shot, state, and seed definitions |
| Batch directing | Storyboard JSON ingestion, continuous shot chains, and controlled take variants |
| Runtime orchestration | Dependency DAGs, parallel execution waves, persistent queues, leases, retries, and recovery |
| Reference management | Reference-frame lifecycle, automatic selection, and first/last-frame handoff |
| Quality loop | Technical checks, declarative identity metrics, boundary continuity, take ranking, and targeted regeneration |
| Post-production governance | Video probing, frame extraction, assembly, snapshots, diffs, rollback, and lineage tracking |
| Team collaboration | Role-based access, edit locks, review workflows, change requests, and generation gates |
| Distributed execution | Worker registration, heartbeat monitoring, capability matching, and capacity-aware scheduling |
| Supply-chain safety | Environment lockfiles, package verification, publisher trust, and secret-free configuration bundles |
| Reproducibility | Audit hash chains, fault injection, regression baselines, and run-to-run comparison |

**v0.7.0 baseline:** 95 ComfyUI nodes, Manifest Schema 1.6, and 135 regression tests.

## Workflow

```mermaid
flowchart LR
    A[Project / Cast / Location Locks] --> B[Batch Director / Take Variants]
    B --> C[Reference Library / Model Profile / Workflow Template]
    C --> D[Collaboration / Edit Lock / Review]
    D --> E[Compatibility / Environment Lock / Generation Gate]
    E --> F[Execution Plan / Persistent Queue / Worker Scheduling]
    F --> G[Generation / Asset Index / Technical QC]
    G --> H[Boundary Continuity / Targeted Regeneration]
    H --> I[Final Assembly / Audit / Snapshot / Replay]
```

## Installation

Clone the repository into `ComfyUI/custom_nodes`:

```bash
git clone https://github.com/xinjian0101/continuity-director.git ComfyUI-ContinuityDirector
```

Or extract a release archive to:

```text
ComfyUI/custom_nodes/ComfyUI-ContinuityDirector
```

Restart ComfyUI after installation.

The core runtime is designed without mandatory third-party Python dependencies. Video probing, frame extraction, and assembly require local `FFmpeg` and `FFprobe` binaries.

## Interface languages

The v0.8 interface specification supports three display modes:

| Mode | Behavior |
|---|---|
| English | All labels, descriptions, status messages, and validation feedback are shown in English |
| 中文 | All user-facing interface text is shown in Simplified Chinese |
| Bilingual | English is shown as the primary label with Simplified Chinese as supporting text |

Language selection is intended to be persistent per browser and must not modify workflow data or node identifiers.

See [Interface and localization](docs/INTERFACE.md) for the implementation rules.

## Collaboration model

Supported production roles:

```text
owner / director / editor / reviewer / operator / viewer
```

The collaboration layer is designed to:

1. Acquire time-limited locks for shots, scenes, or final assemblies.
2. Prevent stale pages from overwriting newer revisions.
3. Submit, approve, reject, revoke, or request changes to revisions.
4. Perform three-way JSON merges and report exact conflict paths.
5. Record collaboration events in a SHA-256 audit chain.
6. Open the generation gate only when review, lock, environment, and audit conditions pass.

## Distributed execution

Workers may declare capabilities such as:

```json
{
  "model_profiles": ["wan", "ltxv"],
  "transports": ["local_workflow"],
  "vram_gb": 24
}
```

The scheduler can match tasks using priority, dependencies, model profile, VRAM, labels, and remaining capacity. Workers that stop reporting heartbeats are marked as `stale`.

## Local validation

```bash
python -m compileall -q .
python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Interface and localization](docs/INTERFACE.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## Project structure

```text
ComfyUI-ContinuityDirector/
├── continuity_core.py
├── production_core.py
├── runtime_core.py
├── orchestration_core.py
├── postprocess_core.py
├── collaboration_core.py
├── nodes.py
├── js/
├── examples/
├── tests/
├── scripts/
└── docs/
```

## License

Released under the [MIT License](LICENSE).
