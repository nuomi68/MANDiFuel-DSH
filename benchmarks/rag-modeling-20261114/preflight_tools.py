#!/usr/bin/env python3
"""通用工具/检索/离线预检，无目标算例，无OFFBEAT真实启动。"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

work=Path(tempfile.mkdtemp(prefix='generic-tools-',dir=os.environ['TMPDIR']))
commands=[]
query=subprocess.run(['python3',os.environ['OFFBEAT_RAG_QUERY'],'--query','sodium coolant channel','--limit','1','--compact'],capture_output=True,text=True,timeout=45)
if query.returncode:raise RuntimeError(query.stderr)
data=json.loads(query.stdout)
assert data.get('mode')=='local' and data.get('provider_telemetry',{}).get('network_requests')==0,data
case=work/'cube';(case/'system').mkdir(parents=True);(case/'constant').mkdir()
(case/'system/blockMeshDict').write_text('''FoamFile { version 2.0; format ascii; class dictionary; object blockMeshDict; }
convertToMeters 1;
vertices ((0 0 0)(1 0 0)(1 1 0)(0 1 0)(0 0 1)(1 0 1)(1 1 1)(0 1 1));
blocks (hex (0 1 2 3 4 5 6 7) (1 1 1) simpleGrading (1 1 1));
edges (); boundary (); mergePatchPairs ();
''')
(case/'system/controlDict').write_text('FoamFile {version 2.0;format ascii;class dictionary;object controlDict;} application offbeat;startFrom startTime;startTime 0;stopAt endTime;endTime 1;deltaT 1;writeControl timeStep;writeInterval 1;')
for command in (['blockMesh','-case',str(case)],['offbeat','-help']):
 with (work/(command[0]+'.log')).open('w') as output:
  r=subprocess.run(command,cwd=case,stdout=output,stderr=subprocess.STDOUT,timeout=40)
 assert r.returncode==0,(command,r.returncode)
 commands.append({'command':command[:2],'exit_code':r.returncode,'solver_start':False})
for family in (socket.AF_INET,socket.AF_INET6):
 try:s=socket.socket(family,socket.SOCK_STREAM)
 except PermissionError:pass
 else:s.close();raise RuntimeError('task remote sockets are not blocked')
record={'toolchain_passed':True,'generic_cube_only':True,'target_case_prepared':False,'model_requests':0,'solver_starts':0,'RAG_mode':data['mode'],'RAG_network_requests':data['provider_telemetry']['network_requests'],'commands':commands}
(work/'checks.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False))
