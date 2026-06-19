# Governance

Continuity Director currently uses a maintainer-led governance model. The primary maintainer is listed in [MAINTAINERS.md](MAINTAINERS.md).

## Decision process

- Bugs, features, compatibility changes, and roadmap proposals should begin as GitHub Issues.
- Code and documentation changes should be delivered through pull requests.
- Decisions prioritize user safety, deterministic behavior, workflow compatibility, maintainability, and ecosystem value.
- Material breaking changes require migration notes, tests, changelog entries, and a documented compatibility decision.
- When reasonable alternatives exist, the maintainer records the selected approach and trade-offs in the Issue or pull request.

## Issue triage

Issues are classified by impact and work type:

- `bug`: confirmed or suspected incorrect behavior.
- `enhancement`: new capability or material improvement.
- `documentation`: user, contributor, architecture, or support documentation.
- `help wanted`: work where community participation is useful.
- `good first issue`: bounded work suitable for a new contributor.
- `question`: support or usage clarification.

A triaged issue should have a clear problem statement, reproducible evidence when applicable, and a next action such as investigation, implementation, documentation, or closure.

## Pull-request review

Pull requests are evaluated for:

1. Correctness and test coverage.
2. Compatibility with existing node identifiers, workflows, and data schemas.
3. Security boundaries for imported JSON, files, and packaged data.
4. English, Simplified Chinese, and bilingual interface behavior when UI text changes.
5. Documentation and changelog completeness.
6. Release-package validity.

The primary maintainer may request changes, close an out-of-scope proposal, or defer work to the roadmap.

## Releases

Release management follows [docs/RELEASING.md](docs/RELEASING.md). Releases are built through GitHub Actions, validated against supported Python versions, and documented in `CHANGELOG.md`.

## Security

Potential vulnerabilities must follow [SECURITY.md](SECURITY.md). Security-sensitive details should not be placed in public Issues before a fix or disclosure plan is ready.

## Changes to governance

Governance changes require a public pull request. The rationale and effect on contributors or users must be described in that pull request.
