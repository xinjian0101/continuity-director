<p align="center"><img src="assets/banner.svg" alt="Continuity Director" width="100%"></p>
<p align="center"><strong>Deterministic continuity planning, quality control, and production reliability for ComfyUI video workflows.</strong></p>
<p align="center"><img alt="Version" src="https://img.shields.io/badge/version-0.8.20-2563eb"> <img alt="Nodes" src="https://img.shields.io/badge/nodes-20-0f766e"> <img alt="Interface" src="https://img.shields.io/badge/interface-English%20%7C%20中文%20%7C%20Bilingual-7c3aed"> <img alt="License" src="https://img.shields.io/badge/license-MIT-f97316"></p>

# Continuity Director

Continuity Director is an installable ComfyUI custom-node package that turns project rules, identity constraints, scenes, shots, references, quality metrics, execution dependencies, approvals, retry plans, checkpoints, environment records, and exports into structured production data.

## v0.8.20

- 20 registered ComfyUI nodes
- Native production dashboard plus reliability sidebar
- English, Simplified Chinese, and bilingual UI
- One-click connected starter chain
- Deterministic storyboard-to-Take expansion
- Quality gates, Take ranking, and exact-path continuity reports
- Dependency-safe execution waves and resumable checkpoints
- Package hash verification and schema migration
- Bounded retry policies and idempotency keys
- Runtime environment locks
- Three-way merge, audit events, and portable export packages
- English and Chinese node help pages
- Python 3.10–3.12 CI, backend lifecycle smoke tests, frontend headless tests, and installable ZIP validation
- No mandatory third-party Python dependencies

## Installation

```bash
git clone https://github.com/xinjian0101/continuity-director.git ComfyUI-ContinuityDirector
```

Place the folder inside `ComfyUI/custom_nodes`, restart ComfyUI, and search for `CD ·` or `Continuity Director`.

## Validation

```bash
python -m compileall -q .
python scripts/smoke_import.py
PYTHONPATH=tests python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
python scripts/build_release.py --check
node tests/frontend_smoke.mjs
node tests/reliability_frontend_smoke.mjs
```

## Build installable ZIP

```bash
python scripts/build_release.py
```

The archive is created at `dist/continuity-director-v0.8.20.zip` with the correct top-level ComfyUI custom-node folder.

## Limitations

The plugin controls production data and decisions; it does not guarantee pixel-perfect model output. Actual visual consistency still depends on the video model, reference material, sampler, motion range, and generation environment.

## License

MIT.
