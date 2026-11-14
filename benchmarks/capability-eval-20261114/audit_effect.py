#!/usr/bin/env python3
"""只审计可观察动作、准备记录和原生输入；不读取或导出模型内部推理。"""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'benchmarks/candidate-pairs'))
import evaluate_suite as evaluator
import render_compact_traces_zh as render

# 手工复核标注：序号对应中文一行轨迹，每条断言动作原名以防漂移。
MARKS={
'C08':[
 (16,'avoidable','Check plugin root env var','已准备环境再次枚举环境变量与插件路径。'),
 (4,'merge_candidate','List workspace and source-case','给定源目录后先列工作区；可与必要输入批量读取合并。'),
 (9,'merge_candidate','List prepare references','技能已提供参考路径，独立列目录可省或合并。'),
 (23,'merge_candidate','Count cellToRegion labels','紧接前次读取同一标签场，统计可在首次读取中完成。'),
 (19,'recovery','Fix and rerun preparation script','准备脚本接口调用错误后修改并重试。'),
 (20,'recovery','Patch axialProfile readback and rerun','修复引用数据的回读路径，准备阶段重试，不是求解重试。'),
 (28,'recovery','Run extraction script','长提取首次前台提交，60秒被终止。'),
 (29,'recovery','Run extraction in background','在后台从头重新提交提取，已有前台计算未复用。'),
 (31,'recovery','Fix sector geometry parsing','修复自写几何字面量解析。'),
 (32,'recovery','Rerun extraction with fixed geometry','修复几何后重读全部请求历史。'),
 (35,'recovery','Fix print units, rerun extraction','修正单位打印仍重跑整个提取。'),
 (38,'recovery','Use nominal radius, rerun extraction','修正功率域换算时再次重跑取场流程，数据缓存可隔离此成本。'),
],
'C05':[
 (5,'avoidable','Inspect plugin root','已有插件路径与接口仍单独检查插件根目录。'),
 (13,'avoidable','Query capabilities for creep model','查询入口不接受具体模型值，返回未收录；属于可改善接口造成的绕路。'),
 (4,'merge_candidate','List workspace and source case','工作区枚举可与源输入批量读取合并。'),
 (6,'merge_candidate','List source case files','单独源目录枚举可与同一初读规划合并。'),
 (15,'merge_candidate','Show capabilities summary','索引已有查询主题，失败后再读摘要；可由查询入口一次返回相关项。'),
 (16,'merge_candidate','Read materials and geometry reference','此前已grep同一材料页；相关段可一次返回，保留必要模型信息。'),
 (17,'merge_candidate','Grep dependencies for creep','跨页grep无命中；可由模型到依赖的索引减少空查。'),
 (18,'merge_candidate','Grep input bindings for creep/strain','继续跨另一参考页搜索；可与相关能力资料同批定位。'),
 (34,'merge_candidate','Show creep strain history CSV','紧接上一步再次显示同一历史表，可一起核对表和量纲。'),
 (39,'merge_candidate','edit','报告已写出后连续修改，可在数据核对后联动成稿。'),
 (43,'merge_candidate','edit','再次单独修改同一报告，属于交付编辑合并候选。'),
 (30,'recovery','Extract creep/elastic/total strain and history','长提取首次前台提交被60秒终止。'),
 (31,'recovery','Run extraction with longer timeout','转后台后重新提取，首次工作未复用。'),
],
'F02':[
 (14,'avoidable','List plugin skill resources','技能入口已给出所需路径，仍遍历插件资源。'),
 (32,'avoidable','Analytic two-layer plane-strain Lame check','题目仅要求计算交付，额外引入解析解验证。'),
 (33,'avoidable','Analytic two-layer plane-strain Lame check (no numpy)','附加解析检查因numpy不可用再次改写；不影响题目所需原生求解。'),
 (3,'merge_candidate','List workspace and source-case','可并入首批必要输入读取。'),
 (19,'merge_candidate','read','读取通用燃料棒设计参考；本题输入已明确，可直接使用所需Study和弹性接口。'),
 (35,'merge_candidate','read','同一任务脚本分段读取，可同轮读所需段；不声称与上一步读取范围完全相同。'),
 (36,'merge_candidate','edit','交付脚本开始逐项改表格/报告，可合并相关变更。'),
 (37,'merge_candidate','Regenerate deliverable tables and report','改一点即重新生成，后续还有多次同类报告生成。'),
 (39,'merge_candidate','edit','再次修改同一交付脚本。'),
 (40,'merge_candidate','Regenerate and verify per-radius profile','再次生成剖面；保留分组正确性核对，但可与其他报告变更合并。'),
 (41,'merge_candidate','edit','连续修改同一脚本中的报告内容。'),
 (42,'merge_candidate','edit','继续单独修改同一脚本。'),
 (43,'merge_candidate','Regenerate report and print it','再次运行报告生成。'),
 (44,'merge_candidate','Reorder report section and regenerate','仅调整章节顺序后再生成，适合最后统一成稿。'),
 (22,'recovery','edit','修复任务脚本导入；此处是运行脚本，不是修改软件实现。'),
 (23,'recovery','Patch imports and check record','继续修复导入与检查记录，发生在实际Study前。'),
]}
LABELS={'avoidable':'明确绕路/可前置消除','merge_candidate':'可合并候选，必要内容仍保留','recovery':'故障/取数方案恢复成本，不视为可直接删除'}


