---
name: execute-offbeat-case
description: Run or resume the current prepared OFFBEAT case and establish its terminal state.
---

# Execute one prepared OFFBEAT case

Use the source case's supplied runner as the execution recipe, including its
preprocessing. The launcher supplies the solver environment; the helper uses
the case as its working directory and waits for the runner:

```bash
python3 <skill-dir>/scripts/case_runner.py run --case <case> -- bash run.sh
```

If a task-local runner reloads an OpenFOAM `bashrc`, disable Bash `nounset`
around that source operation and restore the runner's settings afterward.
OpenFOAM's setup scripts can reference unset optional variables. Retain the
configured OFFBEAT binary directory on `PATH` after loading the environment.
Keep noninteractive plotting on an available headless backend such as `Agg`.

Count actual OFFBEAT starts separately from successful evaluations, saved time
steps and reporting calls. A parameter study evaluates each dispatched parameter
point with its own solver run; postprocessing an existing result is not another
physical evaluation. Preserve launch failures and reporting failures separately.

## OFFBEAT terminal output

In the standard OFFBEAT transient loop, the effective end is the earlier of
`controlDict.endTime` and the heat source's last time marker. The requested load
history must cover the requested duration. With `adjustableTimeStep` enabled,
OFFBEAT's time handling aligns the terminal steps toward that end; normal loop
exit calls `writeNow()`, independently of the periodic `writeInterval`.
Final-state extraction therefore uses this terminal write. Preserve existing
write controls unless the task requires other modeled-time outputs. An optimizer's
best-so-far curve uses evaluation history and needs no additional field writes.
Early failures and custom solver loops use their actual completion evidence.

## Completion handoff

The helper returns `status`, absolute `result_root`, configured `end_time`,
`final_time`, `times`, `exit_code`, `solver_seconds`, `solver_steps` and
`wall_seconds`. It recognizes `end` case-insensitively and compares numeric time
names by value. Its completed record establishes normal runner termination and
the matching final directory; reuse that record. Failed launches retain their
failure record for diagnosis.

For an externally run solve, `inspect --case <case>` reads retained evidence
without starting the solver; `--exit-code` supplies a known process status.
Repair an external completion reader against these retained artifacts.
`--log`, `--end-time` and `--timeout` adapt the runner's settings.
For cases using `controlDict.userTime` (for example days), the helper's
expected end time must match the numeric result-directory unit. Use the native
`controlDict.endTime` value or its directory-unit equivalent for `--end-time`;
keep conversion to physical seconds separate for analysis. A completed 3650-day
run with a `3650/` directory must not be checked against 315360000.

Python callers import `run_case(case, command=[...])` or `inspect_case(case)` from
`scripts/case_runner.py`; optional argument names use underscores. A custom
runner can return its own `status`, `result_root` and completion evidence.
