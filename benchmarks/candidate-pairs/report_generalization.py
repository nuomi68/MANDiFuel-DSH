#!/usr/bin/env python3
"""为任意成对新任务生成基于执行证据的中文报告。"""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('paired_analysis',HERE/'analyze_suite.py');analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


def load(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
 manifest=load(root/'manifest.json');v=load(root/'verification.json');exposure=load(root/'exposure-audit.json');workflow=load(root/'workflow-audit.json')['current'];integrity=load(root/'integrity.json')
 result={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'model':manifest['model'],'tasks':{},'integrity':v['integrity']}
 lines=['# 当前 Skill 与裸 DSH：配对任务对照','',f'报告时间：{result["created_at_beijing"]}。','',
 '任务：'+', '.join(t['id']+' '+t['title'] for t in manifest['tasks'])+'。各一个配对，共'+str(len(manifest['tasks'])*2)+'个独立会话。本轮冻结产品，不附带旧轨迹或答案。两组采用相同有效题面、源输入、模型、启动计数政策和离线限制；裸组无技能及运行助手身份。用户撤销旧题库启动次数上限时，原题面、有效题面和变更记录分别保留。','',
 '| 任务 | 裸组状态 | Skill 状态 | 秒：裸 / Skill | 工具：裸 / Skill | 真实启动：裸 / Skill |',
 '|---|---|---|---:|---:|---:|']
 for task in manifest['tasks']:
  tid=task['id'];result['tasks'][tid]={};summary=load(root/tid/'trace-summary.json')
  for arm in ('bare','skill'):
   actual=v['tasks'][tid][arm];stats=analysis.arm_report(root,task,arm,actual,summary['arms'][arm],exposure['arms'][tid+'/'+arm])
   w=workflow['tasks'][tid][arm]
   stats['workflow_probe_counts']={key:sum(w[stage][key] for stage in ('before_counts','after_counts')) for key in w['before_counts']}
   result['tasks'][tid][arm]=stats
  a=result['tasks'][tid]['bare'];b=result['tasks'][tid]['skill'];same=a['status']==b['status']=='completed'
  result['tasks'][tid]['cost_comparable']=same
  if same:
   result['tasks'][tid]['skill_reduction_percent']={key:100*(1-b[key]/a[key]) for key in ('wall_seconds','tool_calls','steps')}
   result['tasks'][tid]['skill_reduction_percent']['totalTokens']=100*(1-b['tokens']['totalTokens']/a['tokens']['totalTokens'])
  lines.append(f'| {tid} | {analysis.label(a["status"])} | {analysis.label(b["status"])} | {a["wall_seconds"]:.1f} / {b["wall_seconds"]:.1f} | {a["tool_calls"]} / {b["tool_calls"]} | {a["actual_solver_starts"]} / {b["actual_solver_starts"]} |')
 lines+=['','任务完成度由输入、原生执行日志/退出码、实际场和交付覆盖核对；模型或DSH进程退出0不等于任务完成。以下是操作与结果覆盖检查，附加数值一致性复核另列；未做解析参考解精度认证。','']
 for task in manifest['tasks']:
  tid=task['id'];pair=result['tasks'][tid];lines += [f'## {tid}：{task["title"]}','']
  if pair['cost_comparable']:
   r=pair['skill_reduction_percent'];lines += [f'两组完成范围相同。Skill 本轮耗时减少 {r["wall_seconds"]:.1f}%，工具调用减少 {r["tool_calls"]:.1f}%，totalTokens 减少 {r["totalTokens"]:.1f}%；负值表示增加。','']
  else:lines += ['两组存在未完成项或完成范围差异，只列成本，不按较早退出判断胜出。','']
  lines+=['| 组别 | 模型轮次 | 非缓存输入 token | 缓存读取 token | 输出 token | 总 token | 工具失败 |','|---|---:|---:|---:|---:|---:|---:|']
  details=[]
  for arm in ('bare','skill'):
   s=pair[arm];t=s['tokens'];label='裸DSH' if arm=='bare' else 'Skill'
   lines.append(f'| {label} | {s["steps"]} | {t.get("inputTokens",0)} | {t.get("cacheReadTokens",0)} | {t.get("outputTokens",0)} | {t.get("totalTokens",0)} | {s["tool_failures"]} |')
   actual=v['tasks'][tid][arm];failed=[c['check'] for c in actual['checks'] if not c['passed']]
   details += [f'{label}：未通过项 {", ".join(failed) if failed else "无"}；核对异常 {actual.get("evaluation_error") or "无"}。']
   probes=s['workflow_probe_counts'];details += [f'{label}：求解器源码查看尝试 {probes["solver_source_content"]}，源码目录发现 {probes["solver_source_discovery"]}，环境探测 {probes["environment_probe"]}，网页调用 {sum(s["tools_by_name"].get(k,0) for k in ("web_search","web_fetch"))}。']
  lines += ['',*details]
  lines+=['',f'[裸组单行轨迹](中文单行轨迹/{tid}_裸DSH_一行轨迹.md)｜[Skill 单行轨迹](中文单行轨迹/{tid}_Skill_一行轨迹.md)','']
 lines += ['## 可比性与保存','',
 f'证据完整性通过：{integrity["passed"]}，共 {len(integrity["checks"])} 项。保留题面、源和产品快照、启动前后输入及状态、实际结果场、退出码、原始轨迹及中文可观察动作。', '',
 '每题只做一次配对，各会话共享 CPU 和模型 API；耗时含准备、模型生成、工具、求解和交付，不据此估计稳定加速比。总 token 包括缓存读取，输出包含推理计数，不重复加 reasoningTokens，也未按未核实价格折算费用。任务工具禁网，宿主模型 API 正常工作。', '',
 '中文轨迹一行一次工具事件，只包含可观察动作与返回，不导出内部推理正文。首次出现的模型选择、重复探索、修改与失败恢复可沿轨迹查看。', '',
 '[全部中文单行轨迹](中文单行轨迹/总索引.md)｜[独立核对](verification.json)｜[成本与流程数据](comparison.json)｜[完整性](integrity.json)｜[实验设计](experiment-design.json)','']
 save(root/'comparison.json',result);(root/'结果汇总.md').write_text('\n'.join(lines))
 evaluation=root/'evaluation';evaluation.mkdir(exist_ok=True)
 names=['capability_task_checks.py','prompt_policy.py','evaluate_suite.py','new_case_checks.py','generalization_checks.py','audit_exposure.py','audit_workflow.py','finalize_evidence.py','analyze_suite.py','report_generalization.py','translate_traces_zh.py','compact_traces_zh.py','render_compact_traces_zh.py']
 for name in names:shutil.copy2(HERE/name,evaluation/name)
 shutil.copy2(HERE.parent/'fuel-rod-power-ab/verify_results.py',evaluation/'reference_reader.py')
 save(evaluation/'manifest.json',{'scope':'独立只读核对，未追加求解','files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in evaluation.iterdir() if p.is_file()}})
 print(json.dumps({tid:{arm:{k:value[k] for k in ('status','wall_seconds','tool_calls','actual_solver_starts')} for arm,value in pair.items() if arm in ('bare','skill')} for tid,pair in result['tasks'].items()},ensure_ascii=False))

if __name__=='__main__':main()
