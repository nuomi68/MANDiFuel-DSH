"""Run a prepared case once, or inspect retained OFFBEAT completion evidence."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

RECEIPT = '.mandifuel-execution.json'
COMPLETION_ERROR = 'Runner did not establish normal completion at end_time'


def save_json(path, value):
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(path):
    with Path(path).open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _number(value):
    number = Decimal(str(value).strip().rstrip(';').strip())
    if not number.is_finite():
        raise ValueError('Modeled time must be finite')
    return number


def _end_time(case, supplied):
    if supplied is not None:
        return _number(supplied)
    path = case / 'system/controlDict'
    # Preserve a literal endTime: foamDictionary's default output rounds to six
    # significant digits; increasing precision can expose binary float artifacts.
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', path.read_text(), flags=re.S)
    for match in re.finditer(r'(?m)^\s*endTime\s+([^;]+);', text):
        prefix = text[:match.start()]
        if prefix.count('{') != prefix.count('}'):
            continue
        try:
            return _number(match[1])
        except (InvalidOperation, ValueError):
            pass
    # Native dictionary parsing resolves nonliteral entries and includes.
    try:
        result = subprocess.run(['foamDictionary', str(path), '-precision', '17', '-entry', 'endTime', '-value'],
                                capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return _number(result.stdout)
    except FileNotFoundError:
        pass
    raise ValueError('Supply end_time when controlDict endTime cannot be resolved')


def _final_time(case, times, end):
    """Retain the real directory name, allowing bounded accumulation roundoff.

    The bound is relative to modeled time and capped below one percent of a
    literal deltaT and the observed spacing of saved times. It must not turn a
    missing time step into a completed run or depend on display precision.
    """
    exact = next((name for value, name in times if value == end), None)
    if exact is not None:
        return exact, {'method': 'exact', 'difference': '0', 'tolerance': '0'}
    tolerance = max(abs(end), Decimal(1)) * Decimal('1e-12')
    values = sorted({value for value, _ in times})
    bounds = [b - a for a, b in zip(values, values[1:]) if b > a]
    control = case / 'system/controlDict'
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '',
                  control.read_text() if control.is_file() else '', flags=re.S)
    for match in re.finditer(r'(?m)^\s*deltaT\s+([^;]+);', text):
        prefix = text[:match.start()]
        if prefix.count('{') != prefix.count('}'):
            continue
        try:
            step = _number(match[1])
            if step > 0:
                bounds.append(step)
        except (InvalidOperation, ValueError):
            pass
        break
    if bounds:
        tolerance = min(tolerance, min(bounds) * Decimal('0.01'))
    near = [(abs(value - end), value, name) for value, name in times
            if abs(value - end) <= tolerance]
    if near:
        _, value, name = min(near)
        return name, {'method': 'roundoff', 'difference': str(value - end),
                      'tolerance': str(tolerance)}
    return None, {'method': 'missing', 'tolerance': str(tolerance)}


def failure_diagnostic(text, log):
    """Return bounded native error evidence, omitting implementation stack traces."""
    match = re.search(r'^.*FOAM FATAL(?: IO)? ERROR[^\n]*', text, flags=re.M)
    if match:
        lines = []
        for line in text[match.start():].splitlines():
            if line.lstrip().startswith(('From ', '[stack trace]', '#1 ', 'FOAM aborting', 'FOAM exiting')):
                break
            lines.append(line)
            if sum(len(x) + 1 for x in lines) >= 2200:
                break
        excerpt = '\n'.join(lines).strip()[:2200]
        kind = 'native_solver_error'
    else:
        excerpt = '\n'.join(text.splitlines()[-12:]).strip()[-1800:]
        kind = 'completion_or_execution_failure'
    return {'kind': kind, 'message': excerpt or 'No solver error text captured; inspect runner log and exit evidence.',
            'log': str(log), 'next_action': 'diagnose_inputs_then_run_repaired_new_attempt'}


def inspect_case(case, *, log='log.offbeat', end_time=None, exit_code=None):
    """Read completion evidence; never launch, prepare, or alter the case.

    Returns status, result_root, end_time, final_time, times and timing evidence.
    External runs can supply exit_code, or use the runner's log.run-status.
    A recorded failure takes precedence over old successful field files.
    """
    case = Path(case).resolve()
    end = _end_time(case, end_time)
    times = []
    for path in case.iterdir():
        if path.is_dir():
            try:
                times.append((_number(path.name), path.name))
            except (InvalidOperation, ValueError):
                pass
    times.sort()
    final, time_match = _final_time(case, times, end)
    receipt_path = case / RECEIPT
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    explicit_exit = exit_code is not None
    if exit_code is None:
        exit_code = receipt.get('exit_code')
        status_file = case / 'log.run-status'
        if exit_code is None and status_file.exists():
            exit_code = int(status_file.read_text().strip())
    log_path = case / log
    text = log_path.read_text(errors='replace') if log_path.exists() else ''
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ended = bool(lines and lines[-1].lower() == 'end')
    timing = re.findall(r'Execution\s*Time\s*=\s*([\d.eE+-]+)\s*s', text)
    status = 'completed' if ended and final is not None and exit_code in (None, 0) else 'incomplete'
    # Older runners labeled a normal exit as failed when a time name contained
    # binary accumulation noise. Reconcile only this specific classification
    # error; preserve the original receipt and every genuine failed launch.
    reconciled = (status == 'completed' and exit_code == 0
                  and receipt.get('status') == 'failed'
                  and receipt.get('exit_code') == 0
                  and receipt.get('error') == COMPLETION_ERROR)
    if exit_code not in (None, 0) or (
            receipt.get('status') in ('failed', 'interrupted') and not reconciled):
        status = 'failed'
    elif receipt.get('status') == 'running' and not explicit_exit:
        status = 'running'
    record = {'status': status, 'result_root': str(case), 'end_time': str(end),
            'final_time': final, 'times': [name for _, name in times],
            'time_match': time_match,
            'exit_code': exit_code, 'terminal_marker': ended,
            'solver_seconds': float(timing[-1]) if timing else None,
            'solver_steps': len(re.findall(r'^Time\s*=\s*\S+', text, flags=re.M)),
            'wall_seconds': receipt.get('wall_seconds'), 'log': str(log_path)}
    if status in ('failed', 'incomplete') and exit_code is not None:
        record['diagnostic'] = failure_diagnostic(text, log_path)
    if reconciled:
        record.update(error=None, previous_receipt_status='failed',
                      completion_reconciled=True)
    return record


def run_case(case, *, command=('bash', 'run.sh'), log='log.offbeat', end_time=None,
             timeout=None):
    """Wait for one case runner and return a persisted completion record.

    Repeated/concurrent calls reuse a completed record. An earlier failed or
    interrupted launch is returned for diagnosis, without an automatic retry.
    command is an argv sequence; use ['bash', '-c', script] for shell pipelines.
    """
    case = Path(case).resolve()
    if isinstance(command, str) or not command:
        raise ValueError('command must be a nonempty argv sequence')
    with locked(case / '.mandifuel-execution.lock'):
        receipt = case / RECEIPT
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved['status'] in ('completed', 'failed', 'interrupted'):
                if (saved['status'] == 'failed' and saved.get('exit_code') == 0
                        and saved.get('error') == COMPLETION_ERROR
                        and (end_time is None or _number(end_time) == _number(saved['end_time']))):
                    checked = inspect_case(case, log=log, end_time=saved['end_time'])
                    if checked.get('completion_reconciled'):
                        return {**saved, **checked}
                return saved
        previous = inspect_case(case, log=log, end_time=end_time)
        if previous['status'] in ('completed', 'failed'):
            return previous
        if (case / RECEIPT).exists():
            previous.update(status='interrupted', error='Previous launch has no completed record')
            return previous
        started = time.monotonic()
        record = {**previous, 'status': 'running', 'command': list(command)}
        save_json(case / RECEIPT, record)
        try:
            with (case / 'log.mandifuel-runner').open('w') as output:
                process = subprocess.Popen(command, cwd=case, stdout=output,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait(timeout=timeout)
                except BaseException:
                    # The runner may have child solver processes; terminate its group.
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise
            record = inspect_case(case, log=log, end_time=previous['end_time'], exit_code=code)
            if record['status'] != 'completed':
                record.update(status='failed', error=COMPLETION_ERROR)
        except (OSError, subprocess.TimeoutExpired) as exc:
            record.update(status='failed', error=str(exc), exit_code=-1)
        except BaseException:
            record.update(status='interrupted', wall_seconds=time.monotonic()-started)
            save_json(case / RECEIPT, record)
            raise
        record.update(command=list(command), wall_seconds=time.monotonic()-started)
        save_json(case / RECEIPT, record)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'inspect'))
    parser.add_argument('--case', required=True)
    parser.add_argument('--log', default='log.offbeat')
    parser.add_argument('--end-time')
    parser.add_argument('--timeout', type=float)
    parser.add_argument('--exit-code', type=int, help='Known exit status of an external run, for inspect')
    argv = sys.argv[1:]
    separator = argv.index('--') if '--' in argv else len(argv)
    command = argv[separator+1:]
    args = parser.parse_args(argv[:separator])
    options = {'log': args.log, 'end_time': args.end_time}
    if args.action == 'inspect':
        record = inspect_case(args.case, **options, exit_code=args.exit_code)
    else:
        record = run_case(args.case, **options, timeout=args.timeout, command=command or ['bash', 'run.sh'])
    print(json.dumps(record, indent=2))
    return 0 if record['status'] == 'completed' else 1
