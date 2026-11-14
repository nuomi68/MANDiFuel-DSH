#!/usr/bin/env python3
"""只读本地手册、输入卡和保留日志，生成能力元数据；不启动软件或求解。"""
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
LIBRARY=Path('/home/lwz/offbeat')
spec=importlib.util.spec_from_file_location('capability_foam_reader',ROOT/'benchmarks/fuel-rod-power-ab/verify_results.py')
foam=importlib.util.module_from_spec(spec);spec.loader.exec_module(foam)
SELECTORS=['thermalSolver','mechanicsSolver','neutronicsSolver','elementTransport','materialProperties','rheology','heatSource','burnup','fastFlux','corrosion','gapGas','fgr','sliceMapper']


def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()


def value(d,k):
 v=d.get(k)
 return v[0].strip('"') if isinstance(v,list) and len(v)==1 else None


def main():
 observations=defaultdict(lambda:defaultdict(list));materials=defaultdict(list);properties=defaultdict(lambda:defaultdict(list));boundaries=defaultdict(lambda:defaultdict(list));controls=defaultdict(list);failed=[];source_files=[]
 cards=json.loads((ROOT/'rag/data/offbeat_case_cards_compact_138.json').read_text())['cards']
 for card in cards:
  relative=card['card_path'];case=LIBRARY/relative
  try:
   p=case/'constant/solverDict';s=foam.read_foam(p);source_files.append({'path':str(p),'sha256':sha(p)})
   for key in SELECTORS:
    v=value(s,key)
    if v:observations[key][v].append(relative)
   for zone,material in s.get('materials',{}).items():
    if not isinstance(material,dict):continue
    name=value(material,'material')
    if name:materials[name].append(relative)
    for key,v in material.items():
     if key.endswith('Model') and isinstance(v,list) and len(v)==1:properties[key][v[0]].append(relative)
     elif isinstance(v,dict):
      for sub,x in v.items():
       if sub.endswith('Model') and isinstance(x,list) and len(x)==1:properties[key+'/'+sub][x[0]].append(relative)
   for name in ('T','D','DD'):
    p=case/'0'/name
    if not p.is_file():continue
    source_files.append({'path':str(p),'sha256':sha(p)})
    field=foam.read_foam(p)
    for patch,bc in field.get('boundaryField',{}).items():
     if isinstance(bc,dict) and value(bc,'type'):boundaries[name][value(bc,'type')].append(relative)
   p=case/'system/controlDict'
   if p.is_file():
    c=foam.read_foam(p);u=c.get('userTime',{})
    if isinstance(u,dict) and value(u,'type'):controls[value(u,'type')].append(relative)
  except Exception as e:failed.append({'case':relative,'error':str(e)})
 runtime=defaultdict(lambda:defaultdict(list));runtime_materials=defaultdict(list);runtime_boundaries=defaultdict(lambda:defaultdict(list));evidence=[];registries=[]
 runs=['recovery-c08-pairs-20261114-01','generalization-pairs-20261114-01','parameter-plan-c06-20261114-02','run-assistant-c04-20261113-01','run-assistant-newcases-20261113-01','c06-bare-retest-20261114-01']
 for directory in runs:
  root=ROOT/'runs'/directory;p=root/'verification.json'
  if not p.exists():continue
  verified=json.loads(p.read_text())
  for tid,arms in verified['tasks'].items():
   for arm,actual in arms.items():
    for event in actual.get('executions',[]):
     folder=Path(event['evidence_dir']);entry={'id':event['id'],'task':tid,'arm':arm,'normal':event['normal'],'path':str(folder),'solver_log_sha256':sha(folder/'solver.log')}
     if event.get('error') and 'Valid types are:' in event['error']:registries.append({**entry,'error':event['error']})
     if not event['normal']:continue
     evidence.append(entry);s=foam.read_foam(folder/'before/constant/solverDict')
     for key in SELECTORS:
      v=value(s,key)
      if v:runtime[key][v].append(entry)
     for material in s.get('materials',{}).values():
      if isinstance(material,dict) and value(material,'material'):runtime_materials[value(material,'material')].append(entry)
     for name in ('T','D','DD'):
      p=folder/'before/0'/name
      if not p.is_file():continue
      for bc in foam.read_foam(p).get('boundaryField',{}).values():
       if isinstance(bc,dict) and value(bc,'type'):runtime_boundaries[name][value(bc,'type')].append(entry)
 binary=Path('/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat')
 shared=binary.parent.parent/'lib/liboffbeat.so'
 result={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         'profile':{'name':'local-offbeat-openfoam-v2506','binary_sha256':sha(binary),'shared_library_sha256':sha(shared) if shared.exists() else None,'scope':'当前本地安装；历史执行记录确认二进制身份，维护当日另记录共享库身份。文档/源卡观察不等于当前构造器注册或物理验证。'},
         'cards':len(cards),'parse_failures':failed,'selectors':observations,'materials':materials,'property_models':properties,'boundaries':boundaries,'time_units':controls,
         'runtime_selectors':runtime,'runtime_materials':runtime_materials,'runtime_boundaries':runtime_boundaries,'runtime_success_count':len(evidence),'registries':registries,'source_files':source_files,'OFFBEAT_starts':0}
 out=Path(__file__).parent/'evidence.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'cards':len(cards),'parsed':len(cards)-len(failed),'parse_failures':failed[:5],'selectors':{k:list(v) for k,v in observations.items()},'materials':list(materials),'boundaries':{k:list(v) for k,v in boundaries.items()},'runtime_successes':len(evidence)},ensure_ascii=False))

if __name__=='__main__':main()
