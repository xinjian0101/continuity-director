# Support

## Before requesting help

Run the validation commands from the repository root:

```bash
python scripts/smoke_import.py
PYTHONPATH=tests python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
```

Confirm that the plugin directory is located at:

```text
ComfyUI/custom_nodes/ComfyUI-ContinuityDirector
```

Restart ComfyUI after installing or updating the plugin.

## Common problems

### Nodes do not appear

- Confirm that `__init__.py` is directly inside the plugin folder.
- Check the ComfyUI terminal for a Python import traceback.
- Remove duplicate copies of the plugin from `custom_nodes`.
- Run `python scripts/smoke_import.py` from the plugin root.

### Sidebar does not appear

- Update the ComfyUI frontend.
- Check the browser developer console for errors mentioning `continuity_director.js` or `reliability_panel.js`.
- Confirm that the package exports `WEB_DIRECTORY = "./js"`.
- Try a hard browser refresh after restarting ComfyUI.

### A workflow loads with missing nodes

- Pull the latest repository version.
- Confirm that all node identifiers beginning with `CD` are registered.
- Include the missing node identifier in the bug report.

### Release ZIP contains unexpected files

Run:

```bash
python scripts/build_release.py --check
python scripts/build_release.py
```

The builder excludes Git metadata, tests, caches, CI files, and previous `dist` output.

## Filing a useful bug report

Use the repository bug-report form and include:

- Continuity Director version or commit SHA
- ComfyUI version
- ComfyUI frontend version
- Python version and operating system
- Relevant console traceback
- Minimal workflow or input JSON with private data removed
- Expected and actual behavior

Do not include passwords, API keys, private model links, personal data, or proprietary production assets.

## Feature requests

Use the feature-request form. Describe the production problem first, then the proposed behavior. Focused proposals that preserve workflow compatibility are easier to evaluate.

## Security issues

Do not disclose exploitable security issues in a public discussion. Follow [SECURITY.md](SECURITY.md).
