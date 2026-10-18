# Changelog

## 0.4.0-alpha.8

- Share RAG query-mapping and embedding caches in the installation's .cache/rag directory by default.
- Keep an optional explicit cache-path override and separate caches from solver outputs and bundled indexes.

## 0.4.0-alpha.7

- Let DSH Web own the selected session workspace; remove the launcher workspace option.
- Keep the caller's directory for headless execution and example tasks.
- Resolve the default RAG cache in the active query workspace instead of pinning it at startup.

## 0.4.0-alpha.6

- Preserve native Optuna sampler state and pending trials across controller restarts.
- Document foreground study execution with native background job handles.
- Scope continuation data to the active study and separate engineering results from routine diagnostics.
- Refine the TRISO scan around temperature and gas-pressure responses.
- Add a follow-up prompt for local PWR power-shape optimization after the initial search.
- Require evidence for numerical-error and time-delay interpretations.

## 0.4.0-alpha.5

- Provide five natural engineering tasks: one transient solve, a grid scan, optimization, uncertainty propagation and parameter inversion.
- Start example tasks without preselected source cases; let Prepare retrieve and assess references.
- Route source-free studies through retrieval before evaluator binding.
- Remove bundled example fixtures and update workspace initialization and documentation.
- Clarify solver-start counting, OpenFOAM environment loading and native user-time units.

## 0.4.0-alpha.4

- Remove installer, automatic configuration and bootstrap resources.
- Provide a short dependency/startup guide and an editable local configuration template.
- Retain four runnable examples and existing launch/build entry points.

## 0.4.0-alpha.3

- Replace distributed unit tests with four runnable prompt-driven examples.
- Add DSH detection/install, key-configuration guidance and explicit OFFBEAT setup consent.
- Pin OFFBEAT source by commit with OpenFOAM v2506 manual instructions.
- Validate and include examples, installation scripts and notices in both archives.

## 0.4.0-alpha.2

- License original project material under GPL-3.0-or-later; preserve OFFBEAT attribution.
- Include license, notices, source hashes and index regeneration instructions.
- Add source packaging, development dependencies and CI validation.
- Exclude local configuration, caches and development-control material from archives.

## 0.4.0-alpha.1 — 2026-10-17

- Make DeepSeek DSH the only supported runtime, with Web and headless launchers.
- Resolve Node.js explicitly or from the DSH installation for non-interactive shells.
- Retain the five canonical Skills, Study protocol and dual-index case retrieval.
- Preserve explicit per-process workspace and provider settings over launcher defaults;
  derive a separate retrieval cache for every overridden workspace.
- Replace host-specific manifests with `mandifuel.json` and rebuild the release allowlist.
- Remove obsolete host entrypoints, audit implementation and host-only tests.
- Initial DSH-only development snapshot.
