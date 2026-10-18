---
name: conduct-offbeat-study
description: Execute a configured OFFBEAT Study with its evaluator and method, retain evaluation history, and produce the requested analysis.
---

# Execute the configured Study

Run task-local `study.py` with its evaluator, method and task budget. The
[callable interface](references/study-runner.md) supplies dispatch and record
semantics. History may be empty or contain previous evaluations.

The entry command owns all evaluations and method updates. A native
optimizer loop can call `study.run([point])` internally;
a fixed design passes its table, and a ready-frontier method supplies
`next_points(history)`. These are Python-managed evaluations, including when
an algorithm is sequential. Keep the method instance alive and consume each
new observation once, including the final observation at dispatch completion.

The first successful evaluation establishes the reusable path for continuation.
Continue through that same evaluator and method; a changed point value calls the
existing bindings. Deferred reporting work is not a prerequisite for proposing
or solving the next ready point.

Await the entry command's terminal exit through its host job handle; a background
launch notification establishes progress, not completion. Stay with the command
through its requested phases, including reporting when invoked. The controller
waits for its solvers; status observation uses its records. After an actual error,
repair its stage and resume using the retained successful records.
Submit the controller itself as the foreground Bash command. Use the returned
native job handle for a long run; shell `nohup`/`&` do not preserve a process
across sandbox lifetimes.

Authorized retries or replicates use distinct identities and retain earlier
records. The callable reference distinguishes its dispatch limit from the task's
solver-start budget. Sequential adaptive methods use one worker.

For a sequential single-objective Optuna task, use the bundled
`study_runner.run_optuna` controller described in the
[optimization reference](references/optimization.md#durable-optuna-controller).
Bind the response reader before dispatch. The controller saves the native
optimizer, sampler RNG and pending parameters, so a reporting repair can reuse
the completed result without restarting the sampling sequence.

After evaluations finish, save the method's completed state and build the
comparison from retained `response` values. For additional requested quantities,
`study.collect(extract_reporting)` reads successful result roots into
`reporting_response`. A fixed design without progress extraction collects here.
Collection persists each result and resumes unfinished reporting after repair;
the completed search remains available. Preparation readbacks and execution
status already accompany the results; use them directly. Keep unavailable
responses and failed attempts explicit, with conclusions limited to the design.

A retained table and its interpretation suffice for a numerical comparison.
When a figure is requested, plot from that table using an available library or
a simple static SVG when the format is open. Another plotting environment is
needed only for a requested output the available route cannot produce.
