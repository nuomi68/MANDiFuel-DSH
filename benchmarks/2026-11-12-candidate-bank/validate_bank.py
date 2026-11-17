#!/usr/bin/env python3
"""检查新版题面及合同；不会调用模型、网格工具或求解器。"""
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib,json,re

BANK=Path(__file__).resolve().parent
REPO=BANK.parent.parent
REQUIRED_SPEC={'geometry','materials','physics','initial_conditions','boundary_conditions','forcing','time_domain','outputs'}
FORBIDDEN=r'source[-_ ]?case|sources/|target-case|工作目录|工作区|独立目录|源库|结果根目录|result_root|PATH|Allrun|prepare\.json|不改求解器|只读权限|参考解|评分|评测'

def main():
 b=json.loads((BANK/'candidates.json').read_text());entries={t['id']:t for t in b['tasks']};errors=[];checks=[];tasks=[]
 def check(label,truth):
  checks.append(label)
  if not truth:errors.append(label)
 for filename in ['execution-manifest.json','auxiliary-manifest.json']:
  m=json.loads((BANK/filename).read_text());check(filename+':contract',m['execution_contract']=='physical_spec_v2');check(filename+':count',len(m['tasks'])==m['task_count'])
  for t in m['tasks']:
   tid=t['id'];p=BANK/t['prompt_file'];s=p.read_text();sha=hashlib.sha256(p.read_bytes()).hexdigest();tasks.append(t)
   check(tid+':hash',sha==t['prompt_sha256']);check(tid+':no_environment_or_oracle_boilerplate',not re.search(FORBIDDEN,s,re.I));check(tid+':readiness_honest',t['ready_for_formal_run'] is False)
   if tid in entries:
    entry=entries[tid];check(tid+':task_equals_file',entry['task']==s);check(tid+':metadata_hash',entry['prompt_sha256']==sha);check(tid+':title',t['title']==entry['title']);check(tid+':source_only_organizer','组织者' in entry['source_role'])
   else:
    check(tid+':known_extra',tid=='KTH01');entry=b['existing_kth_metadata']
   if t['input_mode']=='model_from_physical_spec':
    spec=entry['model_spec'];check(tid+':complete_physical_spec',spec is not None and REQUIRED_SPEC<=set(spec) and all(spec[k] for k in REQUIRED_SPEC));check(tid+':new_model_action','建' in s);check(tid+':runtime_cap_external',t['solver_start_cap'] is None)
   elif t['input_mode']=='supplied_research_data':
    check(tid+':data_contract',bool(entry['required_assets']))
   if t['task_kind']=='auxiliary':check(tid+':no_solve_scope',t['solver_start_cap']==0)
 check('unique_task_ids',len({t['id'] for t in tasks})==29==len(tasks));check('new_models_18',sum(t['input_mode']=='model_from_physical_spec' for t in tasks)==18);check('default_solve_19',sum(t['task_kind']=='solve' for t in tasks)==19);check('auxiliary_10',sum(t['task_kind']=='auxiliary' for t in tasks)==10)
 provenance=json.loads((BANK/'redesign-provenance.json').read_text());archive=REPO/provenance['original_snapshot']
 for r in provenance['changes']:
  check(r['id']+':archive_hash',hashlib.sha256((archive/'prompts'/f"{r['id']}.txt").read_bytes()).hexdigest()==r['before_sha256']);check(r['id']+':revision_hash',hashlib.sha256((BANK/'prompts'/f"{r['id']}.txt").read_bytes()).hexdigest()==r['after_sha256'])
 check('W01_transition_and_checkpoint_aligned',(792000-3600)%78840==0 and (1580400-3600)%78840==0 and 3600%360==0)
 check('W01_exact_times_declared',all(x in (BANK/'prompts/W01.txt').read_text() for x in ['3600 s','360 s','78840 s','792000 s','1580400 s']))
 links=0
 for name in ['题库总览.md','题设重设计记录.md','去模板化记录.md']:
  p=BANK/name
  for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if target.startswith(('http://','https://','#')):continue
   links+=1;check(name+':link:'+target,(p.parent/target).exists())
 texts=[(BANK/t['prompt_file']).read_text().strip() for t in tasks]
 final_paragraphs=Counter(s.split('\n\n')[-1] for s in texts)
 out={'passed':not errors,'checked_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'scope':'题面/物理规格结构/文件哈希/目录政策分离/历史归档/链接的静态检查；不代表物理可解性或误差容差已验证','benchmark_revision':b['benchmark_revision'],'prompt_files':len(tasks),'new_model_solve_tasks':18,'continuation_solve_tasks':1,'auxiliary_tasks':10,'static_checks':len(checks),'relative_links_checked':links,'forbidden_prompt_boilerplate_matches':sum(bool(re.search(FORBIDDEN,s,re.I)) for s in texts),'unique_final_paragraphs':len(final_paragraphs),'largest_identical_final_paragraph_group':max(final_paragraphs.values()),'ready_for_formal_run':False,'numeric_validation':'not performed for revised models','model_validation':'not performed','dsh_runs_performed':0,'offbeat_starts_performed':0,'old_inventory_record':'runs/benchmark-redesign-20261117-01/original-bank/catalog-check.json','errors':errors}
 (BANK/'catalog-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False,indent=2));return 1 if errors else 0
if __name__=='__main__':raise SystemExit(main())
