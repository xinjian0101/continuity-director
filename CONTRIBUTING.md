# Contributing to Continuity Director

Thank you for helping improve Continuity Director. Contributions should preserve deterministic behavior, workflow compatibility, and clear production auditability.

## Before opening a change

1. Search existing issues and pull requests.
2. Keep changes focused on one problem.
3. Avoid renaming public node identifiers unless a migration path is included.
4. Do not add network calls, telemetry, API keys, or executable third-party configuration.
5. Add or update tests for behavioral changes.

## Development setup

```bash
git clone https://github.com/xinjian0101/continuity-director.git
cd continuity-director
python -m compileall -q .
python -m unittest discover -s tests -p "test_*.py"
python scripts/validate_release.py
```

## Interface requirements

User-facing interface changes must support:

- English
- Simplified Chinese
- Bilingual mode
- Persistent language preference
- Keyboard navigation
- Readable validation messages
- No localization changes to stored workflow data or node identifiers

Do not hard-code visible text inside rendering logic. Add text through the localization dictionary described in `docs/INTERFACE.md`.

## Pull request checklist

- [ ] The change has a clear scope.
- [ ] Public behavior is documented.
- [ ] Tests pass locally.
- [ ] New UI text is localized.
- [ ] Existing workflows remain compatible.
- [ ] No secrets, tokens, or personal data are included.
- [ ] The changelog is updated when appropriate.

## Commit style

Use concise conventional prefixes where practical:

```text
feat: add shot continuity warning
fix: preserve language selection after reload
docs: clarify worker scheduling
refactor: isolate localization registry
test: cover stale edit lock recovery
```

## Reporting security problems

Do not publish exploitable security details in a public issue. Follow `SECURITY.md`.
