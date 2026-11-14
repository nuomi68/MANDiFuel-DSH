#!/usr/bin/python3
"""两组共用的透明预算记录入口，数值计算仍调用原 OFFBEAT。"""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def append(path, record):
    with path.open('a') as stream:
        stream.write(json.dumps(record, ensure_ascii=False)+'\n')
        stream.flush()


def main():
    workspace=Path(__file__).resolve().parent.parent/'workspace'
    info=any(a in {'-help','--help','-help-full','-help-man','-doc','-doc-source','-version','--version'} for a in sys.argv[1:])
    entry={'id':uuid.uuid4().hex,'started_at_utc':datetime.now(timezone.utc).isoformat(),'cwd':os.getcwd(),'argv':sys.argv[1:],'pid':os.getpid(),'kind':'information' if info else 'solve'}
    ledger=workspace/'solver-starts.jsonl'
    with (workspace/'.solver-budget.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        count=sum(1 for line in ledger.read_text().splitlines() if line.strip()) if ledger.exists() else 0
        if not info and count>=5:
            entry.update(kind='blocked',reason='5次实际启动预算已用尽')
        append(workspace/'binary-invocations.jsonl',entry)
        if entry['kind']=='blocked':
            print(entry['reason'],file=sys.stderr)
            return 75
        if not info:
            append(ledger,entry)
    started=time.monotonic()
    binary='/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat'
    process=subprocess.Popen([binary,*sys.argv[1:]])
    code=process.wait()
    append(workspace/'solver-exits.jsonl',{'id':entry['id'],'kind':entry['kind'],'cwd':entry['cwd'],'exit_code':code,'wall_seconds':time.monotonic()-started,'ended_at_utc':datetime.now(timezone.utc).isoformat()})
    return code if code>=0 else 128-code


if __name__=='__main__':
    raise SystemExit(main())
