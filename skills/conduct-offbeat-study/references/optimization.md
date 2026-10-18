# Derivative-free and multiobjective optimization

Use this card only when later candidates may depend on earlier solver results.
An enumerated candidate list belongs to finite-candidate selection instead.

## Define the search

The search is defined by variables, units, bounds, objective direction,
input-only and solver-dependent constraints, solver-start budget, algorithm,
seed when stochastic, and stopping rule.

Use the user's named algorithm and settings. Otherwise choose a named method
suited to the domain, constraints and budget, and record that choice. An available
library's native callback supplies proposal/update bookkeeping. Bisection is for
a monotonic threshold or bracketing task, rather than general minimization.
Population initialization and updates belong within the solve budget.

## Sequential objective callback

### Durable Optuna controller

For a sequential scalar objective, use the bundled controller to keep response
binding and sampler recovery consistent:

```python
from study_runner import Study, run_optuna
import optuna

study = Study(ROOT, prepare=prepare, command=['bash', 'run.sh'],
              progress=extract_progress, end_time=requested_end_time)
optimizer = run_optuna(
    study,
    suggest=lambda trial: {
        'a': trial.suggest_float('a', -0.2, 0.2),
        'b': trial.suggest_float('b', -0.15, 0.15)},
    objective=lambda point, response: response['fuel_max_T_K'],
    budget=12,
    sampler=optuna.samplers.TPESampler(seed=20261018, n_startup_trials=4))
# Reporting consumes optimizer.trials and study.history after all evaluations.
```

The parameters and objective key above are illustrative; bind them to the task.
The controller owns point ids and trial indices, so `suggest` returns parameters
only. Its checkpoint is task-local trusted pickle data; do not load downloaded
checkpoints. Re-running the same controller restores the whole native optimizer
and pending trial. Fix a failed response reader in place, then resume; do not
recreate the sampler from a table of observations. A failed solver stops for
explicit diagnosis rather than automatic retry. Use one controller process per
study root and keep its local checkpoint when archiving raw study evidence.

### Custom native callback

For a component-based evaluator, connect the task's prepared-case function and
progress reader before the loop. `extract_progress(result_root)` returns the
physical response consumed by `objective(point, response)`; `suggest(trial)`
supplies the varied parameters. For an Optuna optimizer configured with the
requested sampler and storage, this fresh-search example lets the native
callback own each trial's lifecycle. Each successful callback performs one solve;
a stage error stops the loop for repair:

```python
study = Study(ROOT, prepare=prepare, command=["bash", "run.sh"],
              progress=extract_progress)

def objective_trial(trial):
    point = {**suggest(trial), "id": str(trial.number)}
    record = study.run([point], workers=1)[-1]
    if record["status"] != "completed" or record.get("response") is None:
        raise RuntimeError(f"Evaluation needs repair: {record}")
    return objective(point, record["response"])

optimizer.optimize(objective_trial, n_trials=budget, n_jobs=1)
```

An existing complete evaluator uses `Study(ROOT, evaluate=evaluate)` instead.
In both forms the callback suggests a point, evaluates it and returns the objective.
The optimizer commits the trial after this return. Completed-trial state, timings
and best-so-far summaries belong in a post-trial callback or after `optimize`.
In Optuna, the active `Trial` supplies suggestions and attributes; completed
`FrozenTrial` records supply `state`, `value` / `values` and timings. `best_value`
requires a completed single-objective trial; a multiobjective study uses
`best_trials`. Keep delivery and summary generation outside the objective callback.
The example surfaces a failed evaluation for repair; an explicitly configured
failure policy can instead let the method continue with its recorded failure state.
Ask/evaluate/tell remains useful when trial lifetime must span external dispatch
or population updates; a synchronous evaluator fits the objective callback.

The first real evaluation is the first callback of this same optimization loop.
Its successful return advances the existing sampler directly. Keep that method
instance alive through the search; a preparation handoff does not require a
separate optimizer invocation.

For interrupted-run recovery, restore the sampler state as well as its trial
history: reopening a trial database with a fresh seeded sampler does not restore
the sampler's in-memory state. Apply the remaining solver-start budget using the
[runner's accounting distinction](study-runner.md#points-and-methods).
Export completed trial metadata from the optimizer's native history, such as
`optimizer.trials`.

## Match the method to the search domain

Use bounded golden-section or Brent-style search only for one continuous
bounded variable when its local or unimodal-search assumption is accepted.
Otherwise report only the budget-limited best observed result, or use a
recorded finite or multistart design.

Run the complete search in the task's Python controller. Use the library's
native optimization loop when it already owns proposal and update order. A
`next_points(history)` adapter is useful for ready-frontier or population dispatch;
its stopping condition returns an empty list. Keep one
optimizer instance alive during the run and feed each new observation once.
After dispatch ends, feed the final outstanding observations and save the
optimizer state and its actual trial metadata. Reconstruct state from ordered
history only for interrupted-run recovery when saved state cannot be loaded;
replayed timestamps are not the original trial timings. Method
settings include initialization, tie handling, update order and stopping; a
population method also maps population size and generations to the start budget.
For a synchronous population update, return the current generation's point list
until its records are complete; then update the optimizer and propose the next
generation. `Study` dispatches the unseen members of that list within `workers`.

Route a fully materialized finite discrete domain to finite-candidate
selection. For adaptive integer, categorical, or mixed domains, use a method
that proposes legal values in those domains. Do not silently round continuous
proposals; any encoding, repair, or duplicate rule is part of the recorded
algorithm.

Surrogate or Bayesian search adds an initial design, model, acquisition rule,
seed and update schedule. Predictions and acquisition values are optimizer
bookkeeping, not physical results, and the
reported best design must have an actual valid solver evaluation.

## Evaluate and update

Preserve the requested algorithm's proposal and duplicate semantics. Caching is
an explicit research policy when repeated deterministic inputs should share a
solve; it is not added automatically to a native optimizer. For stochastic
responses, record replicate seeds, replicate count and objective aggregation.
Append proposals, starts,
failures, extracted objectives, and constraint states to the cumulative history.

For adaptive or population methods, record whether updates are sequential,
synchronous-batch, or asynchronous. Only the declared update order may affect
later proposals; recovery replays the recorded order without silently
resuggesting completed points.

A failure penalty supplied to the optimizer is algorithm bookkeeping, separate
from the physical response. Failed starts count toward the solver-start budget.

Report the best observed feasible design and the exact actual-start count. A
budget-limited derivative-free run does not establish a global optimum or
convergence unless separate evidence supports that claim. A neighboring feasible
and infeasible sample brackets a global feasibility boundary only when the
required monotonicity is established.

## Multiple objectives

Compute nondominance from valid feasible results and retain all tied designs.
Each objective has its own direction and unit. A weighted scalarization requires
specified weights and objective scales; otherwise the result is the observed
Pareto set and its tradeoffs.
