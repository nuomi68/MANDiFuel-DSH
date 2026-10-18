#!/usr/bin/env python3
"""Prepare or execute one of the five prompt-driven DSH examples."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check() -> None:
    manifest = json.loads((ROOT/'examples/manifest.json').read_text())
    for record in manifest['files']:
        p = ROOT/record['path']
        if not p.resolve().is_relative_to(ROOT/'examples') or p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError(f"example file mismatch: {record['path']}")
    for ident in ('D1','D2','D3','D4','D5'):
        if not (ROOT/'examples'/ident/'prompt.txt').read_text(encoding='utf-8').strip():
            raise ValueError(f'empty prompt: {ident}')
    print('PASS: five engineering prompts verified; no solver or model called.')


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('case', choices=['D1','D2','D3','D4','D5'], nargs='?')
    p.add_argument('--workspace', type=Path)
    p.add_argument('--check', action='store_true')
    p.add_argument('--init-only', '--prepare-only', dest='init_only', action='store_true',
                   help='Create an empty task workspace with the prompt; do not retrieve or prepare a solver case.')
    args = p.parse_args()
    check()
    if args.check:
        return 0
    if not args.case or not args.workspace:
        p.error('case and --workspace are required for preparation or execution')
    work = args.workspace.expanduser().resolve()
    if work == Path(work.anchor) or work == ROOT or ROOT in work.parents:
        raise ValueError('workspace must be outside the plugin and cannot be filesystem root')
    template = ROOT/'examples'/args.case
    prompt = (template/'prompt.txt').read_text(encoding='utf-8')
    expected = {'example': args.case, 'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest()}
    state_path = work/'example-request.json'
    if work.exists() and any(work.iterdir()):
        if not state_path.is_file():
            raise ValueError('workspace is nonempty and was not prepared by this runner')
        state = json.loads(state_path.read_text())
        if state != expected:
            raise ValueError('workspace belongs to a different or changed engineering request')
        if any(path.name not in {'example-request.json', 'prompt.txt'} for path in work.iterdir()):
            raise ValueError('workspace already contains task data; select a fresh workspace')
    else:
        work.mkdir(parents=True,exist_ok=True)
        state_path.write_text(json.dumps(expected,indent=2)+'\n')
    (work/'prompt.txt').write_text(prompt,encoding='utf-8')
    if args.init_only:
        print('Prompt workspace initialized:', work)
        return 0
    if not (ROOT/'configs/launcher.env').is_file():
        raise ValueError('copy configs/launcher.env.example to configs/launcher.env and edit paths; see README.md')
    if any((work/name).exists() for name in ('final_reply.txt','execution.json','dsh.stderr.log')):
        raise ValueError('execution records already exist; use a fresh workspace to retain previous results')
    env = os.environ.copy()
    with (work/'final_reply.txt').open('x',encoding='utf-8') as reply, (work/'dsh.stderr.log').open('x',encoding='utf-8') as errors:
        result = subprocess.run(['bash',str(ROOT/'scripts/start-dsh.sh'),'headless',prompt],
                                cwd=work,env=env,stdout=reply,stderr=errors,check=False)
    record = {'example':args.case,'dsh_exit_code':result.returncode,
              'note':'Host exit status does not prove all engineering requirements were met; inspect retained solver/results records.'}
    (work/'execution.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record));print('Final reply:', work/'final_reply.txt')
    return result.returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError,OSError,KeyError) as exc:
        print(f'Example error: {exc}',file=sys.stderr)
        raise SystemExit(1)
