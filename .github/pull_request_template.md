## Summary

Describe the change and the production problem it solves.

## Change type

- [ ] Bug fix
- [ ] New node or production capability
- [ ] Dashboard or localization change
- [ ] Reliability or packaging change
- [ ] Documentation only
- [ ] Breaking change with migration support

## Validation

- [ ] `python -m compileall -q .`
- [ ] `python scripts/smoke_import.py`
- [ ] `PYTHONPATH=tests python -m unittest discover -s tests -p "test_*.py"`
- [ ] `python scripts/validate_release.py`
- [ ] `python scripts/build_release.py --check`
- [ ] Frontend smoke tests run when JavaScript changed

## Compatibility

- [ ] Public node identifiers remain stable, or a migration path is included.
- [ ] Stored workflow keys and schemas remain compatible, or changes are documented.
- [ ] New user-facing text supports English, Simplified Chinese, and bilingual mode.
- [ ] No credentials, private production assets, telemetry, or executable imported configuration are included.

## Screenshots or workflow example

Add screenshots for interface changes or a minimized workflow/JSON example for behavioral changes.

## Documentation

List updated README, help pages, examples, architecture notes, or changelog entries.
