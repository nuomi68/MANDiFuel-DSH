#!/usr/bin/env python3
"""Run frozen candidate prompts against bare and skill DSH, with isolated evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from prompt_policy import render_prompt

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
BANK=REPO/'benchmarks/2026-11-12-candidate-bank'
LIBRARY=Path('/home/lwz/offbeat')
REAL_BINARY=Path('/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat')
DEFAULT_SNAPSHOT=Path('/tmp/mandifuel-candidate-pairs-20261112/mandifuel-plugin-0.4.0-alpha.8')


def now(): return datetime.now(timezone.utc).isoformat()
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def hashes(root): return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def freeze_source(source,target,task_id):
    target.mkdir()
    for name in ['0','constant','system']:
        shutil.copytree(source/name,target/name,symlinks=False)
    for name in ['rodDict','rodMaker.py','input_settings.txt']:
        if (source/name).is_file(): shutil.copyfile(source/name,target/name)
    # Freeze the existing input-driven compute recipe. Cases with a prepared
    # mesh dictionary need no generator; never copy reference comparison scripts.
    recipe='#!/usr/bin/env bash\nset -eo pipefail\n'
    if (source/'rodMaker.py').is_file():
        recipe+='python3 rodMaker.py\nmv blockMeshDict system/blockMeshDict\n'
    recipe+='blockMesh > log.blockMesh 2>&1\n'
    if (source/'system/changeDictionaryDict').is_file():
        recipe+='changeDictionary > log.changeDictionary 2>&1\n'
    recipe+='offbeat > log.offbeat 2>&1\n'
    (target/'Allrun').write_text(recipe)
    preserved={p.relative_to(target).as_posix():sha(p) for p in target.rglob('*') if p.is_file() and p.name!='Allrun'}
    if any(sha(source/relative)!=value for relative,value in preserved.items()): raise ValueError('physical input copy mismatch')
    return {'source':str(source),'original_source_hashes':hashes(source),'actor_source_hashes':hashes(target),'preserved_original_files':preserved,'recipe_changed':'保留纯计算步骤，传播失败；去掉原始预期值/比较/绘图/清理脚本','excluded_original_files':sorted(set(hashes(source))-set(hashes(target))),'original_allrun_sha256':sha(source/'Allrun')}


def prepare_arm(task,arm,root):
    task_id=task['id']; target=root/task_id/arm; workspace=target/'workspace'
    workspace.mkdir(parents=True)
    source=root/task_id/'source-case'
    shutil.copytree(source,workspace/'source-case')
    library=workspace/'sources'
    source_relative=Path(task['source']).relative_to(LIBRARY)
    shutil.copytree(source,library/source_relative)
    traces=target/'traces'; traces.mkdir()
    bindir=target/'instrumented-bin'; bindir.mkdir()
    shutil.copy2(HERE/'solver-wrapper.py',bindir/'offbeat'); (bindir/'offbeat').chmod(0o755)
    save(bindir/'config.json',{'workspace':str(workspace),'solver_start_cap':task['solver_start_cap'],'real_binary':str(REAL_BINARY)})
    runtime=target/'launch-config'; runtime.mkdir()
    for name in ['launch-arm.sh','common.patch.yml','bare.patch.yml','isolate-launch.py','preflight_toolchain.py']:
        shutil.copy2(HERE/name,runtime/name)
    # Same offline backend for both groups; no skill content is copied to the bare group.
    for name in ['offline-exec.py','mandifuel-offline-subprocess.mjs']:
        shutil.copy2(root/'frozen-plugin/dsh'/name,runtime/name)
    home=target/'dsh-home'; (home/'profiles').mkdir(parents=True)
    shutil.copytree(Path('/home/lwz/.dsh/profiles/headless'),home/'profiles/headless',symlinks=True)
    (home/'profiles/node_modules').symlink_to('/home/lwz/.dsh/profiles/node_modules',target_is_directory=True)
    for name in ['settings.yaml','.credentials.yaml','.anonymous-user-id','cordis.patch.yml']:
        original=Path('/home/lwz/.dsh')/name
        if original.is_file():
            shutil.copy2(original,home/name); (home/name).chmod(0o600)
    for name in ['tmp','rag-cache']:
        (target/name).mkdir()
    return target


def configure_isolation(task,arm,root):
    task_id=task['id']; target=root/task_id/arm; workspace=target/'workspace'
    other=root/task_id/('skill' if arm=='bare' else 'bare')
    paths=['/usr','/bin','/lib','/lib64','/etc','/etc/resolv.conf','/proc','/dev','/sys','/opt',
           '/home/lwz/.nvm/versions/node/v22.23.2','/home/lwz/.dsh/profiles',
           '/home/lwz/.dsh/settings.yaml','/home/lwz/.dsh/.credentials.yaml',
           '/home/lwz/.dsh/.anonymous-user-id','/home/lwz/OpenFOAM','/home/lwz/offbeat/offbeatLib',
           str(target/'instrumented-bin'),str(target/'launch-config')]
    paths=[p for p in paths if Path(p).exists()]
    denied=[str(BANK/'candidates.json'),str(root/'manifest.json'),str(other/'workspace/source-case/constant/solverDict'),
            str(REPO/'skills/prepare-offbeat-case/SKILL.md'),str(Path(task['source'])/'Allrun'),
            str(REPO/'runs/candidate-pairs-20261112-01/结果汇总.md')]
    allowed=[str(workspace/'source-case/constant/solverDict'),str(REAL_BINARY),str(target/'launch-config/common.patch.yml')]
    plugin_doc=root/'frozen-plugin/skills/prepare-offbeat-case/SKILL.md'
    if arm=='skill':
        paths.append(str(root/'frozen-plugin')); allowed.append(str(plugin_doc))
    else: denied.append(str(plugin_doc))
    policy={'description':'whole DSH process filesystem allowlist, including native read tools and bash descendants',
            'listable':['/'],'readable':paths,'writable':[str(workspace),str(target/'traces'),str(target/'tmp'),str(target/'rag-cache'),str(target/'dsh-home'),'/dev/null','/dev/tty'],
            'denied_probe_files':denied,'allowed_probe_files':allowed,'check_output':str(workspace/'isolation-check.json')}
    save(target/'launch-config/isolation.json',policy)
    env=dict(os.environ,BENCH_PLUGIN_ROOT=str(root/'frozen-plugin'),BENCH_PROMPT_FILE=str(root/task_id/'task.txt'),
             BENCH_TRACE_ROOT=str(target/'traces'),BENCH_ISOLATION_POLICY=str(target/'launch-config/isolation.json'),
             MANDIFUEL_OFFBEAT_BIN=str(target/'instrumented-bin'),MANDIFUEL_RAG_CACHE_DIR=str(target/'rag-cache'),
             MANDIFUEL_CASE_LIBRARY_ROOT=str(workspace/'sources'),TMPDIR=str(target/'tmp'),
             DSH_HOME=str(target/'dsh-home'),MPLBACKEND='Agg',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    # Configuration-only boot: no model requests or solver start. All six must pass before the suite runs.
    check_env=dict(env,BENCH_PREFLIGHT_ONLY='1')
    with (target/'preflight.stdout.log').open('w') as out,(target/'preflight.stderr.log').open('w') as err:
        completed=subprocess.run(['bash',str(target/'launch-config/launch-arm.sh'),arm],cwd=workspace,env=check_env,stdout=out,stderr=err,timeout=90)
    evidence=json.loads((workspace/'isolation-check.json').read_text()) if (workspace/'isolation-check.json').is_file() else {}
    save(target/'preflight.json',{'exit_code':completed.returncode,'isolation':evidence,'model_requests':0,'solver_starts':0})
    if completed.returncode!=0 or not evidence.get('passed'):
        raise RuntimeError(f'isolation/configuration preflight failed: {task_id}/{arm}; inspect preflight.stderr.log')
    with (target/'boot.stdout.log').open('w') as out,(target/'boot.stderr.log').open('w') as err:
        boot=subprocess.run(['bash',str(target/'launch-config/launch-arm.sh'),arm],cwd=workspace,env=dict(env,BENCH_PREFLIGHT_ONLY='boot'),stdout=out,stderr=err,timeout=90)
    if boot.returncode!=0:
        raise RuntimeError(f'boot preflight failed: {task_id}/{arm}; inspect boot.stderr.log')
    with (target/'toolchain.stdout.log').open('w') as out,(target/'toolchain.stderr.log').open('w') as err:
        toolchain=subprocess.run(['bash',str(target/'launch-config/launch-arm.sh'),arm],cwd=workspace,env=dict(env,BENCH_TOOLCHAIN_ONLY='1'),stdout=out,stderr=err,timeout=90)
    if toolchain.returncode!=0:
        raise RuntimeError(f'toolchain preflight failed: {task_id}/{arm}; inspect toolchain logs')
    return env


def run_arm(task,arm,root,timeout,env):
    task_id=task['id']; target=root/task_id/arm; workspace=target/'workspace'
    record={'task_id':task_id,'arm':arm,'started_at_utc':now(),'workspace':str(workspace),'timeout_seconds':timeout,'solver_start_cap':task['solver_start_cap'],'read_isolation':'kernel Landlock allowlist, fail closed','task_network':'offline subprocess seccomp; native web disabled in both arms'}
    save(target/'run.json',record); began=time.monotonic()
    with (target/'stdout.log').open('w') as out,(target/'stderr.log').open('w') as err:
        process=subprocess.Popen(['bash',str(target/'launch-config/launch-arm.sh'),arm],cwd=workspace,env=env,stdout=out,stderr=err,start_new_session=True)
        record['pid']=process.pid; save(target/'run.json',record)
        try: record.update(exit_code=process.wait(timeout=timeout),timed_out=False)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL); process.wait()
            record.update(exit_code=process.returncode,timed_out=True)
    record.update(ended_at_utc=now(),wall_seconds=round(time.monotonic()-began,3),source_unchanged=hashes(workspace/'source-case')==hashes(root/task_id/'source-case'))
    save(target/'run.json',record)
    print(json.dumps(record,ensure_ascii=False),flush=True)
    return record


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True,type=Path); p.add_argument('--ids',nargs='+',default=['P02','C04','W01']); p.add_argument('--arms',nargs='+',choices=['bare','skill'],default=['bare','skill']); p.add_argument('--snapshot',type=Path,default=DEFAULT_SNAPSHOT); p.add_argument('--timeout',type=int,default=1800); p.add_argument('--preflight-only',action='store_true'); p.add_argument('--design-file',type=Path); p.add_argument('--solver-start-limit',type=int,help='Optional explicit cap for solve tasks; default: unlimited. No-solve tasks remain at zero.')
    args=p.parse_args();
    if args.solver_start_limit is not None and args.solver_start_limit < 1:p.error('--solver-start-limit must be positive')
    args.arms=list(dict.fromkeys(args.arms)); root=args.output.resolve(); root.mkdir(parents=True,exist_ok=False)
    bank=json.loads((BANK/'candidates.json').read_text()); entries={t['id']:t for t in bank['tasks']}
    tasks=[]
    shutil.copytree(args.snapshot,root/'frozen-plugin'); (root/'frozen-plugin/configs').mkdir(exist_ok=True)
    shutil.copyfile(REPO/'configs/launcher.env',root/'frozen-plugin/configs/launcher.env')
    os.chmod(root/'frozen-plugin/configs/launcher.env',0o600)
    shutil.copytree(HERE,root/'definition',ignore=shutil.ignore_patterns('__pycache__'))
    for task_id in args.ids:
        t=entries[task_id]; prompt=BANK/t['prompt_file']; target=root/task_id; target.mkdir()
        if prompt.read_text().strip()!=t['task'].strip(): raise ValueError('prompt differs from reviewed candidate')
        shutil.copy2(prompt,target/'task-original.txt')
        cap=0 if t['solver_start_cap']==0 else args.solver_start_limit
        effective,policy=render_prompt(prompt.read_text(),t['solver_start_cap'],cap)
        (target/'task.txt').write_text(effective)
        save(target/'prompt-policy.json',policy)
        source=LIBRARY/t['source_case_paths'][0]
        evidence=freeze_source(source,target/'source-case',task_id)
        save(target/'source-manifest.json',evidence)
        task={'id':task_id,'title':t['title'],'source':str(source),'solver_start_cap':cap,'original_solver_start_cap':t['solver_start_cap'],'prompt_override':policy,'original_task_sha256':sha(prompt),'expected_workflow_diagnostic':t['expected_workflow'],'task_sha256':sha(target/'task.txt'),'source_evidence':evidence}
        tasks.append(task)
    manifest={'started_at_utc':now(),'task_ids':args.ids,'arms':args.arms,'model':'deepseek-official/deepseek-v4-flash','design':f'{len(tasks)} tasks, {len(args.arms)*len(tasks)} independent concurrent DSH sessions; selected arms only, isolated workspaces, source copies, traces and budgets','prompt_policy':'保留原题物理要求；按用户修订默认撤销旧题库的求解次数限额，输入错误允许修复重算；原题面、有效题面与变更逐条保存。不注入案例解法、参考解或历史轨迹。','preparatory_solver_starts':0,'read_isolation':'Landlock allowlist applied to entire DSH process and descendants; organizer files, other arms, prior runs, original Allrun and bare plugin reads denied','tasks':tasks,'plugin_hashes':hashes(root/'frozen-plugin'),'launch_file_hashes':hashes(root/'definition'),'timeout_per_arm_seconds':args.timeout,'results':[]}
    if args.design_file:
        shutil.copy2(args.design_file,root/'experiment-design.json')
        manifest['experiment_design_sha256']=sha(root/'experiment-design.json')
    save(root/'manifest.json',manifest)
    # The unselected arm receives only an input fixture for the read-denial probe.
    # It has no DSH session, solver invocation or performance measurement.
    for t in tasks:
        for arm in ['bare','skill']: prepare_arm(t,arm,root)
    environments={}
    for t in tasks:
        for arm in args.arms:
            environments[(t['id'],arm)]=configure_isolation(t,arm,root)
            print(json.dumps({'preflight':'passed','task':t['id'],'arm':arm}),flush=True)
    manifest['isolation_preflight']=f'all {len(environments)} selected sessions passed before any model request'; save(root/'manifest.json',manifest)
    if args.preflight_only: return
    print(json.dumps({'started':str(root),'tasks':args.ids,'sessions':len(args.arms)*len(tasks),'budgets':{t['id']:t['solver_start_cap'] for t in tasks}},ensure_ascii=False),flush=True)
    results=[]
    with ThreadPoolExecutor(max_workers=len(args.arms)*len(tasks)) as pool:
        pending={pool.submit(run_arm,t,a,root,args.timeout,environments[(t['id'],a)]):(t['id'],a) for t in tasks for a in args.arms}
        for future in as_completed(pending):
            try: results.append(future.result())
            except Exception as exc: results.append({'task_id':pending[future][0],'arm':pending[future][1],'harness_error':str(exc)})
            manifest['results']=results; save(root/'manifest.json',manifest)
    manifest.update(ended_at_utc=now(),plugin_unchanged=hashes(root/'frozen-plugin')==manifest['plugin_hashes'])
    save(root/'manifest.json',manifest)


if __name__=='__main__': main()
