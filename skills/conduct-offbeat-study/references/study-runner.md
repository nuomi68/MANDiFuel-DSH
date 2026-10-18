# Study callable interface

Import the thin interface using the discovered plugin root:

```python
import sys
from pathlib import Path

PLUGIN = Path("<plugin-root>")
sys.path.insert(0, str(PLUGIN / "skills/conduct-offbeat-study/scripts"))
from study_runner import Study
ROOT = Path(__file__).resolve().parent
```

## Compose missing capabilities

For a source case with a supplied runner, provide the task's input edits and
progress response:

```python
study = Study(ROOT, prepare=prepare, command=["bash", "run.sh"],
              progress=extract_progress)
```

`prepare(point)` returns the isolated case path after applying the resolved edits.
The supplied runner owns preprocessing and terminal output as described by
[Execute](../../execute-offbeat-case/SKILL.md); it runs in that case directory
with the inherited solver environment. `extract_progress(result_root)` returns
the requested scalar or small response mapping. Omit it for a fixed design whose
responses can wait until reporting. `log=...`, `end_time=...` and `timeout=...`
adapt the bundled runner; `execute=custom_execute` instead accepts a callable
returning terminal `status`, absolute `result_root` and available evidence.

For a fixed design with reporting-only responses:

```python
study = Study(ROOT, prepare=prepare, command=["bash", "run.sh"])
history = study.run(points, workers=workers)
history = study.collect(extract_reporting)
```

For a fresh sequential point inside an optimizer callback,
`record = study.run([point], workers=1)[-1]` waits and persists its result.
`run` returns cumulative history in proposal order, not a single record.
`record["response"]` is the progress callback's return value; execution metadata
such as `status`, `final_time` and `result_root` is alongside it.

## Reuse an evaluator

An available `evaluate(point)` already owns preparation, execution and progress
extraction. Pass it as `Study(ROOT, evaluate=evaluate)` in place of the components.

The evaluator returns a JSON-serializable terminal record with `status`, the
absolute `result_root` when solved, and `response` for progress when needed.
A scalar or small response mapping suffices. A non-null response is marked
`progress_status="completed"` unless the evaluator supplies an explicit status.
An extraction error retains `status="completed"` for its successful solve and
sets `progress_status="failed"`, `response=None` and `progress_error`.
An uncaught evaluator exception becomes an `evaluation_failed` record.

`Study` supplies dispatch, waiting, limits and history. An optional
`progress(result_root)` can supply missing progress or repair failed extraction
from retained results; completed progress is reused. Both forms accept an empty
history. `adopt` registers an already existing completion.

## Points and methods

Points are JSON dictionaries, for example `{"id": "p01", "x": 0.5}`. Identity is
the complete dictionary; an intentional replicate or authorized retry has a
distinct identity and target path. Recorded points are not automatically attempted again.

`max_evaluations` is an optional cumulative history-entry limit: it includes
adopted points and preparation failures. It is not a physical solver-start counter.
The method owns the task's stopping rule. For a solver-start budget, count actual
starts, including failed solves; a preparation failure before execution consumes
no solve. During error recovery, use the retained execution evidence to account
for starts rather than subtracting `len(history)` or the optimizer's trial count.
A sequential objective callback can omit this separate dispatch limit.

For a ready-frontier method, call
`study.run(next_points=next_points, workers=..., max_evaluations=attempt_limit)`.
`next_points(history)` receives terminal records in proposal order and returns
the ready list, or `[]` when finished. Keep method state alive between calls and
consume each new observation once. The helper dispatches unseen identities
within the worker and evaluation limits; it requests no further proposals when
the optional history-entry limit is reached. Feed the final observations to the method after `run`
returns. One controller command owns this loop through the stopping condition.
With multiple workers, proposals can use completed responses while others run;
use one worker when each proposal depends on every preceding response.

## Records, reporting and recovery

Records contain `point`, solve `status`, `result_root` when available, and
`response` for progress. The bundled runner also supplies `end_time`, `final_time`,
`times`, `exit_code`, `solver_seconds`, `solver_steps`, `wall_seconds` and log path.
`terminal_marker` is a boolean; completed status already incorporates it and
numeric equality of final and end times, regardless of their string spelling.
Progress and reporting status describe extraction separately from solve status.
Without progress extraction, `response` stays `None`; collection fills
`reporting_response` instead.
Search penalties belong to the method, separate from unavailable physical values.

Use retained responses directly for their report columns. When additional
quantities are requested, `study.collect(extract_reporting)` calls
`extract_reporting(result_root)` for successful solves and saves the additions
as `reporting_response` and `reporting_status`. Completed reporting is reused;
failed reporting can be retried after repair without a new solve. Combine the
retained progress and reporting mappings for the analysis. Shared selections
belong in task configuration rather than a large description in every record.

Constructing `Study` with the same root reloads `history.json`; `run` dispatches
unseen points. With a repaired `progress` callback, it recovers missing or failed
progress from successful result roots without invoking the evaluator again.
Interrupted attempts stay explicit. An existing completion can be registered as
`study.adopt(point, completion)`; this preserves a response already in the record,
or accepts `response=value`. Adoption performs no preparation, solve or extraction
and is unnecessary when history already contains the completion. For an externally
run case, Execute's `inspect_case(case)` reads its completion evidence; adopt the
returned completion. Repair an external reader's error against those retained
artifacts. Only the coordinator writes history.

Run the entry command with a timeout covering its requested phases. For a
backgrounded command, use its job handle and completion notification or exit
status. If the host only supports polling, use short waits on that handle or exit
record; a fixed multi-minute sleep can outlast the host tool timeout. The
controller's return establishes completion of its requested phases,
including reporting collection when invoked.
