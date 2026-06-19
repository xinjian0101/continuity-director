<p align="center">
  <img src="assets/banner.svg" alt="Continuity Director" width="100%">
</p>

<p align="center"><strong>Deterministic continuity planning, quality control, and production governance for ComfyUI video workflows.</strong></p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.8.0-2563eb">
  <img alt="Nodes" src="https://img.shields.io/badge/nodes-14-0f766e">
  <img alt="Interface" src="https://img.shields.io/badge/interface-English%20%7C%20中文%20%7C%20Bilingual-7c3aed">
  <img alt="Tests" src="https://img.shields.io/badge/tests-13%20passing-16a34a">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-f97316">
</p>

# Continuity Director

Continuity Director is an installable ComfyUI custom-node package for repeatable AI video production. It turns project rules, character identity, scene state, shot instructions, reference handoffs, quality metrics, execution dependencies, approvals, and export data into deterministic JSON records with SHA-256 hashes.

It does not replace a video model and cannot guarantee pixel-perfect identity. It controls inputs and decisions so drift and failed handoffs can be detected and corrected systematically.

## Included

- 14 registered ComfyUI nodes
- Modern native sidebar production dashboard
- Floating compatibility panel for older frontends
- English, Simplified Chinese, and bilingual interface modes
- Persistent browser language preference
- Quick-add node library and one-click connected starter chain
- Storyboard-to-Take expansion
- Reference-frame handoff records
- Weighted Take ranking and quality gates
- Dependency-safe execution waves
- Exact-path continuity reports
- Three-way collaborative JSON merge
- Hash-linked audit events
- Portable production package export
- Built-in node help pages
- Tests, release validation, and GitHub Actions CI
- No mandatory third-party Python dependencies

## Nodes

| Stage | Node | Purpose |
|---|---|---|
| Locks | `CDProjectLock` | Project title, ratio, FPS, language, and notes |
| Locks | `CDCharacterLock` | Appearance, wardrobe, forbidden changes, references, identity seed |
| Locks | `CDSceneLock` | Location, time, lighting, palette, and environment |
| Locks | `CDShotLock` | Prompt, camera, duration, seed, and continuity context |
| Locks | `CDManifestBuilder` | Portable production manifest |
| Directing | `CDBatchDirector` | Expand storyboard JSON into deterministic Take variants |
| Directing | `CDReferenceHandoff` | Record adjacent-shot reference transfer |
| Quality | `CDQualityGate` | Evaluate metrics against thresholds |
| Quality | `CDTakeRanker` | Weighted deterministic Take ranking |
| Quality | `CDContinuityReport` | Exact-path JSON continuity comparison |
| Runtime | `CDExecutionPlan` | Dependency-safe parallel execution waves |
| Collaboration | `CDAuditEvent` | Hash-linked production audit record |
| Collaboration | `CDThreeWayMerge` | Revision-safe JSON merge with conflict paths |
| Export | `CDExportPackage` | Hashed production package export |

## Installation

From `ComfyUI/custom_nodes`:

```bash
git clone https://github.com/xinjian0101/continuity-director.git ComfyUI-ContinuityDirector
```

Restart ComfyUI and search for `Continuity Director` or node names beginning with `CD ·`. No `pip install` step is required for v0.8.0.

## Starter workflow

1. Add Project Lock, Character Lock, and Scene Lock.
2. Connect them to Shot Lock.
3. Build a Manifest.
4. Send the manifest and storyboard JSON to Batch Director.
5. Build an Execution Plan.
6. Evaluate generated metrics with Quality Gate and Take Ranker.
7. Append an Audit Event and create an Export Package.

The sidebar action **Add starter chain** inserts and connects the primary chain automatically. Example inputs are in `examples/`.

## Validation

```bash
python -m compileall -q .
PYTHONPATH=tests python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
node --check js/continuity_director.js
```

## Compatibility

- Python 3.10+
- ComfyUI custom-node lifecycle using `NODE_CLASS_MAPPINGS`
- Frontend extension using `WEB_DIRECTORY` and `app.registerExtension`
- Native sidebar on supported ComfyUI frontend versions
- Floating compatibility panel on older frontend versions

## Security boundaries

Imported JSON is parsed only as data. Project packages do not store API keys. Hashes provide change detection, not access control. External models, custom nodes, FFmpeg builds, and operating systems remain separate trust boundaries.

## License

MIT.
