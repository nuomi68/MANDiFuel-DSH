"""Run isolated headless DSH triples, blocking on completion. No web host or UI agent."""
import argparse,concurrent.futures,csv,hashlib,importlib.util,json,os,random,shutil,sys,time
from pathlib import Path
from tasks import ROOT,RUNS,TASKS,sources,frames,columns
from reference import values
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pairs',ROOT/'benchmarks/token-pairs-20261117/run.py')
pairs=importlib.util.module_from_spec(spec);spec.loader.exec_module(pairs)
ARMS=('bare','skill','skill_rag')
def save(p,v):
    tmp=p.with_suffix('.new');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def frozen_plugins(root):
    full=pairs.freeze(root)
    # The isolated actor has its own physical workspace. Machine-specific shared
    # runs pin is irrelevant here; remove it only from the experiment snapshot.
    cfg=full/'configs/launcher.env'
    cfg.write_text('\n'.join(l for l in cfg.read_text().splitlines() if not l.startswith('MANDIFUEL_RUNS_ROOT='))+'\n')
    for file in ['dsh/run-assistant-persona.md','STUDY_PROTOCOL.md','skills/prepare-offbeat-case/SKILL.md','README.md']:
        p=full/file
        lines=[l for l in p.read_text().splitlines() if not any(k in l for k in ('experience/','经验卡','经验条目','经验检索','经验库','审核经验','联合查询','联合检索','--experience-limit'))]
        p.write_text('\n'.join(lines)+'\n')
    shared='\n本轮使用工作区内随题给定的输入或观测。需要另查算例模型约定时，可用本地 rag/query.py 与九分面词表核对。遵循题面的计算或只读后处理范围。\n'
    persona=full/'dsh/run-assistant-persona.md'
    persona.write_text(persona.read_text()+shared)
    skill=root/'skills-without-experience';shutil.copytree(full,skill)
    shutil.rmtree(skill/'rag/experience')
    persona.write_text(persona.read_text()+'本组额外使用审核经验库。先用一次 python3 "$MANDIFUEL_PLUGIN_ROOT/rag/experience/experience_rag.py" query --query "本题物理问题与英文工程关键词" --limit 3 --compact。只采纳与当前模型、单位和条件相符的条目。无相关项时继续独立计算。在说明中注明采用或未采用的经验。\n')
    return full,skill
def source(t,root):
    tid,title,key,kind,question,units=t
    orig=(RUNS/sources[key]).resolve();dst=root/tid/'source-case';dst.mkdir(parents=True)
    if kind=='solve':
        for name in ('0','system','constant'):shutil.copytree(orig/name,dst/name,symlinks=False,ignore=shutil.ignore_patterns('polyMesh','__pycache__','*.bak','*.orig'))
        if not (dst/'system/blockMeshDict').exists():raise ValueError((tid,'missing blockMeshDict'))
        recipe='#!/usr/bin/env bash\nset -eu\nblockMesh > log.blockMesh 2>&1\n'
        if (dst/'system/changeDictionaryDict').is_file():recipe+='changeDictionary > log.changeDictionary 2>&1\n'
        (dst/'Allrun').write_text(recipe+'offbeat > log.offbeat 2>&1\n')
    elif kind=='field':
        shutil.copytree(orig/'constant/polyMesh',dst/'constant/polyMesh')
        ts,fields=frames[tid]
        for tm in ts:
            out=dst/tm;out.mkdir()
            for field in fields:shutil.copyfile(orig/tm/field,out/field)
            if (orig/tm/'polyMesh').is_dir():shutil.copytree(orig/tm/'polyMesh',out/'polyMesh')
        if tid=='P14':(dst/'units.txt').write_text('输入 fastFlux 的数值约定为 n/(cm²·s)，物理时刻单位 s。\n')
    elif tid=='P15':shutil.copyfile(orig,dst/'observations.dat')
    else:
        with orig.open() as src,(dst/'observations.csv').open('w') as out:
            writer=csv.DictWriter(out,columns[tid],extrasaction='ignore');writer.writeheader();writer.writerows(csv.DictReader(src))
    save(dst.parent/'inputs.json',{'origin':str(orig),'snapshot':pairs.hashes(dst)})
    return dst
def prompt(t):
    tid,title,key,mode,q,u=t
    context=('由 source-case/ 提供冻结的初始输入，在自己的独立算例目录从初态真实执行 OFFBEAT；保留求解日志和终态场。' if mode=='solve'
             else '本题是后处理。使用 source-case/ 给定的原始场或观测表，无需启动求解器。')
    return f'{q}\n{context}\n在当前工作目录写 answer.json，字段 a 和 b 分别为以上两个工程量的有限数值，按题目顺序，单位分别为 {u[0]} 与 {u[1]}。另用 source 字符串说明本次读取的数据文件和物理取数口径。只需给出计算结果与简短说明。'
