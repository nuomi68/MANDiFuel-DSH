# MANDiFuel Study Protocol

A Study spans multiple solver evaluations across parameter vectors, samples,
seeds or adaptive candidates. Time steps and response quantities within one solve
belong to one evaluation; comparisons of existing result trees use extraction.

| Capability | Input | Handoff |
| --- | --- | --- |
| `prepare-offbeat-case` | Engineering request, with an optional source case | Selected reference, isolated prepared case and changed inputs |
| `execute-offbeat-case` | Prepared case | Terminal status and retained result root |
| `extract-offbeat-results` | Completed result root and response selection | Requested scalar or response mapping |
| `orchestrate-offbeat-study` | Multiple-evaluation request and available capabilities | Research definition, evaluator and configured method |
| `conduct-offbeat-study` | Configured Study, with optional existing history | Evaluations, retained records and requested analysis |

`evaluate(point)` prepares the point, executes its case and returns the progress
responses needed by the method. Reuse an applicable evaluator or compose missing
Atomic capabilities. Existing prepared cases and completed results enter at their
applicable stage.

## Task context

Treat the active DSH session's selected workspace as the study's data boundary.
For headless tasks, use the caller's working directory. Existing results
inside that workspace may support continuation. Other workspaces, past reports,
experiment logs and conversation/session histories are not reference material
for a new study. Read the plugin's implementation and skill documentation as
needed. Discover reference cases through Prepare's RAG interface and inspect
the configured read-only case library; do not borrow a prepared model or output
from a different task in place of this retrieval and preparation process.

## Study progression

[Orchestrate](skills/orchestrate-offbeat-study/SKILL.md) binds the inputs,
execution recipe, responses and method in task-local Python.
When a source is not supplied, Prepare resolves a suitable reference through
its retrieval interface before those input bindings are established.
[Conduct](skills/conduct-offbeat-study/SKILL.md) runs that controller and delivers
the requested comparison. The first evaluation belongs to the configured method;
subsequent points reuse the same bindings and method instance.

Prepare establishes changed inputs; Execute supplies the terminal result root;
Extract supplies selected responses. Read the contracts needed to compose these
callbacks before dispatch, using their documented arguments and returns. Each
successful handoff supplies the next phase's evidence.

Resolve changed input owners and their physical dependencies from the applicable
preparation reference. Apply the first requested edit successfully, then encode
that path for reuse. Bind outputs using documented fields and selectors; the
method's first evaluation establishes their availability. A missing field or
incompatible selection uses that retained result root for diagnosis. The supplied
execution recipe owns preprocessing.

One Python controller owns the requested method from its first evaluation through
its stopping condition. A fixed design dispatches its complete table; an adaptive
method consumes progress responses and proposes subsequent points through the
same evaluator. Reporting-only extraction follows the evaluations and reuses
their retained roots and responses.

Launch a long-running controller as a foreground command in the Bash tool, then
await the tool's native background job handle when it yields. Do not use shell
`nohup`, `&`, or daemon wrappers: a shell sandbox may terminate detached children
when its command exits. Native job completion, rather than a saved PID or a
launch message, establishes that the study controller actually finished.

Preparation readbacks, execution records and selected responses are the evidence
used for continuation and delivery. A preparation error returns to its affected
binding; an execution error uses Execute's failure record; a missing required
response or extraction error returns to Extract with the retained result root.
Exploratory validation solves require an actual error and a need for new
execution evidence; repair extraction or completion-reading errors against retained
results first. Equal responses alone are not an error. Every actual solver start
for the task counts against its budget, including initialization, diagnostics and
retries in any directory. Changing an attempt's name or purpose does not exempt it.

## Engineering delivery

Lead the final response and report with the engineering question, adopted model,
requested numerical findings and their interpretation. Use concise scientific
prose and plot from retained solver data. State the model conditions needed to
understand the comparison; a finite design reports its best evaluated points.
Keep routine shell setup, machine paths and repaired implementation diagnostics
in the retained execution records rather than making them the report's story.
If an unresolved issue changes the requested result or method, explain that
specific issue and do not present the affected claim as established. Separate
analytical validation curves from numerical results in the figure legend.
Do not assign a numerical discretization error without a refinement study or
other quantitative evidence. Differences between evaluated designs establish
their computed response differences, not a mesh error estimate. Interpret a
time-space heatmap as a distribution; infer delays only from the resolved time
histories. Report whether the best optimized candidate arose during initial
sampling or adaptive search, and keep both phases visible in the trajectory.
