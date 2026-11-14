#!/usr/bin/env python3
"""Verify immutable inputs, paired configuration, budgets and evidence coverage."""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json

from prompt_policy import render_prompt
from pathlib import Path


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''): digest.update(block)
    return digest.hexdigest()
def hashes(root):return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def load(path):return json.loads(path.read_text())


def main():
    p=argparse.ArgumentParser();p.add_argument('run_root',type=Path);args=p.parse_args();root=args.run_root.resolve();manifest=load(root/'manifest.json');verification=load(root/'verification.json');exposure=load(root/'exposure-audit.json')
    checks=[]
    def check(name,passed,**evidence):checks.append({'check':name,'passed':bool(passed),**evidence})
    check('all_selected_sessions_finished',len(manifest['results'])==len(manifest.get('arms',['bare','skill']))*len(manifest['tasks']) and all('ended_at_utc' in r and 'exit_code' in r for r in manifest['results']))
    check('frozen_plugin_unchanged',hashes(root/'frozen-plugin')==manifest['plugin_hashes'])
    check('frozen_launch_definitions_unchanged',hashes(root/'definition')==manifest['launch_file_hashes'])
    check('whole_process_isolation_preflights',exposure['all_arm_isolation_preflights_passed'])
    check('no_observed_organizer_or_bare_skill_content_exposure',not exposure['organizer_or_bare_skill_exposure_observed'])
    # The bank's absolute location is fixed in the launch script; compare original text too.
    bank=Path('/home/lwz/MANDiFuel-DSH-lwz/benchmarks/2026-11-12-candidate-bank/prompts')
    for task in manifest['tasks']:
        tid=task['id']; source=root/tid/'source-case'; original=Path(task['source'])
        if 'original_task_sha256' in task:
            original_prompt_text=(bank/(tid+'.txt')).read_text()
            effective,policy=render_prompt(original_prompt_text,task['original_solver_start_cap'],task['solver_start_cap'])
            check(tid+'_original_prompt_preserved',sha(root/tid/'task-original.txt')==task['original_task_sha256']==sha(bank/(tid+'.txt')))
            check(tid+'_effective_prompt_matches_declared_override',(root/tid/'task.txt').read_text()==effective and sha(root/tid/'task.txt')==task['task_sha256'] and policy==task['prompt_override'])
        else:
            check(tid+'_prompt_matches_reviewed_original',sha(root/tid/'task.txt')==task['task_sha256']==sha(bank/(tid+'.txt')))
        check(tid+'_original_source_unchanged',hashes(original)==task['source_evidence']['original_source_hashes'])
        check(tid+'_curated_source_unchanged',hashes(source)==task['source_evidence']['actor_source_hashes'])
        for arm in manifest.get('arms',['bare','skill']):
            name=tid+'/'+arm; folder=root/tid/arm; actual=verification['tasks'][tid][arm];work=folder/'workspace';summary=load(root/tid/'trace-summary.json')['arms'][arm]
            check(name+'_source_case_unchanged',hashes(work/'source-case')==hashes(source))
            relative=original.relative_to('/home/lwz/offbeat')
            check(name+'_sources_unchanged',hashes(work/'sources'/relative)==hashes(source))
            check(name+'_solver_budget',task['solver_start_cap'] is None or actual['solver_starts']<=task['solver_start_cap'],starts=actual['solver_starts'],cap=task['solver_start_cap'])
            check(name+'_execution_evidence_count',len(actual['executions'])==actual['solver_starts'])
            check(name+'_all_started_invocations_have_exit_evidence',all((Path(e['evidence_dir'])/'exit.json').is_file() for e in actual['executions']))
            check(name+'_actual_wrapper_matches_frozen_definition',sha(folder/'instrumented-bin/offbeat')==manifest['launch_file_hashes']['solver-wrapper.py'])
            for file in ['launch-arm.sh','common.patch.yml','bare.patch.yml','isolate-launch.py','preflight_toolchain.py']:
                check(name+'_launch_'+file,sha(folder/'launch-config'/file)==manifest['launch_file_hashes'][file])
            routes=summary.get('routes',[])
            check(name+'_configured_model_route',routes==[{'provider':'deepseek-official','model':'deepseek-v4-flash'}],routes=routes)
            check(name+'_single_session',summary.get('sessions')==1 if isinstance(summary.get('sessions'),int) else len(summary.get('sessions',[]))==1)
            if arm=='bare':check(name+'_no_skill_tool_calls',summary['tools_by_name'].get('skill',0)==0)
    binary=Path('/home/lwz/OpenFOAM/lwz-v2506/platforms/linux64GccDPInt32Opt/bin/offbeat')
    node=Path('/home/lwz/.nvm/versions/node/v22.23.2/bin/node')
    package=node.parent.parent/'lib/node_modules/@deepseek-ai/dsh/package.json'
    result={'checked_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'scope':'实验输入、隔离、预算和证据完整性；任务完成度单列，不用模型进程退出代替计算完成','checks':checks,'passed':all(c['passed'] for c in checks),'task_statuses':{tid:{arm:v['status'] for arm,v in pair.items()} for tid,pair in verification['tasks'].items()},'runtime':{'dsh_version':load(package)['version'],'dsh_package_sha256':sha(package),'node_sha256':sha(node),'solver_binary_sha256':sha(binary)},'organizer_evaluation_solver_starts':0}
    (root/'integrity.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[c['check'] for c in checks if not c['passed']],'task_statuses':result['task_statuses']},ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':main()
