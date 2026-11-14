#!/usr/bin/python3
"""Common actual-start budget and per-invocation evidence, independent of Skills."""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


def now(): return datetime.now(timezone.utc).isoformat()


def append(path,value):
    with path.open('a') as stream:
        stream.write(json.dumps(value,ensure_ascii=False)+'\n'); stream.flush()


def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def times(case):
    result=[]
    if case.is_dir():
        for p in case.iterdir():
            if not p.is_dir(): continue
            try: number=Decimal(p.name)
            except InvalidOperation: continue
            if number.is_finite() and number>=0: result.append((number,p))
    return [p for n,p in sorted(result,key=lambda item:item[0])]


def snapshot(case,output):
    output.mkdir(parents=True,exist_ok=True)
    for name in ['system/controlDict','system/userParameters','constant/solverDict','rodDict','input_settings.txt','0/gapGas','0/D','0/T','0/DD','0/Cs','system/fvSolution']:
        source=case/name
        if source.is_file():
            dest=output/name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,dest)
    directories=times(case)
    inventory={'time_directories':[p.name for p in directories],'state_files':{},'root_files':{}}
    for p in directories:
        for f in sorted(p.rglob('*')):
            if f.is_file(): inventory['state_files'][f.relative_to(case).as_posix()]=sha(f)
    if directories:
        p=directories[-1]; shutil.copytree(p,output/'latest-state'/p.name,symlinks=False)
    for f in case.iterdir() if case.is_dir() else []:
        if f.is_file() and not f.name.startswith(('log.','.mandifuel')):
            inventory['root_files'][f.name]=sha(f)
    save(output/'inventory.json',inventory)
    return inventory


def case_path(argv):
    for i,arg in enumerate(argv):
        if arg=='-case' and i+1<len(argv): return Path(argv[i+1]).resolve()
        if arg.startswith('-case='): return Path(arg.split('=',1)[1]).resolve()
    return Path.cwd().resolve()


def main():
    config=json.loads((Path(__file__).resolve().parent/'config.json').read_text())
    workspace=Path(config['workspace'])
    argv=sys.argv[1:]
    informational=any(a in {'-help','--help','-help-full','-help-man','-doc','-doc-source','-version','--version'} for a in argv)
    case=case_path(argv)
    entry={'id':uuid.uuid4().hex,'kind':'information' if informational else 'solve','started_at_utc':now(),'cwd':str(Path.cwd()),'case_root':str(case),'argv':argv,'pid':os.getpid()}
    ledger=workspace/'solver-starts.jsonl'
    with (workspace/'.solver-budget.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        count=sum(bool(line.strip()) for line in ledger.read_text().splitlines()) if ledger.exists() else 0
        if not informational and config['solver_start_cap'] is not None and count>=config['solver_start_cap']:
            entry.update(kind='blocked',reason=f"实际OFFBEAT启动预算{config['solver_start_cap']}次已用尽")
        append(workspace/'binary-invocations.jsonl',entry)
        if entry['kind']=='blocked':
            print(entry['reason'],file=sys.stderr); return 75
        if not informational: append(ledger,entry)
    began=time.monotonic()
    evidence=workspace/'execution-evidence'/entry['id']
    if not informational:
        evidence.mkdir(parents=True)
        save(evidence/'start.json',entry)
        try: snapshot(case,evidence/'before')
        except Exception as exc: save(evidence/'before-error.json',{'error':str(exc)})
    output_path=evidence/'solver.log' if not informational else workspace/'.offbeat-information.log'
    with output_path.open('wb') as output:
        process=subprocess.Popen([config['real_binary'],*argv],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        while chunk:=process.stdout.read1(65536):
            output.write(chunk); output.flush(); sys.stdout.buffer.write(chunk); sys.stdout.buffer.flush()
        code=process.wait()
    result={'id':entry['id'],'kind':entry['kind'],'cwd':entry['cwd'],'case_root':str(case),'exit_code':code,'wall_seconds':time.monotonic()-began,'ended_at_utc':now()}
    append(workspace/'solver-exits.jsonl',result)
    if not informational:
        save(evidence/'exit.json',result)
        try: snapshot(case,evidence/'after')
        except Exception as exc: save(evidence/'after-error.json',{'error':str(exc)})
    return code if code>=0 else 128-code


if __name__=='__main__': raise SystemExit(main())
