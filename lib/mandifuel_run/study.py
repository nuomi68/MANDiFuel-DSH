"""Run task-defined evaluations with retained point records."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
from pathlib import Path

from .case import locked, run_case, save_json


def _key(point):
    return json.dumps(point, sort_keys=True, allow_nan=False)


class Study:
    """Supply evaluate(point), or prepare(point) with a runner and progress.

    Points are JSON dictionaries; include an id/seed for intentional replicates.
    history is stored as history.json. status describes the solve; progress_status
    and reporting_status separately describe extraction. No automatic retries.
    An optional execute(case) callback supports other established runner contracts.
    """

    def __init__(self, root, prepare=None, *, command=('bash', 'run.sh'), progress=None,
                 log='log.offbeat', end_time=None, timeout=None, execute=None, evaluate=None):
        if (prepare is None) == (evaluate is None):
            raise ValueError('Supply either prepare or evaluate')
        if evaluate is not None and execute is not None:
            raise ValueError('evaluate already owns execution')
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.prepare, self.progress = prepare, progress
        self.evaluate = evaluate
        self.execute = execute or (lambda case: run_case(case, command=command, log=log,
                                                       end_time=end_time, timeout=timeout))
        self.path = self.root / 'history.json'
        self.history = self._load()

    def _load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def _save(self):
        save_json(self.path, self.history)

    def adopt(self, point, completed, *, response=None):
        """Register an existing completion record without prepare/execute/extract."""
        if completed['status'] != 'completed':
            raise ValueError('adopt expects an existing completed solve record')
        if response is None:
            response = completed.get('response')
        record = {**completed, 'point': point, 'response': response}
        if response is not None:
            record['progress_status'] = 'completed'
        with locked(self.root / '.mandifuel-study.lock'):
            self.history = self._load()
            for index, previous in enumerate(self.history):
                if _key(previous['point']) == _key(point):
                    if previous['status'] == 'completed':
                        return previous
                    self.history[index] = record
                    break
            else:
                self.history.append(record)
            self._save()
        return record

    def _evaluate(self, point):
        record = {'point': point, 'status': 'prepare_failed', 'response': None}
        try:
            if self.evaluate is not None:
                record['status'] = 'evaluation_failed'
                completed = self.evaluate(point)
                if completed['status'] == 'running':
                    raise ValueError('evaluate must return a terminal record')
                if completed['status'] == 'completed' and 'result_root' not in completed:
                    raise ValueError('A completed evaluation requires result_root')
                record.update(completed, point=point)
                if record['response'] is not None:
                    record.setdefault('progress_status', 'completed')
            else:
                case = self.prepare(point)
                record.update(result_root=str(Path(case).resolve()), status='execution_failed')
                record.update(self.execute(case))
        except Exception as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
            return record
        return self._progress(record)

    def _progress(self, record):
        if self.progress and record['status'] == 'completed' and record.get('progress_status') != 'completed':
            try:
                record.update(response=self.progress(record['result_root']), progress_status='completed')
            except Exception as exc:
                record.update(response=None, progress_status='failed', progress_error=f'{type(exc).__name__}: {exc}')
        return record

    def run(self, points=None, *, next_points=None, workers=1, max_evaluations=None):
        """Run a fixed table or a task's next_points(terminal_history) callback.

        max_evaluations counts all adopted/attempted points, including failures.
        Existing records are retained; only unseen points are dispatched. Pending
        points from an interrupted controller remain explicit, not auto-retried.
        workers=1 preserves sequential adaptive proposal order.
        """
        if (points is None) == (next_points is None):
            raise ValueError('Supply either points or next_points')
        if workers < 1 or (max_evaluations is not None and max_evaluations < 1):
            raise ValueError('workers and max_evaluations must be positive')
        fixed = list(points) if points is not None else None
        propose = next_points if fixed is None else lambda history: fixed
        with locked(self.root / '.mandifuel-study.lock'):
            self.history = self._load()
            for record in self.history:
                if record['status'] == 'running':
                    record.update(status='interrupted', error='Controller interrupted; retained cases can be inspected and adopted')
                self._progress(record)
            self._save()
            pending = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                try:
                    while True:
                        known = {_key(r['point']) for r in self.history}
                        terminal = [r for r in self.history if r['status'] != 'running']
                        has_budget = max_evaluations is None or len(self.history) < max_evaluations
                        ready = propose(terminal) if has_budget and len(pending) < workers else []
                        for point in ready:
                            if len(pending) >= workers or (max_evaluations is not None and len(self.history) >= max_evaluations):
                                break
                            key = _key(point)
                            if key in known:
                                continue
                            known.add(key)
                            index = len(self.history)
                            self.history.append({'point': point, 'status': 'running', 'response': None})
                            self._save()
                            pending[pool.submit(self._evaluate, point)] = index
                        if not pending:
                            break
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            self.history[pending.pop(future)] = future.result()
                            self._save()
                finally:
                    for future, index in pending.items():
                        self.history[index] = future.result()
                        self._save()
        return self.history

    def collect(self, reporting):
        """Collect reporting(result_root) after solving; extraction never reruns it."""
        with locked(self.root / '.mandifuel-study.lock'):
            self.history = self._load()
            for record in self.history:
                if record['status'] != 'completed' or record.get('reporting_status') == 'completed':
                    continue
                try:
                    record.update(reporting_response=reporting(record['result_root']), reporting_status='completed')
                except Exception as exc:
                    record.update(reporting_status='failed', reporting_error=f'{type(exc).__name__}: {exc}')
                self._save()
        return self.history
