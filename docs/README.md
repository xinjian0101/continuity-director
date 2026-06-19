# Continuity Director Documentation

This directory is the documentation hub for users, workflow authors, and contributors.

## Start here

| Goal | Document |
|---|---|
| Install and run the plugin | [Repository README](../README.md#installation) |
| Understand the production pipeline | [Repository README](../README.md#production-workflow) |
| Review all nodes | [Repository README](../README.md#node-map) |
| Learn the internal architecture | [Architecture](ARCHITECTURE.md) |
| Implement interface changes | [Interface and localization](INTERFACE.md) |
| Troubleshoot an installation | [Support](../SUPPORT.md) |
| Contribute code or documentation | [Contributing](../CONTRIBUTING.md) |
| Report a security issue | [Security policy](../SECURITY.md) |

## User workflow

1. Install the repository under `ComfyUI/custom_nodes`.
2. Restart ComfyUI.
3. Open the Continuity Director sidebar.
4. Add the connected starter chain.
5. Configure continuity locks.
6. Build a manifest and expand storyboard Takes.
7. Apply execution, quality, and reliability controls.
8. Export and verify the production package.

## Developer validation

```bash
python -m compileall -q .
python scripts/smoke_import.py
PYTHONPATH=tests python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
python scripts/build_release.py --check
node tests/frontend_smoke.mjs
node tests/reliability_frontend_smoke.mjs
```

## Documentation rules

- Public-facing repository documentation is written in English.
- Node help pages may include English and Simplified Chinese variants.
- Public node identifiers and stored workflow keys must not be translated.
- Behavior changes require matching tests and changelog entries.
- Examples must not contain credentials, private assets, or personal information.
