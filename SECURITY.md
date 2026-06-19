# Security Policy

## Supported versions

| Version | Status |
|---|---|
| 0.8.x | Preview development |
| 0.7.x | Maintained |
| Earlier | Not maintained |

## Reporting a security issue

Please use GitHub private vulnerability reporting when available. Do not include secrets, personal information, or production data in a report.

Provide the affected version, reproduction steps, observed behavior, expected behavior, and a minimal test case.

## Project security principles

- Project bundles must not contain API keys or credentials.
- Imported manifests must be validated before use.
- External JSON must remain declarative data.
- File operations must remain inside approved project directories.
- Audit-chain and revision checks must fail safely.
- Stale edit locks and malformed worker registrations must be rejected.

External models, operating systems, FFmpeg builds, ComfyUI installations, and third-party custom nodes have their own security boundaries.