def load(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def commands(call):return str(call['args'].get('command',''))+' '+str(call['args'].get('file_path',''))


def main():
 root=Path(sys.argv[1]).resolve();comparison=load(root/'comparison.json');workflow=load(root/'workflow-audit.json')['current'];verified=load(root/'verification.json')
 result={'scope':'可观察工具事件的保守人工复核，不是每次文件IO计数；目录和报告编辑多数只列合并候选，必要恢复与后台等待另列。各标注按工具事件计数，同一故障可能包含初次失败及修复动作，不据此推算可节省秒数。','tasks':{}}
 for tid in ('C08','C05','F02'):
  result['tasks'][tid]={}
  for arm in ('bare','skill'):
   trace=next((root/tid/arm/'traces').rglob('session.jsonl'));calls,_=render.helper.read_session(trace)
   audit=workflow['tasks'][tid][arm];totals={k:audit['before_counts'][k]+audit['after_counts'][k] for k in audit['before_counts']}
   result['tasks'][tid][arm]={'tool_calls':len(calls),'probe_counts':totals,'source_or_environment_union_calls':len({x['call_id'] for x in audit['classified_calls'] if any(k in x['categories'] for k in ('solver_source_content','solver_source_discovery','environment_probe'))})}
   if arm=='bare':continue
   docs=[];queries=[]
   for n,c in enumerate(calls,1):
    text=commands(c)
    if re.search(r'software-capabilities(?:[/.]|\b)',text) and (c['tool']=='read' or re.search(r'\b(?:cat|sed|head|grep)\b',text)):docs.append(n)
    if re.search(r'software_capabilities\.py[\"\']?\s+(?:show|summary)\b',text):
     queries.append({'event':n,'action':c['args'].get('description'),'unrecorded_error':'能力项未收录' in str(c['output']),'tool_error':c['tool_error']})
   marks=[]
   for n,category,expected,reason in MARKS[tid]:
    c=calls[n-1];name=c['args'].get('description',c['tool'])
    assert name==expected,(tid,n,name,expected)
    marks.append({'event':n,'step':c['step'],'category':category,'label':LABELS[category],'reason':reason,'action':name,'call_id':c['id'],'raw_call_line':c['call_line'],'raw_result_line':c['result_line'],'raw_trace':str(trace.relative_to(root))})
   result['tasks'][tid][arm].update(capability_document_events=docs,query_events=queries,review_marks=marks,review_counts=dict(Counter(x['category'] for x in marks)))
 # 审查真实准备记录，不只按脚本出现check_case字样判断已调用。
 receipts=[]
 paths=[root/'C08/skill/workspace/prepare-record.json',root/'C05/skill/workspace/prep-check.txt',*sorted((root/'F02/skill/workspace').glob('*/cases/*/prepare.json'))]
 for p in paths:
  d=load(p);check=d.get('capability_check',d)
  if 'stdout' in check:check=json.loads(check['stdout'])
  receipts.append({'file':str(p.relative_to(root)),'status':check['status'],'errors':check['errors'],'warnings':check['warnings'],'native_entry_reads':check['native_entry_reads'],'scope':check['scope']})
 result['capability_check_receipts']=receipts
 # C08首个实际启动的输入就是关键证据；不以模型陈述判定。
 event=verified['tasks']['C08']['skill']['executions'][0];before=Path(event['evidence_dir'])/'before/constant/solverDict';s=evaluator.foam.read_foam(before);original=evaluator.foam.read_foam(root/'C08/source-case/constant/solverDict')
 result['C08_first_actual_input']={'mechanicsSolver':s['mechanicsSolver'],'gapGas':s['gapGas'],'heatSource':s['heatSource'],'load_time_points':s['heatSourceOptions']['timePoints'],'source_load_preserved':evaluator.foam.equivalent(s['heatSourceOptions'],original['heatSourceOptions']),'native_exit_code':event['exit_code'],'normal':event['normal']}
 result['C05_extraction_code_observation']={'file':'C05/skill/workspace/extract_results.py','basis':'实际交付脚本的循环结构，非额外底层运行跟踪','historical_read_field_invocations_per_full_run':9,'historical_time_frames_per_all_call':21,'final_tensor_read_field_invocations_per_full_run':30,'final_scalar_read_field_invocations_per_full_run':7,'duplicate_same_epsilonCreep_xx_all_history':True,'scope':'5种终态张量各按6个分量单独读；一个脚本工具动作仍会重复加载场和网格元数据。不把静态调用数当工具事件数。'}
 aggregate={}
 for arm in ('bare','skill'):
  stats=[comparison['tasks'][tid][arm] for tid in result['tasks']]
  aggregate[arm]={k:sum(v[k] for v in stats) for k in ('wall_seconds','tool_calls','steps','actual_solver_starts')}
  aggregate[arm]['totalTokens']=sum(v['tokens']['totalTokens'] for v in stats)
  aggregate[arm]['source_content_attempts']=sum(result['tasks'][tid][arm]['probe_counts']['solver_source_content'] for tid in result['tasks'])
  aggregate[arm]['source_discovery_attempts']=sum(result['tasks'][tid][arm]['probe_counts']['solver_source_discovery'] for tid in result['tasks'])
  aggregate[arm]['environment_probe_attempts']=sum(result['tasks'][tid][arm]['probe_counts']['environment_probe'] for tid in result['tasks'])
 aggregate['skill_reduction_percent']={k:100*(1-aggregate['skill'][k]/aggregate['bare'][k]) for k in ('wall_seconds','tool_calls','steps','totalTokens')}
 aggregate['wall_scope']='三题会话时长之和，不是六会话并发实验的总墙钟。'
 result['aggregate']=aggregate
 result['skill_review_totals']=dict(sum((Counter(x['skill']['review_counts']) for x in result['tasks'].values()),Counter()))
 save(root/'capability-effect-audit.json',result)
 print(json.dumps({'aggregate':aggregate,'review_totals':result['skill_review_totals'],'receipts':len(receipts)},ensure_ascii=False))

if __name__=='__main__':main()