def prepare(t,arm,root,plugins):
    tid=t[0];plugin=plugins[1] if arm=='skill' else plugins[0]
    task=dict(id=tid,prompt=prompt(t),solver_start_cap=None if t[3]=='solve' else 0)
    env=pairs.prepare(task,arm,root,plugin)
    env['MANDIFUEL_RUNS_ROOT']=''
    f=root/tid/arm;work=f/'workspace'
    (work/'resources.md').write_text('source-case/ 为随题输入。使用已安装的 OpenFOAM/OFFBEAT 与本地 Python。仅访问本题数据与分配的工具，禁止调用其他 agent、联网、读取历史任务或修改软件实现。回答本题无需联网、图片或网页。\n')
    r=f/'launch-config';p=r/'launch-arm.sh';p.write_text(p.read_text().replace('[[ "$arm" == skill ]]','[[ "$arm" != bare ]]'))
    pp=r/'isolation.json';policy=json.loads(pp.read_text())
    if arm=='skill_rag':policy['readable'].append(str(plugin))
    exp=plugins[0]/'rag/experience/experience_rag.py'
    policy['denied_probe_files']=[x for x in policy['denied_probe_files'] if 'cleanup-20261117' not in x]
    policy['denied_probe_files'].append(str(root/'reference.json'))
    if arm!='skill_rag':policy['denied_probe_files'].append(str(exp))
    else:policy['allowed_probe_files'].append(str(exp))
    save(pp,policy)
    return task,env

def remove_temporary_auth(folder):
    for name in ('.credentials.yaml', '.anonymous-user-id'):
        (folder / 'dsh-home' / name).unlink(missing_ok=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('--workers',type=int,default=12);ap.add_argument('--timeout',type=int,default=1200);args=ap.parse_args()
    root=args.root.resolve();root.mkdir(mode=0o700,parents=True,exist_ok=False)
    plugins=frozen_plugins(root)
    shutil.copytree(HERE,root/'definition',ignore=shutil.ignore_patterns('__pycache__'))
    randomizer=random.Random(20261119);schedule=[]
    items=list(TASKS);randomizer.shuffle(items)
    for t in items:
        arms=list(ARMS);randomizer.shuffle(arms);schedule.extend((t[0],a) for a in arms)
    manifest={'version':'three-arm-20-v1','commit':os.popen('git rev-parse HEAD').read().strip(),'started':pairs.now(),'tasks':[{'id':t[0],'title':t[1],'mode':t[3],'units':t[5]} for t in TASKS],'arms':ARMS,'schedule':schedule,'model':'deepseek-official/deepseek-v4-flash','timeout':args.timeout,'workers':args.workers,'repeats':1,'frontend':False,'experiment_files_sha256':pairs.hashes(root/'definition'),'plugins_sha256':{k:pairs.hashes(p) for k,p in zip(('skill_rag','skill'),plugins)},'score':'Success: completed turn, source unchanged, requested 2 finite outputs with nonempty source, and raw terminal fields plus normal exit for solves / no solve for postprocessing. Physics: unconditional 20-task denominator, success and both independent numeric checks pass; separately provide conditional rate and individual checks. Numeric acceptance max(abs(ref)*0.005, 1e-12) in requested units; values in answer.json already in specified units.'}
    save(root/'manifest.json',manifest)
    refs={};envs={}
    for t in TASKS:
        dst=source(t,root);(dst.parent/'task.txt').write_text(prompt(t)+'\n')
        refs[t[0]]=list(values(t,None if t[3]=='solve' else dst))
        print('reference',t[0],flush=True)
    save(root/'reference.json',refs)
    for t in TASKS:
        for a in ARMS:envs[t[0],a]=prepare(t,a,root,plugins)
    def one(key):
        tid,a=key;t,env=envs[key]
        try:
            pairs.preflight(t,a,root,env)
            return pairs.run(t,a,root,env,args.timeout)
        finally:
            remove_temporary_auth(root/tid/a)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(one,k):k for k in schedule}
        for f in concurrent.futures.as_completed(futures):
            try:results.append(f.result())
            except Exception as e:results.append({'task_id':futures[f][0],'arm':futures[f][1],'infrastructure_error':str(e)})
            save(root/'progress.json',results)
    print('finished',len(results),flush=True)
if __name__=='__main__': main()
