# Security Policy

## Supported versions

| Version | Status |
|---|---|
| 0.8.x | Maintained preview |
| 0.7.x and earlier | Not supported |

Security fixes are prioritized for the current maintained release line. Users should update to the latest available patch before reporting an issue that may already be resolved.

## Reporting a security issue

Use GitHub private vulnerability reporting when available. Do not publish exploitable details in a public Issue before the maintainer has reviewed the report.

Include:

- Affected version or commit SHA
- Reproduction steps
- Observed and expected behavior
- Security impact
- Minimal test case or sanitized fixture
- Suggested mitigation when known

Do not include credentials, personal information, private model links, or production data.

The primary maintainer aims to acknowledge a complete private report within 72 hours. This is an operational target, not a service-level guarantee.

## Project security principles

- Project bundles must not contain API keys or credentials.
- Imported manifests must be validated before use.
- External JSON must remain declarative data.
- File operations must remain inside approved project directories.
- Audit-chain, package-integrity, and revision checks must fail safely.
- Release packages must be reproducible and validated before publication.
- GitHub Actions dependencies are reviewed through Dependabot updates.

## Security boundaries

External models, operating systems, FFmpeg builds, ComfyUI installations, and third-party custom nodes have their own security boundaries. Integrity hashes detect changes but do not provide authorization or sandbox untrusted software.
