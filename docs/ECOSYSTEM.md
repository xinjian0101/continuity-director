# Ecosystem Value

Continuity Director addresses a narrow but recurring problem in AI video production: generation tools can produce individual clips, but production teams still need structured control over identity, scene state, shot handoffs, quality decisions, retries, approvals, and reproducibility.

## Primary users

- ComfyUI workflow authors building multi-shot video pipelines.
- Independent creators who need repeatable character and scene constraints.
- Small production teams coordinating generation, review, and export decisions.
- Custom-node developers who need model-agnostic continuity and reliability records.
- Researchers comparing generation runs under controlled workflow inputs.

## Ecosystem contribution

The project provides reusable infrastructure rather than another model wrapper:

- Stable JSON records for project, character, scene, shot, and environment state.
- Deterministic storyboard-to-Take expansion.
- Quality gates, Take ranking, and exact-path continuity reports.
- Dependency-safe execution plans, retries, checkpoints, and idempotency keys.
- Revision-safe collaboration and portable verified production packages.
- English, Simplified Chinese, and bilingual interface support.

These capabilities can sit around different video models and generation workflows, reducing duplicate implementation across projects.

## Integration boundaries

Continuity Director is intentionally model-agnostic. It can complement video-generation nodes, reference-image tools, quality metrics, post-processing pipelines, and external production systems through declared data. Imported JSON remains data and is not executed.

## Non-goals

- Replacing video-generation models.
- Guaranteeing pixel-perfect identity.
- Storing model-service credentials.
- Collecting hidden usage data.
- Executing third-party configuration as code.

## Why the project matters

AI video workflows increasingly combine many nodes, models, references, and manual decisions. Without explicit production state, failures are difficult to reproduce and collaboration is difficult to audit. Continuity Director turns those decisions into inspectable, testable, and portable records for the ComfyUI ecosystem.
