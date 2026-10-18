---
name: prepare-offbeat-case
description: Prepare OFFBEAT inputs from an engineering request, retrieve a suitable reference when no source is supplied, and modify physical inputs, histories, geometry and sampling definitions.
---

# Prepare the requested case

Prepare the requested input in a copy of the source input tree at the target path
(default `case/` in the task workspace). Case-root model files travel with
`0/`, `constant/` and `system/`.

## Input bindings

For a supplied case, start with the requested row in the
[input bindings](references/input-bindings.md) or the geometry reference below,
then read the corresponding data owner in that case. Radius, diameter, thickness
and geometric-gap changes use the geometry reference for material-input
dependencies even when the generator entry is already known. The selected entries
and their include/file references define the edit scope; a load-only change reuses
the existing geometry. Apply the resolved edits and use their returned readbacks.

| Geometry | Input and editing reference |
| --- | --- |
| Generator-owned rod or TRISO dimensions | `rodDict`, `rod3Ddict.json` or `sphereDict`: [generator dimensions](references/radial-geometry.md). |
| Explicit radial coordinates without a generator, or separately requested retained geometry | [Radial mapping](references/radial-coordinate-map.md). |
| Box dimensions | `system/blockMeshDict` or retained points: [box resize](references/box-geometry.md). |
| Sector angle | Generator angle or retained block/UNV geometry: [angle mapping](references/sector-geometry.md). |
| Replacement rod structure | Template/generator: [new rod](references/geometry-construction.md). |

## Source selection

When the user supplies an engineering task without a source case, retrieve
references from the complete request through:
`python3 <plugin-root>/rag/query.py --query-file <request-file> --limit 5 --compact`.
This is part of preparation; the user does not need to name RAG, a Skill, a
template file or a case-card identifier. For a Study, resolve this source before
binding its varied inputs and evaluator.

Inspect the returned labels, exclusions and referenced input directories for
geometry, material, physics and requested responses. Choose a suitable candidate
on that evidence, retain the query result and selection rationale in the task
workspace, then prepare an isolated copy. A similarity rank alone does not
establish engineering suitability. Use the configured case-library root to
resolve references returned by this interface.

If the returned candidates omit an essential component or physical capability,
refine the engineering query with that missing requirement or widen the
candidate list up to `--limit 20`, then assess the returned references again.
A reduced benchmark
does not replace a complete model merely because it has a high similarity score.

Separate requested changes from reference-case assumptions and identify the
adopted reference settings in the handoff. If essential engineering information
is missing or candidates do not support the task, ask for that information.
A retrieval/provider failure is reported as such; it does not select a hidden
example fixture or imply that retrieval succeeded.

## Editing interfaces

- Existing dictionary entry:
  `python3 <skill-dir>/scripts/foam_edit.py --case <target> --file <file> --entry <path> --set '<value>'`.
  Multiline values use `--set-file <value-file>`.
- Generator parameters: edit the parameter file and regenerate the requested
  dictionary. A parameter-only deliverable consists of the parameter edits.
- Retained coordinates:
  `python3 <skill-dir>/scripts/geometry_ops.py --case <target> --apply <operation.json>`.
- Python-literal inputs and unsupported syntax accept task-local text or Python edits.

`<skill-dir>` denotes this directory; `<plugin-root>` denotes the plugin root.
The native editor returns the changed entry's readback. A geometry return with
`validation.status: passed` certifies the edits covered by that operation.
These readbacks complete preparation for their covered bindings; a discrepancy
reopens the affected edit. A task-local edit without such a return reads its
changed inputs back once at their serialized precision. Hand off the target path,
changed inputs and these readbacks.
