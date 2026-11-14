#!/usr/bin/env python3
"""整理共享检索对照的完整性、成本与选模证据；不调用模型或求解器。"""
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO/'benchmarks/candidate-pairs'))
import analyze_suite as analysis
import audit_workflow
import audit_exposure
import render_compact_traces_zh as renderer


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def hashes(p):return {str(f.relative_to(p)):sha(f) for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
def load(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def main():
 r=Path(sys.argv[1]).resolve();m=load(r/'manifest.json');v=load(r/'verification.json');checks=[]
 def check(name,passed,**detail):checks.append({'check':name,'passed':bool(passed),**detail})
 check('all_six_sessions_finished',len(m['results'])==6 and all(x.get('ended_at_utc') for x in m['results']))
 check('frozen_plugin_unchanged',hashes(r/'frozen-plugin')==m['plugin_hashes'])
 check('shared_RAG_library_manuals_unchanged',hashes(r/'shared')==m['shared_resource_hashes'])
 check('launch_definitions_unchanged',hashes(r/'definition')==m['launch_file_hashes'])
 check('organizer_targets_unchanged',sha(r/'tasks.json')==m['tasks_sha256'])
 check('same_RAG_query_implementation',sha(r/'shared/retrieval/query.py')==sha(r/'frozen-plugin/rag/query.py'))
 exposure={'arms':{},'all_arm_isolation_preflights_passed':True,'organizer_or_bare_skill_exposure_observed':False,'interpretation':'两组共享137张离线卡、参考输入及使用手册；裸组不能读取Skill/能力表，目标标准、组间产物和历史结果被内核隔离。'}
 result={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'model':m['model'],'tasks':{},'integrity':v['integrity']}
 review={'automatic_false_positives':[],'scope':'自动源码查看标记人工复核：执行公共CLI后用sed裁剪JSON不等于读取脚本源码。原始workflow-audit.json不覆盖。'}
 workflow=load(r/'workflow-audit.json')['current']
 for task in m['tasks']:
  tid=task['id'];result['tasks'][tid]={};summary=load(r/tid/'trace-summary.json')
  check(tid+'_same_effective_prompt',sha(r/tid/'task.txt')==task['prompt_sha256'])
  for arm in ('bare','skill'):
   name=tid+'/'+arm;f=r/tid/arm;actual=v['tasks'][tid][arm];work=f/'workspace'
   pre=load(f/'preflight.json');check(name+'_isolation',pre['exit_code']==0 and pre['isolation']['passed'])
   initial=load(f/'initial-workspace.json');check(name+'_no_preselected_inputs',set(initial['files'])=={'request.txt','resources.md'} and not initial['source_case_present'] and not initial['target_case_present'])
   check(name+'_prompt_identical',sha(work/'request.txt')==task['prompt_sha256'])
   for stage in ('boot','toolchain'):check(name+'_'+stage,load(f/(stage+'.json'))['exit_code']==0)
   check(name+'_wrapper_unchanged',sha(f/'instrumented-bin/offbeat')==m['launch_file_hashes']['solver-wrapper.py'])
   starts=work/'solver-starts.jsonl';count=len(starts.read_text().splitlines()) if starts.exists() else 0
   check(name+'_all_solver_evidence_retained',count==actual['solver_starts']==len(actual['executions']) and all((Path(e['evidence_dir'])/'exit.json').exists() for e in actual['executions']))
   check(name+'_no_solve_count_cap',load(f/'instrumented-bin/config.json')['solver_start_cap'] is None)
   s=summary['arms'][arm];check(name+'_same_model_route',s.get('routes')==[{'provider':'deepseek-official','model':'deepseek-v4-flash'}])
   if arm=='bare':check(name+'_no_skill_tool',s['tools_by_name'].get('skill',0)==0)
   trace=next((f/'traces').rglob('session.jsonl'));calls,_=renderer.helper.read_session(trace);suspicious=[]
   for number,c in enumerate(calls,1):
    a=c['args'];text=str(a.get('command',''))+' '+str(a.get('file_path',''));output=str(c['output']);kind=[]
    if arm=='bare' and re.search(r'frozen-plugin|MANDIFUEL_PLUGIN_ROOT|mandifuel_prepare|mandifuel_run|SKILL\.md',text):kind.append('bare_skill_reference')
    if re.search(r'(?:^|[/\s])(?:tasks|manifest|predeclared-criteria)\.json',text) and '/execution-evidence/' not in text:kind.append('organizer_reference_candidate')
    other='skill' if arm=='bare' else 'bare'
    if re.search(r'/(?:G01|G02|M01)/'+other+r'/workspace',text):kind.append('other_arm_reference')
    if kind:
     leaked=bool(re.search(r'name:\s*(?:prepare|execute|extract|conduct|orchestrate)-offbeat-|organizer_only_references|pressures_inner_Pa',output))
     suspicious.append({'event':number,'step':c['step'],'kinds':kind,'permission_denied':'Permission denied' in output,'sensitive_content_observed':leaked,'call_id':c['id']})
   exposed=any(x['sensitive_content_observed'] for x in suspicious)
   exposure['arms'][name]={'references':suspicious,'organizer_hint_reads_observed':int(exposed),'bare_skill_document_reads_observed':int(exposed) if arm=='bare' else 0,'isolation_preflight_passed':pre['isolation']['passed']}
   exposure['organizer_or_bare_skill_exposure_observed']|=exposed
   check(name+'_no_observed_sensitive_exposure',not exposed)
   stats=analysis.arm_report(r,task,arm,actual,s,exposure['arms'][name])
   native={};events={e['id']:e for e in actual['executions']}
   for case in actual['case_checks']:
    if not case['passed']:continue
    event=events[case['event_id']];exit=load(Path(event['evidence_dir'])/'exit.json')
    elapsed=(datetime.fromisoformat(exit['ended_at_utc'])-datetime.fromisoformat(actual['run']['started_at_utc'])).total_seconds()
    key=str(case.get('radial_counts',case.get('pressure_inner_Pa','single')));native[key]=min(native.get(key,float('inf')),elapsed)
   stats['earliest_sufficient_native_results_seconds']=max(native.values()) if len(native)>=(2 if tid in ('G01','G02') else 1) else None
   stats['first_valid_native_by_required_point_seconds']=native
   w=workflow['tasks'][tid][arm];probes={key:w['before_counts'][key]+w['after_counts'][key] for key in w['before_counts']}
   for hit in w['classified_calls']:
    if 'plugin_implementation_read' in hit['categories'] and 'software_capabilities.py' in hit.get('command','') and '| sed ' in hit['command']:
     probes['plugin_implementation_read']-=1;review['automatic_false_positives'].append({'task':tid,'arm':arm,'call_id':hit['call_id'],'reason':'公共查询CLI的JSON输出被sed裁剪，没有读取Python实现文件。','command':hit['command']})
   stats['reviewed_probe_counts']=probes;stats['retrieval']=actual['retrieval'];stats['case_checks']=actual['case_checks']
   result['tasks'][tid][arm]=stats
  pair=result['tasks'][tid];pair['cost_comparable']=all(pair[a]['status']=='completed' for a in ('bare','skill'))
  if pair['cost_comparable']:pair['skill_reduction_percent']={k:100*(1-pair['skill'][k]/pair['bare'][k]) for k in ('wall_seconds','tool_calls','steps')}
 check('all_selected_sessions_same_source_library',m['no_preselected_source'])
 check('no_sensitive_exposure',not exposure['organizer_or_bare_skill_exposure_observed'])
 integrity={'passed':all(x['passed'] for x in checks),'checks':checks,'scope':'实验输入、同等检索、空目标起点、隔离、冻结、路由和执行证据；任务结果及物理误差另外列出。','organizer_solver_starts':0}
 save(r/'integrity.json',integrity);save(r/'exposure-audit.json',exposure);save(r/'workflow-review-corrections.json',review)
 result['aggregate']={}
 for arm in ('bare','skill'):
  stats=[result['tasks'][tid][arm] for tid in m['task_ids']]
  result['aggregate'][arm]={k:sum(x[k] for x in stats) for k in ('wall_seconds','tool_calls','steps','actual_solver_starts')}
  result['aggregate'][arm]['totalTokens']=sum(x['tokens']['totalTokens'] for x in stats)
 result['aggregate']['skill_reduction_percent']={k:100*(1-result['aggregate']['skill'][k]/result['aggregate']['bare'][k]) for k in ('wall_seconds','tool_calls','steps','totalTokens')}
 save(r/'comparison.json',result)
 print(json.dumps({'integrity_passed':integrity['passed'],'checks':len(checks),'failed':[x['check'] for x in checks if not x['passed']],'aggregate':result['aggregate']},ensure_ascii=False))

if __name__=='__main__':main()
