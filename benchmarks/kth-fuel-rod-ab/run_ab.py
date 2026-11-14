#!/usr/bin/env python3
"""冻结同一题面与当前技能，运行两个隔离的 DSH 会话并保留原始证据。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
SOURCE=Path('/home/lwz/offbeat/Cases/testCases/exerciseOFFBEAT/case1_solved')
SNAPSHOT=Path('/tmp/mandifuel-workflow-routing-final-20261112/mandifuel-plugin-0.4.0-alpha.8')


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def run_arm(arm,root,timeout):
    target=root/arm
    workspace=target/'workspace'
    workspace.mkdir(parents=True)
    shutil.copytree(root/'source-case',workspace/'source-case')
    traces=target/'traces'; traces.mkdir()
    bindir=target/'instrumented-bin'; bindir.mkdir()
    shutil.copy2(HERE/'solver-wrapper.py',bindir/'offbeat')
    (bindir/'offbeat').chmod(0o755)
    env=dict(os.environ,BENCH_PLUGIN_ROOT=str(root/'frozen-plugin'),BENCH_TRACE_ROOT=str(traces),MANDIFUEL_OFFBEAT_BIN=str(bindir),MANDIFUEL_RAG_CACHE_DIR=str(target/'rag-cache'),MPLBACKEND='Agg',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    result={'arm':arm,'started_at_utc':now(),'workspace':str(workspace),'timeout_seconds':timeout}
    save(target/'run.json',result)
    start=time.monotonic()
    with (target/'stdout.log').open('w') as out,(target/'stderr.log').open('w') as err:
        process=subprocess.Popen(['bash',str(HERE/'launch-arm.sh'),arm],cwd=workspace,env=env,stdout=out,stderr=err,start_new_session=True)
        result['pid']=process.pid; save(target/'run.json',result)
        try:
            result.update(exit_code=process.wait(timeout=timeout),timed_out=False)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL); process.wait()
            result.update(exit_code=process.returncode,timed_out=True)
    result.update(ended_at_utc=now(),wall_seconds=round(time.monotonic()-start,3),source_unchanged=hashes(workspace/'source-case')==hashes(root/'source-case'))
    save(target/'run.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--timeout',default=1800,type=int)
    args=parser.parse_args()
    root=args.output.resolve(); root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(SNAPSHOT,root/'frozen-plugin')
    (root/'frozen-plugin/configs').mkdir(exist_ok=True)
    shutil.copy2(REPO/'configs/launcher.env',root/'frozen-plugin/configs/launcher.env')
    shutil.copytree(SOURCE,root/'source-case',symlinks=False)
    shutil.copy2(HERE/'task.txt',root/'task.txt')
    shutil.copytree(HERE,root/'definition',ignore=shutil.ignore_patterns('__pycache__','references'))
    refs=root/'references'; refs.mkdir()
    pdf=Path('/tmp/kth-applied-reactor-technology.pdf')
    if pdf.read_bytes()[:5]!=b'%PDF-': raise RuntimeError('官方PDF下载无效')
    shutil.copy2(pdf,refs/'Applied-Reactor-Technology-2011.pdf')
    manifest={'started_at_utc':now(),'source':'https://www.diva-portal.org/smash/get/diva2%3A500610/fulltext01.pdf','exercise':'KTH Applied Reactor Technology, 2011, Example 4-2, p.103','model':'deepseek-official/deepseek-v4-flash','design':'one paired run, concurrent arms, independent workspaces, serial solves per arm','solver_start_budget_per_arm':5,'timeout_per_arm_seconds':args.timeout,'reference_answers_exposed_to_arms':False,'prior_trajectory_exposed_to_arms':False,'official_source_case':str(SOURCE),'task_sha256':hashlib.sha256((root/'task.txt').read_bytes()).hexdigest(),'source_hashes':hashes(root/'source-case'),'plugin_hashes':hashes(root/'frozen-plugin'),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()}
    save(root/'manifest.json',manifest)
    print(json.dumps({'started':str(root),'frozen_skill_files':len(manifest['plugin_hashes']),'source_files':len(manifest['source_hashes'])},ensure_ascii=False),flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda arm:run_arm(arm,root,args.timeout),['bare','skill']))
    manifest.update(ended_at_utc=now(),results=results,plugin_unchanged=hashes(root/'frozen-plugin')==manifest['plugin_hashes'])
    save(root/'manifest.json',manifest)


if __name__=='__main__': main()
