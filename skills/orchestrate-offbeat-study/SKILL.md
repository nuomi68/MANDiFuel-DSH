---
name: orchestrate-offbeat-study
description: Configure an OFFBEAT Study by defining its research variables and responses, reusing or composing an evaluator, and binding the requested method.
---

# Configure the Study

If no source case is supplied, use [Prepare](../prepare-offbeat-case/SKILL.md)
to retrieve and assess a reference from the engineering request before binding
the evaluator. This does not require a separate retrieval instruction from the user.

Define the source, varied inputs and physical relationships, point design or
named algorithm, requested responses, concurrency and total evaluation budget.
Use the user's algorithm, or select a suitable named method and record its settings.

`progress` responses determine subsequent points or stopping; `reporting`
responses supply the final comparison. Fix their physical support, modeled time,
reduction and unit. A fixed design can postpone extraction until reporting.

Reuse an applicable `evaluate(point)`. For a missing path, begin with
[Prepare](../prepare-offbeat-case/SKILL.md) and the source's varied input owners.
Apply the first requested edit successfully before generalizing that edit into
reusable preparation code. [Execute](../execute-offbeat-case/SKILL.md) supplies
the runner and terminal-write contract; [Extract](../extract-offbeat-results/SKILL.md)
supplies progress selection when the method needs a solver response.

The task-specific pieces are input bindings, the response formula and method
settings. Conduct's [callable interface](../conduct-offbeat-study/references/study-runner.md)
joins these to the supplied runner. Use its component form for a source case,
or pass an existing evaluator directly. Bind documented arguments and return
values. Resolve an uncovered input requirement before dispatch; an observed
interface failure directs implementation diagnosis to the affected component.
Each point uses an isolated target based on the task/module root.
A changed source, parameter schema or physical relationship updates the affected code.

For a fixed design, materialize the complete point table and pass it to
`Study.run(points, workers=...)`; all ready points share the resolved preparation
path. For sequential optimization, connect the evaluator to the library's native
objective callback; the library owns proposal updates and trial state. Conduct's
`Study` executes and records each requested point inside that callback.
Use ask/evaluate/tell or `next_points(history)` when the method
needs a shared ready frontier or batch dispatch. The first invocation evaluates
a point from the requested method; no separate baseline is needed unless the
research itself requests one. Existing completions can be adopted with their
responses and budget usage.

Once this evaluation path can run, read [Conduct](../conduct-offbeat-study/SKILL.md)
for command waiting and delivery, then hand it task-local `study.py`.
Its first real result resolves output-dependent details; later values reuse the
path. The controller continues the method after each successful return.

Read only the applicable method guidance: [sweeps/candidates](../conduct-offbeat-study/references/sweeps-and-candidates.md),
[sampling](../conduct-offbeat-study/references/uncertainty-quantification.md), or
[adaptive search](../conduct-offbeat-study/references/optimization.md).
[Fuel-rod dependencies](../conduct-offbeat-study/references/fuel-rod-design-studies.md)
apply when the task couples geometry, operating histories or physical models.
