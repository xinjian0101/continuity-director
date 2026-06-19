## Summary

Describe the problem and the implemented change.

## Scope

- Area:
- User-visible impact:
- Workflow or schema impact:

## Validation

- [ ] `python -m compileall -q .`
- [ ] `python -m unittest discover -s tests -p "test_*.py"`
- [ ] `python scripts/validate_release.py`
- [ ] Existing workflows remain compatible.
- [ ] New interface text supports English, 中文, and bilingual mode.
- [ ] Documentation and changelog are updated when required.
- [ ] No credentials, personal data, or private production assets are included.

## Screenshots or logs

Add sanitized evidence when the change affects the interface or runtime behavior.

## Risks and rollback

Describe possible regressions and the rollback path.
