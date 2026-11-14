#!/usr/bin/env python3
"""Run identical fuel-rod tasks concurrently; retain stdout, stderr and DSH events."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent


def now():
    return datetime.now(timezone.utc).isoformat()


def run_arm(arm, root, timeout):
    target = root / arm
    workspace = target / 'workspace'
    workspace.mkdir(parents=True, exist_ok=False)
    traces = target / 'traces'
    traces.mkdir()
    # A transparent per-arm executable records actual solver invocations.
    # Its log stays within the task workspace so the DSH sandbox can append it.
    bin_dir = target / 'instrumented-bin'
    bin_dir.mkdir()
    wrapper = bin_dir / 'offbeat'
    wrapper.write_text('#!/usr/bin/python3\n'
        'import datetime, json, os, sys\n'
        'entry = {"started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "cwd": os.getcwd(), "argv": sys.argv[1:], "pid": os.getpid()}\n'
        'informational = any(a in ("-help", "--help", "-help-full", "-help-man", "-doc", "-doc-source", "-version", "--version") for a in sys.argv[1:])\n'
        'entry["kind"] = "information" if informational else "solve"\n'
        f'with open({str(workspace / "binary-invocations.jsonl")!r}, "a") as stream:\n'
        '    stream.write(json.dumps(entry) + "\\n")\n'
        'if not informational:\n'
        f'    with open({str(workspace / "solver-starts.jsonl")!r}, "a") as stream:\n'
        '        stream.write(json.dumps(entry) + "\\n")\n'
        'binary = "/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat"\n'
        'os.execv(binary, [binary, *sys.argv[1:]])\n')
    wrapper.chmod(0o755)
    env = dict(os.environ, BENCH_TRACE_ROOT=str(traces), MPLBACKEND='Agg',
               PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1',
               MANDIFUEL_OFFBEAT_BIN=str(bin_dir),
               MANDIFUEL_RAG_CACHE_DIR=str(target / 'rag-cache'))
    start = time.monotonic()
    result = {'arm': arm, 'started_at_utc': now(), 'workspace': str(workspace),
              'timeout_seconds': timeout}
    (target / 'run.json').write_text(json.dumps(result, indent=2) + '\n')
    with (target / 'stdout.log').open('w') as out, (target / 'stderr.log').open('w') as err:
        process = subprocess.Popen(['bash', str(HERE / 'launch-arm.sh'), arm],
                                   cwd=workspace, env=env, stdout=out, stderr=err,
                                   start_new_session=True)
        result['pid'] = process.pid
        (target / 'run.json').write_text(json.dumps(result, indent=2) + '\n')
        try:
            result['exit_code'] = process.wait(timeout=timeout)
            result['timed_out'] = False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            result.update(exit_code=process.returncode, timed_out=True)
    result.update(ended_at_utc=now(), wall_seconds=round(time.monotonic() - start, 3))
    (target / 'run.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    task = (HERE / 'task.txt').read_bytes()
    (root / 'task.txt').write_bytes(task)
    manifest = {'started_at_utc': now(), 'task_sha256': hashlib.sha256(task).hexdigest(),
                'design': 'single paired run, concurrent arms, serial solver starts within arm',
                'source_case': '/home/lwz/offbeat/Cases/testCases/exerciseOFFBEAT/case1_solved',
                'rag_evaluated': False, 'solver_start_budget_per_arm': 3}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda arm: run_arm(arm, root, args.timeout), ['bare', 'skill']))
    manifest.update(ended_at_utc=now(), results=results)
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
