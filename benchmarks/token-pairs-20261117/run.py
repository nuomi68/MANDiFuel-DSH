"""Freeze and execute three headless paired tasks, without presentation services."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import argparse,hashlib,json,os,shutil,signal,subprocess,sys,time
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
sys.path.insert(0,str(REPO/'benchmarks/candidate-pairs'))
from run_suite import hashes,save,sha

DSH=Path('/home/lwz/.nvm/versions/node/v22.23.2/lib/node_modules/@deepseek-ai/dsh/lib/bin.js')
REAL=Path('/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat')
ARMS=('bare','skill')
RUNTIME_FILES=['offline-exec.py','mandifuel-offline-subprocess.mjs','project-boundary.mjs','mandifuel-project-fs.mjs','mandifuel-project-policy.mjs','mandifuel-project-sandbox.mjs','project-fs-worker.mjs']
COMMON="""- id: agent-default-model
  config:
    provider: deepseek-official
    model: deepseek-v4-flash
- id: session-persistence-jsonl
  config:
    root: !!js process.env.BENCH_TRACE_ROOT
    compression: none
    packChunks: false
- id: tool-web
  disabled: true
- id: web-search-deepseek
  disabled: true
- id: web-fetch-http
  disabled: true
"""

def now():return datetime.now(timezone.utc).isoformat()

def freeze(root):
    plugin=root/'frozen-plugin';plugin.mkdir()
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=REPO).decode().split('\0')
    prefixes=('dsh/','lib/','rag/','skills/','scripts/')
    fixed={'README.md','STUDY_PROTOCOL.md','LICENSE','NOTICE','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md','CHANGELOG.md','mandifuel.json','requirements-examples.txt','configs/launcher.env.example'}
    for name in tracked:
        if name and (name.startswith(prefixes) or name in fixed):
            source=REPO/name
            if source.is_file():
                target=plugin/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    shutil.copyfile(REPO/'configs/launcher.env',plugin/'configs/launcher.env');(plugin/'configs/launcher.env').chmod(0o600)
    return plugin

def source_case(task,root):
    source=(REPO/task['source']).resolve();target=root/task['id']/'source-case';target.mkdir(parents=True)
    for name in ['0','constant','system']:
        shutil.copytree(source/name,target/name,symlinks=False)
    for name in ['rodDict','rodMaker.py','input_settings.txt']:
        if (source/name).is_file():shutil.copyfile(source/name,target/name)
    # Inputs only: no solved time, receipts, old report, comparison or expected value.
    (target/'Allrun').write_text('#!/usr/bin/env bash\nset -eo pipefail\n'+('python3 rodMaker.py\nmv blockMeshDict system/blockMeshDict\n' if task['id']=='T01' else '')+'blockMesh > log.blockMesh 2>&1\noffbeat > log.offbeat 2>&1\n')
    save(target.parent/'source-manifest.json',{'original':str(source),'copied_inputs':hashes(target),'results_supplied':False})
    return target

def prepare(task,arm,root,plugin):
    folder=root/task['id']/arm;work=folder/'workspace';work.mkdir(parents=True)
    shutil.copytree(root/task['id']/'source-case',work/'source-case')
    (work/'sources').mkdir()
    (work/'request.txt').write_text(task['prompt']+'\n')
    (work/'resources.md').write_text('本题工作区提供只读 source-case/ 完整参考输入，未提供计算结果。\nOpenFOAM 环境已加载；offbeat、blockMesh 和 Python 3.12 在 PATH 中。Allrun 提供原输入的纯计算步骤。\n只使用本地输入与已安装工具；不要联网、读取其他任务或历史会话、安装软件或修改求解器。不得创建子 agent。\n只需计算数据与简短中文说明，无需图片、网页、前端或 UI 配置。实际失败保留证据，允许修复输入后继续；未设置求解启动次数上限，纯准备任务除外。\n')
    for name in ['traces','tmp','rag-cache','instrumented-bin','launch-config','dsh-home']:(folder/name).mkdir()
    runtime=folder/'launch-config'
    shutil.copyfile(HERE/'launch-arm.sh',runtime/'launch-arm.sh')
    shutil.copyfile(REPO/'benchmarks/candidate-pairs/isolate-launch.py',runtime/'isolate-launch.py')
    for name in RUNTIME_FILES:shutil.copyfile(plugin/'dsh'/name,runtime/name)
    (runtime/'common.patch.yml').write_text(COMMON)
    base='- id: skill-filesystem\n  disabled: true\n- id: tool-skill\n  disabled: true\n'
    base+='- id: system-prompt\n  config:\n    persona: '+json.dumps('你是科学计算助手。使用本题输入和已安装的 OpenFOAM/OFFBEAT 完成用户任务，只编辑任务输入与必要批处理，不查看或修改软件实现源码。依据实际日志、退出状态和保存数据报告结果。',ensure_ascii=False)+'\n'
    for ident in ['subprocess','fs-sandbox','sandbox-policy','sandbox']:base+=f'- id: {ident}\n  disabled: true\n'
    base+='- insert:\n'
    for ident,filename in [('mandifuel-project-sandbox','mandifuel-project-sandbox.mjs'),('mandifuel-project-policy','mandifuel-project-policy.mjs'),('mandifuel-project-fs','mandifuel-project-fs.mjs'),('mandifuel-offline-subprocess','mandifuel-offline-subprocess.mjs')]:
        base+=f'    - id: {ident}\n      name: '+json.dumps(str(runtime/filename))+'\n'
        if ident=='mandifuel-project-policy':base+='      config:\n        mode: workspace-write\n        workspaceRoot: !!js process.env.MANDIFUEL_PROJECT_ROOT\n'
    (runtime/'bare-runtime.patch.yml').write_text(base)
    wrapper=folder/'instrumented-bin/offbeat';shutil.copyfile(REPO/'benchmarks/candidate-pairs/solver-wrapper.py',wrapper);wrapper.chmod(0o755)
    save(wrapper.parent/'config.json',{'workspace':str(work),'solver_start_cap':task['solver_start_cap'],'real_binary':str(REAL)})
    home=folder/'dsh-home';(home/'profiles').mkdir()
    shutil.copytree(Path('/home/lwz/.dsh/profiles/headless'),home/'profiles/headless',symlinks=True)
    (home/'profiles/node_modules').symlink_to('/home/lwz/.dsh/profiles/node_modules',target_is_directory=True)
    # Use normal local DSH authentication, without reading or exporting key values.
    for name in ['settings.yaml','.credentials.yaml','.anonymous-user-id','cordis.patch.yml']:
        p=Path('/home/lwz/.dsh')/name
        if p.is_file():shutil.copyfile(p,home/name);(home/name).chmod(0o600)
    readable=['/usr','/bin','/lib','/lib64','/etc','/etc/resolv.conf','/proc','/dev','/sys','/opt','/home/lwz/.nvm/versions/node/v22.23.2','/home/lwz/.dsh/profiles','/home/lwz/OpenFOAM','/home/lwz/offbeat/offbeatLib',str(runtime),str(wrapper.parent)]
    readable=[p for p in readable if Path(p).exists()]
    if arm=='skill':readable.append(str(plugin))
    other=root/task['id']/('skill' if arm=='bare' else 'bare')/'workspace/request.txt'
    denied=[str(root/'manifest.json'),str(other),str(REPO/'skills/prepare-offbeat-case/SKILL.md'),str(REPO/'work/cleanup-20261117/version-result.json')]
    allowed=[str(work/'request.txt'),str(REAL)]
    if arm=='bare':denied.append(str(plugin/'skills/prepare-offbeat-case/SKILL.md'))
    else:allowed.append(str(plugin/'skills/prepare-offbeat-case/SKILL.md'))
    policy={'listable':['/'],'readable':readable,'writable':[str(work),str(folder/'traces'),str(folder/'tmp'),str(folder/'rag-cache'),str(home),'/dev/null','/dev/tty'],'denied_probe_files':denied,'allowed_probe_files':allowed,'check_output':str(work/'isolation-check.json')}
    save(runtime/'isolation.json',policy)
    return dict(os.environ,BENCH_PLUGIN_ROOT=str(plugin),BENCH_PROMPT_FILE=str(root/task['id']/'task.txt'),BENCH_TRACE_ROOT=str(folder/'traces'),BENCH_ISOLATION_POLICY=str(runtime/'isolation.json'),MANDIFUEL_PROJECT_ROOT=str(work),MANDIFUEL_DEFAULT_WORKDIR=str(work),MANDIFUEL_OFFBEAT_BIN=str(wrapper.parent),MANDIFUEL_CASE_LIBRARY_ROOT=str(work/'sources'),MANDIFUEL_RAG_CACHE_DIR=str(folder/'rag-cache'),TMPDIR=str(folder/'tmp'),DSH_HOME=str(home),MPLBACKEND='Agg',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',MANDIFUEL_PRESENTATION_ENABLED='0')

def preflight(task,arm,root,env):
    folder=root/task['id']/arm
    with (folder/'preflight.stdout.log').open('w') as out,(folder/'preflight.stderr.log').open('w') as err:
        p=subprocess.run(['bash',str(folder/'launch-config/launch-arm.sh'),arm],cwd=folder/'workspace',env=dict(env,BENCH_PREFLIGHT_ONLY='1'),stdout=out,stderr=err,timeout=120)
    result={'exit_code':p.returncode,'model_requests':0,'solver_starts':0}
    result['isolation']=json.loads((folder/'workspace/isolation-check.json').read_text()) if (folder/'workspace/isolation-check.json').exists() else {}
    text=(folder/'preflight.stdout.log').read_text();result['frontend_plugin_present']='mandifuel-native-workbench' in text
    save(folder/'preflight.json',result)
    if p.returncode or not result['isolation'].get('passed') or result['frontend_plugin_present']:raise RuntimeError(f'Preflight failed: {task["id"]}/{arm}; see private logs')
    print(json.dumps({'preflight':'passed','task':task['id'],'arm':arm}),flush=True)

def run(task,arm,root,env,timeout):
    folder=root/task['id']/arm;work=folder/'workspace';record={'task_id':task['id'],'arm':arm,'started_at_utc':now(),'workspace':str(work),'timeout_seconds':timeout,'solver_start_cap':task['solver_start_cap'],'frontend':False};save(folder/'run.json',record);began=time.monotonic()
    with (folder/'stdout.log').open('w') as out,(folder/'stderr.log').open('w') as err:
        p=subprocess.Popen(['bash',str(folder/'launch-config/launch-arm.sh'),arm],cwd=work,env=env,stdout=out,stderr=err,start_new_session=True);record['pid']=p.pid;save(folder/'run.json',record)
        try:record.update(exit_code=p.wait(timeout=timeout),timed_out=False)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=15)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
            record.update(exit_code=p.returncode,timed_out=True)
    record.update(ended_at_utc=now(),wall_seconds=round(time.monotonic()-began,3),source_unchanged=hashes(work/'source-case')==hashes(root/task['id']/'source-case'));save(folder/'run.json',record);print(json.dumps(record,ensure_ascii=False),flush=True);return record

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--timeout',type=int,default=1800);p.add_argument('--preflight-only',action='store_true');args=p.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False);plugin=freeze(root);shutil.copytree(HERE,root/'definition',ignore=shutil.ignore_patterns('__pycache__'))
    tasks=json.loads((HERE/'tasks.json').read_text())['tasks']
    for task in tasks:source_case(task,root);(root/task['id']/'task.txt').write_text(task['prompt']+'\n')
    envs={}
    for task in tasks:
        for arm in ARMS:envs[task['id'],arm]=prepare(task,arm,root,plugin)
    manifest={'started_at_utc':now(),'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'model':'deepseek-official/deepseek-v4-flash','tasks':tasks,'arms':ARMS,'replicates_per_task_arm':1,'frontend_agent':False,'scope':'Current complete scientific Skills integration versus bare DSH; not a single-rule ablation. Same inputs, model, runtime and write boundary. Provided source isolates workflow from retrieval selection.','execution':'six isolated concurrent headless sessions; wall times descriptive, not repeated performance estimates','timeout_per_arm_seconds':args.timeout,'plugin_hashes':hashes(plugin),'results':[]}
    save(root/'manifest.json',manifest)
    for task in tasks:
        for arm in ARMS:preflight(task,arm,root,envs[task['id'],arm])
    manifest['all_six_preflights_passed']=True;save(root/'manifest.json',manifest)
    if args.preflight_only:return
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(run,t,a,root,envs[t['id'],a],args.timeout):(t['id'],a) for t in tasks for a in ARMS}
        for f in as_completed(futures):
            try:manifest['results'].append(f.result())
            except Exception as exc:manifest['results'].append({'task_id':futures[f][0],'arm':futures[f][1],'harness_error':str(exc)})
            save(root/'manifest.json',manifest)
    manifest.update(ended_at_utc=now(),plugin_unchanged=hashes(plugin)==manifest['plugin_hashes']);save(root/'manifest.json',manifest)

if __name__=='__main__':main()
