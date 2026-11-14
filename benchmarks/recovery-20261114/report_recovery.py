#!/usr/bin/env python3
"""以保留证据报告无默认次数限制的输入恢复闭环；不启动求解。"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'benchmarks/candidate-pairs'))
import evaluate_suite as api


def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();r=args.root.resolve()
 v=read(r/'verification.json')['tasks']['C08'];comp=read(r/'comparison.json')['tasks']['C08'];numeric=read(r/'数值独立复核/复核数据.json')['tasks']['C08'];manifest=read(r/'manifest.json');integrity=read(r/'integrity.json')
 trace=read(r/'中文单行轨迹/翻译清单.json');checks=[];attempts=[]
 assert manifest['tasks'][0]['solver_start_cap'] is None
 assert all(x['status']=='completed' for x in v.values())
 for arm in ('bare','skill'):
  for event in v[arm]['executions']:
   case=Path(event['case_root']);before=Path(event['evidence_dir'])/'before';s=api.foam.read_foam(before/'constant/solverDict')
   receipt_path=case/'.mandifuel-execution.json';receipt=read(receipt_path) if receipt_path.exists() else None
   attempts.append({'arm':arm,'id':event['id'],'case':str(case.relative_to(r/'C08'/arm/'workspace')),'exit_code':event['exit_code'],'normal':event['normal'],'last_time_s':event['physical_last_time_s'],
                    'mechanicsSolver':s.get('mechanicsSolver'),'gapGas':s.get('gapGas'),'timePoints':s['heatSourceOptions']['timePoints'],'lhgr':s['heatSourceOptions']['lhgr'],
                    'error':event.get('error'),'receipt_status':receipt.get('status') if receipt else None,'diagnostic':receipt.get('diagnostic') if receipt else None})
   if event['normal']:
    terminal=max(api.times(case),key=lambda x:x[0])[1];snapshot=Path(event['evidence_dir'])/'after/latest-state'/terminal.name/'T'
    checks.append({'check':arm+'_native_final_T_unchanged','passed':snapshot.is_file() and sha(snapshot)==sha(terminal/'T')})
 for arm,columns,file in [('bare',('time_s','E_fuel_J','E_clad_J','E_total_J'),'thermal-transient/postprocessing/energy_balance.csv'),('skill',('t_s','dE_fuel_J','dE_clad_J','dE_total_J'),'results/thermal-budget-a4.csv')]:
  table=list(csv.DictReader((r/'C08'/arm/'workspace'/file).open()))
  for frame in numeric[arm]['case']['history']:
   row=next(x for x in table if float(x[columns[0]])==frame['time_s'])
   for col,expected in zip(columns[1:],(frame['regions']['fuel']['delta_energy_J'],frame['regions']['cladding']['delta_energy_J'],frame['delta_total_energy_J'])):
    actual=float(row[col]);checks.append({'check':arm+'_'+str(frame['time_s'])+'_'+col,'passed':math.isclose(actual,expected,rel_tol=2e-6,abs_tol=2e-4),'delivered':actual,'independent':expected})
 skill=[x for x in attempts if x['arm']=='skill']
 checks += [{'check':'four_distinct_skill_attempt_directories','passed':len({x['case'] for x in skill})==4},
            {'check':'three_failures_retained_then_completed','passed':[x['receipt_status'] for x in skill]==['failed','failed','failed','completed']},
            {'check':'three_native_errors_returned_by_public_executor','passed':all(x['diagnostic'] and x['diagnostic']['kind']=='native_solver_error' for x in skill[:3])},
            {'check':'original_source_and_evidence_integrity','passed':integrity['passed']},
            {'check':'all_163_chinese_tool_events','passed':trace['事件总数']==163 and len(trace['文档'])==2},
            {'check':'original_traces_unchanged','passed':all(sha(r/p)==h for p,h in trace['源文件SHA256'].items())}]
 assert all(x['passed'] for x in checks),[x for x in checks if not x['passed']]
 save(r/'恢复闭环核对.json',{'passed':True,'checks':checks,'attempts':attempts,'organizer_OFFBEAT_starts':0,'policy':'默认不限启动次数；全部尝试计数保留'})
 old=read(REPO/'runs/generalization-pairs-20261114-01/comparison.json')['tasks']['C08']['skill']
 bare=comp['bare'];current=comp['skill'];last=numeric['skill']['case']['history'][-1]
 lines=['# 输入修复闭环与不限次数复测','',
 '已把默认策略改为完成计算优先：真实求解启动只记账，不设默认次数上限；有可修复输入错误就保留失败证据、修正并以新尝试继续。用户明确设置的限制、仅准备/仅提取范围仍遵守。', '',
 '| 运行 | 状态 | 秒 | 工具调用 | 真实启动 |', '|---|---|---:|---:|---:|',
 f'| 旧 Skill、旧两次上限 | 未完成 | {old["wall_seconds"]:.3f} | {old["tool_calls"]} | {old["actual_solver_starts"]} |',
 f'| 本轮 Skill、无次数上限 | 完成 | {current["wall_seconds"]:.3f} | {current["tool_calls"]} | {current["actual_solver_starts"]} |',
 f'| 本轮裸 DSH、无次数上限 | 完成 | {bare["wall_seconds"]:.3f} | {bare["tool_calls"]} | {bare["actual_solver_starts"]} |','',
 '旧轮次未完成，不能把其较早结束当作效率优势。本轮 Skill 比裸组耗时增加约 44.6%，工具调用减少约 50.5%，totalTokens 减少约 52.6%；恢复有效，但仍未在本题端到端耗时上超过裸组。', '',
 '## 四次真实运行', '',
 '| 尝试 | 力学选择器 | 气体模型 | 热源时间点 / s | 原生退出码 | 结果 |','|---|---|---|---|---:|---|']
 reasons=['不支持的 none 力学模型，初始化失败','恢复固定力学后，fuelRodGap 缺少气体导热模型','恢复 FRAPCON 后实际算到 10 秒，末点查表越界，仍为失败','将表尾延至 20 秒，请求区间内仍为 18000 W/m，正常完成']
 for i,(x,reason) in enumerate(zip(skill,reasons),1):
  times=' '.join(z for z in x['timePoints'] if z not in ('(',')'))
  lines.append(f'| {i} | {x["mechanicsSolver"][0]} | {x["gapGas"][0]} | {times} | {x["exit_code"]} | {reason} |')
 lines += ['', '四次使用不同目录，前三次失败记录、输入和日志均保留。第三次已有 10 秒状态场，但因退出失败及缺少正常结束证据，执行器保持 failed；第四次正常完成才进入交付。若仍按旧两次上限，这条实际轨迹会在第二次后被截断。', '',
 '## 实现机制', '',
 '- Skill 和运行身份明确要求依据日志修复输入并继续，默认不添加两次、三次等上限。成功工况和结果直接复用；同一错误无实质修正时重新诊断，不原样循环。',
 '- 公共执行器直接返回有界原生错误摘要，包括未知类型及合法类型列表、缺失项和越界信息，省去为常见错误翻阅实现。',
 '- 同一目录保持幂等，修复后用新尝试保存状态。默认无限计数包装器不会阻断第三、第四次启动；显式用户上限和纯准备的零启动约束仍有效。',
 '- 开发规范要求按接口与依赖固化通用能力、明确适用范围，未覆盖组合通过一般流程及运行反馈推进；不按题号分支。', '',
 '本次没有加入 C08 专用修复脚本、合法选择器答案或 FRAPCON/fuelRodGap 专题契约，也没有给会话旧轨迹、答案和失败结论。两组获得同一撤销历史次数上限后的题面，原题面与删除条款分别保存。', '',
 '## 数值与验证', '',
 f'两组均正常完成 10 秒、Euler、1 秒步长，保留全部正时间帧。原生场独立积分的终态燃料热能增量 {last["regions"]["fuel"]["delta_energy_J"]:.9f} J，包壳 {last["regions"]["cladding"]["delta_energy_J"]:.9f} J，合计 {last["delta_total_energy_J"]:.9f} J；两组独立积分一致。两组 60 项逐帧能量交付值与独立积分在输出精度容差内一致，两个正常终态 T 与各自退出快照哈希一致。', '',
 f'独立执行与输入/交付检查全部通过，证据完整性 {len(integrity["checks"])} 项通过。开发检查：恢复机制 42 项、完成判断 15 项、原参数计划回归 23 项，5 项 Skill 格式验证通过；这些开发测试只用假求解器或历史只读场，额外真实 OFFBEAT 启动为 0。', '',
 '组织者核对脚本的原题文本变量曾覆盖源路径变量，已修正并重新执行完整性核对；没有改变任务输入、判定要求或求解结果，没有因此重算。', '',
 '## 仍需改进', '',
 '取消次数上限让输入恢复能够继续，不会自动消除首次参数猜测。本题仍经历三类输入错误；后续适合把已确认的选择器、耦合依赖和时间表规则做成通用检查，同时保留对新错误的运行反馈闭环。', '',
 '本轮提取阶段还遇到公共接口调用及空 defaultFaces 元数据查询问题，最终完成数据提取，但耗时较长。应继续改进公开接口说明、批量读取和准备记录复用；提取修复始终复用第四次结果，没有重新求解。', '',
 '这是新产品策略与错误摘要一起改变的一次配对，不是取消次数限制的单因素实验，也不构成未见任务稳定成功的证明。原来的有上限试验保留，未覆盖。任务工具持续离线，宿主模型 API 正常使用。', '',
 '[Skill 中文单行轨迹](中文单行轨迹/C08_Skill_一行轨迹.md)｜[裸组轨迹](中文单行轨迹/C08_裸DSH_一行轨迹.md)｜[完整对照](结果汇总.md)｜[恢复闭环证据](恢复闭环核对.json)｜[原生场独立复核](数值独立复核/复核数据.json)｜[题面政策变更](C08/prompt-policy.json)', '',
 '[通用恢复规范](../../skills/execute-offbeat-case/references/input-recovery.md)｜[开发原则与工作流](../../STUDY_PROTOCOL.md)', '']
 (r/'恢复机制与复测结果.md').write_text('\n'.join(lines))
 report=r/'结果汇总.md';s=report.read_text();s=s.replace('| 任务 | 裸组状态 |','本轮 Skill 经三次输入修复后第四次求解完成，默认次数上限不再截断恢复。详见[恢复机制与复测结果](恢复机制与复测结果.md)。\n\n| 任务 | 裸组状态 |',1);report.write_text(s)
 print(json.dumps({'passed':True,'recovery_checks':len(checks),'skill_attempts':len(skill),'events':trace['事件总数']},ensure_ascii=False))

if __name__=='__main__':main()
