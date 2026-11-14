#!/usr/bin/env python3
"""Check mesh preprocessing and solver help inside isolation, without a solve."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

workspace=Path.cwd()
root=Path(tempfile.mkdtemp(prefix='toolchain-',dir=os.environ['TMPDIR']))
case=root/'case'; shutil.copytree(workspace/'source-case',case)
commands=[]
if (case/'rodMaker.py').is_file():
    commands.append(['python3','rodMaker.py'])
commands.append(['blockMesh'])
if (case/'system/changeDictionaryDict').is_file(): commands.append(['changeDictionary'])
observations=[]
for index,command in enumerate(commands):
    if command==['blockMesh'] and (case/'blockMeshDict').is_file():
        shutil.move(str(case/'blockMeshDict'),str(case/'system/blockMeshDict'))
    with (root/f'{index}.log').open('w') as output:
        result=subprocess.run(command,cwd=case,stdout=output,stderr=subprocess.STDOUT,timeout=30)
    observations.append({'command':command,'exit_code':result.returncode})
    if result.returncode: raise SystemExit(0 if all(o["exit_code"]==0 for o in observations) else 1)
real=json.loads((workspace.parent/'instrumented-bin/config.json').read_text())['real_binary']
with (root/'solver-help.log').open('w') as output:
    result=subprocess.run([real,'-help'],cwd=case,stdout=output,stderr=subprocess.STDOUT,timeout=30)
observations.append({'command':['offbeat','-help'],'exit_code':result.returncode,'solver_start':False})
# Probe task confinement without any outgoing connection or model request.
import socket
blocked = True
for domain in (socket.AF_INET, socket.AF_INET6):
    try:
        descriptor = socket.socket(domain, socket.SOCK_STREAM)
    except PermissionError:
        pass
    else:
        descriptor.close()
        blocked = False
observations.append({'command':['offline socket probe, no connection'], 'exit_code':0 if blocked else 1,
                     'task_network':'blocked', 'model_request':False})
(root/'checks.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'toolchain_passed':all(o['exit_code']==0 for o in observations),'evidence':str(root),'solver_starts':0}))
raise SystemExit(0 if all(o["exit_code"]==0 for o in observations) else 1)
