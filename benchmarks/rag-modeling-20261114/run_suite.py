#!/usr/bin/env python3
"""无预置source-case的离线RAG建模对照；共用参考资料，隔离Skill与运行证据。"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
OLD=REPO/'benchmarks/candidate-pairs'
LIBRARY=Path('/home/lwz/offbeat')
BINARY=Path('/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat')
SNAPSHOT=Path('/tmp/mandifuel-capabilities-20261114-01/mandifuel-plugin-0.4.0-alpha.8')

def now():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def hashes(p):return {str(f.relative_to(p)):sha(f) for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}


def freeze_resources(root):
 shared=root/'shared';shared.mkdir()
 shutil.copytree(root/'frozen-plugin/rag',shared/'retrieval',ignore=shutil.ignore_patterns('__pycache__'))
 docs=shared/'manuals';docs.mkdir()
 for name in ('user_guide','tools','theory_manual'):
  shutil.copytree(LIBRARY/'mkdocs/docs'/name,docs/name)
 cards=json.loads((shared/'retrieval/data/offbeat_case_cards_compact_138.json').read_text())['cards']
 library=shared/'reference-library';library.mkdir();records=[]
 allowed={'rodDict','sphereDict','rod3Ddict.json','input_settings.txt','blockMeshDict','rodMaker.py','sphereMaker.py','createBlockMeshDict.py','gasPressure.py','gasPressures','timesteps','timestepcreator.py','README_commands','README_structure'}
 for card in cards:
  source=LIBRARY/card['card_path'];target=library/card['card_path'];target.mkdir(parents=True)
  original={}
  for name in ('0','constant','system'):
   if (source/name).is_dir():
    shutil.copytree(source/name,target/name,symlinks=False)
    for f in (target/name).rglob('*'):
     if f.is_file():original[str(f.relative_to(target))]=sha(source/f.relative_to(target))
  for f in source.iterdir():
   if f.is_file() and (f.name in allowed or f.suffix in {'.unv','.msh'}):
    shutil.copyfile(f,target/f.name);original[f.name]=sha(f)
  # 公共参考配方只含常见预处理/求解，不含原始验证答案、比较或作图。
  recipe='#!/usr/bin/env bash\nset -euo pipefail\n'
  generator=next((n for n in ('rodMaker.py','sphereMaker.py','createBlockMeshDict.py') if (target/n).is_file()),None)
  if generator:
   recipe+=f'python3 {generator}\n'
   recipe+='if [[ -f blockMeshDict ]]; then mv blockMeshDict system/blockMeshDict; fi\n'
  elif not (target/'system/blockMeshDict').is_file() and (target/'blockMeshDict').is_file():recipe+='cp blockMeshDict system/blockMeshDict\n'
  if (target/'system/blockMeshDict').is_file() or generator or (target/'blockMeshDict').is_file():recipe+='blockMesh > log.blockMesh 2>&1\n'
  elif list(target.glob('*.unv')):recipe+='ideasUnvToFoam '+next(target.glob('*.unv')).name+' > log.importMesh 2>&1\n'
  if (target/'system/changeDictionaryDict').is_file():recipe+='changeDictionary > log.changeDictionary 2>&1\n'
  recipe+='offbeat > log.offbeat 2>&1\n';(target/'Allrun').write_text(recipe)
  for path,digest in original.items():assert sha(target/path)==digest,(card['card_path'],path)
  records.append({'case':card['card_path'],'original_preserved_inputs':original,'reference_recipe':'常规预处理和求解；由参考输入结构编译，不含原始验证/后处理答案。','excluded_root_files':sorted(f.name for f in source.iterdir() if f.is_file() and f.name not in original)})
 save(root/'reference-library-provenance.json',{'cards':len(cards),'cases':records,'target_inputs_prepared':False,'target_solver_starts':0})
 return shared


def prepare_arm(root,task,arm):
 folder=root/task['id']/arm;work=folder/'workspace';work.mkdir(parents=True)
 text=(HERE/'prompts'/f'{task["id"]}.effective.txt').read_text();(work/'request.txt').write_text(text)
 (work/'resources.md').write_text('本地RAG：'+str(root/'shared/retrieval/query.py')+'\n参考输入库：'+str(root/'shared/reference-library')+'\n本地使用手册：'+str(root/'shared/manuals')+'\n工作区没有source-case；目标算例由本次任务建立。\n')
 for name in ('traces','tmp','rag-cache','instrumented-bin','launch-config'):(folder/name).mkdir()
 shutil.copy2(root/'definition/solver-wrapper.py',folder/'instrumented-bin/offbeat');(folder/'instrumented-bin/offbeat').chmod(0o755)
 save(folder/'instrumented-bin/config.json',{'workspace':str(work),'solver_start_cap':None,'real_binary':str(BINARY)})
 for name in ('launch-arm.sh','common.patch.yml','bare.patch.yml','isolate-launch.py','preflight_toolchain.py','offline-exec.py','mandifuel-offline-subprocess.mjs'):
  shutil.copy2(root/'definition'/name,folder/'launch-config'/name)
 home=folder/'dsh-home';(home/'profiles').mkdir(parents=True)
 shutil.copytree(Path('/home/lwz/.dsh/profiles/headless'),home/'profiles/headless',symlinks=True)
 (home/'profiles/node_modules').symlink_to('/home/lwz/.dsh/profiles/node_modules',target_is_directory=True)
 for name in ('settings.yaml','.credentials.yaml','.anonymous-user-id','cordis.patch.yml'):
  source=Path('/home/lwz/.dsh')/name
  if source.is_file():shutil.copy2(source,home/name);(home/name).chmod(0o600)
 save(folder/'initial-workspace.json',{'files':hashes(work),'source_case_present':False,'target_case_present':False})


def configure(root,task,arm):
 folder=root/task['id']/arm;work=folder/'workspace';shared=root/'shared'
 paths=['/usr','/bin','/lib','/lib64','/etc','/etc/resolv.conf','/proc','/dev','/sys','/opt','/home/lwz/.nvm/versions/node/v22.23.2','/home/lwz/.dsh/profiles','/home/lwz/.dsh/settings.yaml','/home/lwz/.dsh/.credentials.yaml','/home/lwz/.dsh/.anonymous-user-id','/home/lwz/OpenFOAM',str(folder/'instrumented-bin'),str(folder/'launch-config'),str(shared)]
 paths=[p for p in paths if Path(p).exists()]
 other=root/task['id']/('bare' if arm=='skill' else 'skill')/'workspace/request.txt'
 denied=[str(root/'manifest.json'),str(root/'tasks.json'),str(other),str(REPO/'skills/prepare-offbeat-case/SKILL.md'),str(LIBRARY/'Cases/Verification/trisoModulesTest/hollowsphere_1D/Allrun'),str(REPO/'runs/capability-pairs-20261114-01/结果汇总.md')]
 allowed=['/etc/resolv.conf',str(work/'request.txt'),str(shared/'retrieval/query.py'),str(shared/'reference-library/Cases/Verification/NaCoolantChannelModel/vsAnalytical/constant/solverDict'),str(BINARY)]
 skill=root/'frozen-plugin/skills/prepare-offbeat-case/SKILL.md'
 if arm=='skill':paths.append(str(root/'frozen-plugin'));allowed.append(str(skill))
 else:denied.append(str(skill))
 policy={'listable':['/'],'readable':paths,'writable':[str(work),str(folder/'traces'),str(folder/'tmp'),str(folder/'rag-cache'),str(folder/'dsh-home'),'/dev/null','/dev/tty'],'denied_probe_files':denied,'allowed_probe_files':allowed,'check_output':str(work/'isolation-check.json')}
 save(folder/'launch-config/isolation.json',policy)
 env=dict(os.environ,BENCH_PLUGIN_ROOT=str(root/'frozen-plugin'),BENCH_PROMPT_FILE=str(root/task['id']/'task.txt'),BENCH_TRACE_ROOT=str(folder/'traces'),BENCH_ISOLATION_POLICY=str(folder/'launch-config/isolation.json'),MANDIFUEL_OFFBEAT_BIN=str(folder/'instrumented-bin'),MANDIFUEL_RAG_CACHE_DIR=str(folder/'rag-cache'),MANDIFUEL_CASE_LIBRARY_ROOT=str(shared/'reference-library'),OFFBEAT_RAG_QUERY=str(shared/'retrieval/query.py'),OFFBEAT_LOCAL_DOCS=str(shared/'manuals'),TMPDIR=str(folder/'tmp'),DSH_HOME=str(folder/'dsh-home'),MPLBACKEND='Agg',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
 for stage,flag in [('preflight',{'BENCH_PREFLIGHT_ONLY':'1'}),('boot',{'BENCH_PREFLIGHT_ONLY':'boot'}),('toolchain',{'BENCH_TOOLCHAIN_ONLY':'1'})]:
  with (folder/(stage+'.stdout.log')).open('w') as out,(folder/(stage+'.stderr.log')).open('w') as err:
   p=subprocess.run(['bash',str(folder/'launch-config/launch-arm.sh'),arm],cwd=work,env=dict(env,**flag),stdout=out,stderr=err,timeout=90)
  evidence=json.loads((work/'isolation-check.json').read_text()) if (work/'isolation-check.json').exists() else {}
  save(folder/(stage+'.json'),{'exit_code':p.returncode,'isolation':evidence,'model_requests':0,'solver_starts':0})
  if p.returncode or not evidence.get('passed'):raise RuntimeError(f'{stage} failed for {task["id"]}/{arm}; inspect logs')
 return env


def run_arm(root,task,arm,timeout,env):
 folder=root/task['id']/arm;work=folder/'workspace';record={'task_id':task['id'],'arm':arm,'started_at_utc':now(),'workspace':str(work),'timeout_seconds':timeout,'solver_start_cap':None,'no_target_inputs_supplied':True}
 save(folder/'run.json',record);began=time.monotonic()
 with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
  process=subprocess.Popen(['bash',str(folder/'launch-config/launch-arm.sh'),arm],cwd=work,env=env,stdout=out,stderr=err,start_new_session=True)
  record['pid']=process.pid;save(folder/'run.json',record)
  try:record.update(exit_code=process.wait(timeout=timeout),timed_out=False)
  except subprocess.TimeoutExpired:
   os.killpg(process.pid,signal.SIGTERM)
   try:process.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
   record.update(exit_code=process.returncode,timed_out=True)
 record.update(ended_at_utc=now(),wall_seconds=round(time.monotonic()-began,3));save(folder/'run.json',record)
 print(json.dumps(record,ensure_ascii=False),flush=True);return record


def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--timeout',type=int,default=2400);p.add_argument('--preflight-only',action='store_true');args=p.parse_args()
 root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
 shutil.copytree(SNAPSHOT,root/'frozen-plugin');shutil.copy2(REPO/'configs/launcher.env',root/'frozen-plugin/configs/launcher.env');(root/'frozen-plugin/configs/launcher.env').chmod(0o600)
 shutil.copytree(HERE,root/'definition',ignore=shutil.ignore_patterns('__pycache__'))
 for name in ('launch-arm.sh','common.patch.yml','bare.patch.yml','isolate-launch.py'):shutil.copy2(OLD/name,root/'definition'/name)
 shutil.copy2(HERE/'preflight_tools.py',root/'definition/preflight_toolchain.py')
 for name in ('offline-exec.py','mandifuel-offline-subprocess.mjs'):shutil.copy2(root/'frozen-plugin/dsh'/name,root/'definition'/name)
 wrapper=(OLD/'solver-wrapper.py').read_text()
 wrapper=wrapper.replace("'system/fvSolution']:","'system/fvSolution','system/fvSchemes','system/blockMeshDict','sphereDict','rod3Ddict.json']:")
 wrapper=wrapper.replace("    directories=times(case)","    if (case/'constant/polyMesh').is_dir():\n        shutil.copytree(case/'constant/polyMesh',output/'constant/polyMesh',symlinks=False)\n    directories=times(case)")
 (root/'definition/solver-wrapper.py').write_text(wrapper)
 shutil.copy2(HERE/'tasks.json',root/'tasks.json');bank=json.loads((root/'tasks.json').read_text());tasks=[]
 for t in bank['tasks']:
  folder=root/t['id'];folder.mkdir();shutil.copy2(HERE/'prompts'/f'{t["id"]}.effective.txt',folder/'task.txt')
  tasks.append({k:v for k,v in t.items() if k!='requirements'}|{'solver_start_cap':None,'expected_workflow_diagnostic':'fixed-study' if t['id'] in ('G01','G02') else 'case'})
 freeze_resources(root)
 for t in tasks:
  for arm in ('bare','skill'):prepare_arm(root,t,arm)
 manifest={'started_at_utc':now(),'task_ids':[t['id'] for t in tasks],'tasks':tasks,'arms':['bare','skill'],'model':'deepseek-official/deepseek-v4-flash','baseline':'裸DSH+同等离线RAG/参考库/手册；无Skill、能力表和Skill公共工具','treatment':'冻结当前完整Skill，不修改产品；两组相同物理题面和本地参考资料','no_preselected_source':True,'workspace_initial_content':'仅request.txt和resources.md；预检后另有isolation-check.json，无目标卡或网格','plugin_hashes':hashes(root/'frozen-plugin'),'launch_file_hashes':hashes(root/'definition'),'shared_resource_hashes':hashes(root/'shared'),'tasks_sha256':sha(root/'tasks.json'),'solver_start_limit':None,'timeout_per_arm_seconds':args.timeout,'preparatory_solver_starts':0,'results':[]}
 save(root/'manifest.json',manifest)
 envs={}
 for t in tasks:
  for arm in ('bare','skill'):
   envs[t['id'],arm]=configure(root,t,arm);print(json.dumps({'preflight':'passed','task':t['id'],'arm':arm}),flush=True)
 manifest['isolation_preflight']='all 6 selected sessions passed before model calls';save(root/'manifest.json',manifest)
 if args.preflight_only:return
 print(json.dumps({'started':str(root),'sessions':6,'baseline':manifest['baseline']},ensure_ascii=False),flush=True)
 with ThreadPoolExecutor(max_workers=6) as pool:
  pending={pool.submit(run_arm,root,t,a,args.timeout,envs[t['id'],a]):(t['id'],a) for t in tasks for a in ('bare','skill')}
  for future in as_completed(pending):
   try:result=future.result()
   except Exception as e:result={'task_id':pending[future][0],'arm':pending[future][1],'harness_error':str(e)}
   manifest['results'].append(result);save(root/'manifest.json',manifest)
 manifest.update(ended_at_utc=now(),plugin_unchanged=hashes(root/'frozen-plugin')==manifest['plugin_hashes'],shared_resources_unchanged=hashes(root/'shared')==manifest['shared_resource_hashes']);save(root/'manifest.json',manifest)

if __name__=='__main__':main()
