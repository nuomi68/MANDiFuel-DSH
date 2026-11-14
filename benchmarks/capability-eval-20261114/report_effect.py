#!/usr/bin/env python3
"""生成中文实验结论，引用可复核动作与实际产物。"""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[2]

def load(p):return json.loads(p.read_text())

def main():
 r=Path(sys.argv[1]).resolve();c=load(r/'comparison.json');a=load(r/'capability-effect-audit.json');v=load(r/'verification.json');n=load(r/'数值独立复核/复核数据.json');integrity=load(r/'integrity.json')
 agg=a['aggregate'];reductions=agg['skill_reduction_percent']
 lines=['# 能力表效果与剩余路径分析','',
 '三题六次独立运行均完成。当前Skill确实被使用，并避免了已知输入错误和大量源码探索；耗时表现分化，三题累计会话时长几乎持平。长提取、重复解析和交付文件逐项修改仍明显存在。','',
 '| 题目 | 裸DSH / 秒 | Skill / 秒 | 工具：裸 / Skill | 实际求解：裸 / Skill | 两组交付 |',
 '|---|---:|---:|---:|---:|---|']
 for tid in ('C08','C05','F02'):
  x=c['tasks'][tid];b=x['bare'];s=x['skill']
  lines.append(f'| {tid} | {b["wall_seconds"]:.3f} | {s["wall_seconds"]:.3f} | {b["tool_calls"]} / {s["tool_calls"]} | {b["actual_solver_starts"]} / {s["actual_solver_starts"]} | 均完成 |')
 lines += ['',f'工具总数339→140，减少{reductions["tool_calls"]:.1f}%；模型轮次318→115；totalTokens 34,390,011→6,794,387，减少{reductions["totalTokens"]:.1f}%。总token包含缓存读取，不按价格折算费用。三题会话时长相加1495.888→1494.209秒，仅减少0.1%；这是任务时长之和，六会话实际并发运行，不能把它解释为串行实验总墙钟。','',
 '## Skill实际发挥的作用','',
 '三题Skill组均读取软件能力资料。C08实际批量查询mechanicsSolver、gapGas、heatSource和时间控制；C05查询具体蠕变模型名未命中后读取材料等分类页面；F02读取能力表入口，使用Study组织两个压力点。该结论来自工具调用，不仅依据“加载了Skill”。','',
 '四份真实准备记录均保存了已知问题检查，返回no_known_errors：C08一份、C05一份、F02每压力点一份。见[准备检查与动作定位](capability-effect-audit.json)。它们证明检查实际运行；本轮没有错误输入触发拦截，不据此宣称所有任务脚本已形成无法绕过的统一硬闸。','',
 'C08第一个真实启动输入为mechanicsSolver constant、gapGas FRAPCON，保留原始heatSourceOptions和(0 604800)载荷末点，一次正常完成。裸组两次实际启动，发生线功率时间表末点修正。该观察符合能力表的预期；完整Skill同时包含运行助手身份、协议和工具，不能将效果单独归因于能力表。','',
 '## 无用路径还剩多少','',
 '整轮可观察源码内容查看尝试：裸组54次，Skill组0次；源码目录发现：8次对0次；环境探测：21次对1次。分类按工具事件和参数匹配，不等于实际文件IO次数，各类别可能重叠，不相加成独立事件总数。全部任务工具网页调用为0。','',
 '对Skill的140条事件另作保守人工复核，以下三类标注彼此不重叠；未标注事件不代表完全没有优化空间：','',
 '| 任务 | 明确绕路/可前置消除 | 可合并候选 | 恢复事件 |',
 '|---|---:|---:|---:|']
 for tid in ('C08','C05','F02'):
  m=a['tasks'][tid]['skill']['review_counts'];lines.append(f'| {tid} | {m.get("avoidable",0)} | {m.get("merge_candidate",0)} | {m.get("recovery",0)} |')
 lines += ['| 合计 | 6 | 23 | 12 |','',
 '明确绕路的6条：C08环境枚举1条；C05插件根检查和不支持的具体模型名查询2条；F02插件资源遍历及额外解析解计算/重试3条。23条合并候选包括目录枚举、跨页搜索、脚本分段读取、同一历史表再次显示，以及报告逐项修改和多次生成。必要数据与正确性检查仍须保留，不能直接把23条视为可以删除。','',
 '12条恢复事件覆盖初次失败、修复及重提取，属于完成任务所需的恢复成本；它们不是12个独立故障，也不主张遇错不修。问题在于其中不少错误可以用稳定接口和准备阶段验证前置消除，格式修改也可以与原始场读取解耦。','',
 '## 当前主要瓶颈','',
 '| 题目 | 首次求解前：裸 / Skill 秒 | 最后求解后：裸 / Skill 秒 |',
 '|---|---:|---:|']
 for tid in ('C08','C05','F02'):
  b=c['tasks'][tid]['bare']['phases_seconds'];s=c['tasks'][tid]['skill']['phases_seconds']
  lines.append(f'| {tid} | {b["before_first_solve"]:.3f} / {s["before_first_solve"]:.3f} | {b["after_last_solve"]:.3f} / {s["after_last_solve"]:.3f} |')
 lines += ['',
 'C08准备阶段从259.7秒降到97.8秒，也少一次实际求解；但最后求解后的提取和交付从286.3秒增加到561.4秒，抵消了前段收益。其提取先前台超时，随后修几何解析、修单位打印、改域换算，都重新运行整段取场。','',
 'C05准备阶段两组约59.5秒；Skill的取场脚本首次前台60秒超时，转后台从头执行。脚本每次完整运行含9次全历史read_field调用，每次21帧；另对5种终态张量各取6个分量，合计30次终态张量读取，再取7个标量。epsilonCreep的xx历史重复读取一次。此处根据交付脚本循环静态核对，未额外跟踪底层文件IO。一次shell动作仍可能重复解析同一场和网格，工具数少并不保证计算工作少。','',
 'F02实际使用Study和准备钩子，两个评价点各一次求解；后续修改报告复用保留的Study数据，没有重跑OFFBEAT。但同一study_definition.py仍多次修改，报告/径向分组多次重新生成，并额外计算了用户未要求的拉梅解，存在继续压缩的空间。','',
 '## 下一轮应优先改的机制','',
 '1. 扩展能力查询的定位方式：按模型值、参数路径和别名返回所属能力及直接依赖，未知键一次返回相关候选；避免具体模型名查询失败后逐页grep。','2. 首次提交长提取就使用原生后台句柄；将实际场读取、响应计算和报告生成分离。原始数据读一次并保存，修单位、格式、章节或域换算时复用，保留失败证据。','3. 提供批量字段/张量分量查询，并复用网格几何；按相同时间、作用域组织请求。不能只把多个重复读取塞进一段shell就认定已完成批处理优化。','4. 将必要验收与交付内容在求解前列齐，同一脚本/多文件联动修改一次、基于缓存数据统一生成；仍依据真实日志修复输入并继续求解，不以次数限制替代恢复。','',
 '本轮没有修改冻结Skill或参与者产物，也没有为补结果在组外求解。上述机制是有轨迹依据的后续改进方向，本轮不宣称已经修复。','',
 '## 核对与可比性','',
 f'主任务输入/执行/交付检查共{sum(len(x["checks"]) for p in v["tasks"].values() for x in p.values())}项，实验完整性{len(integrity["checks"])}项全部通过。独立匹配{sum(x["numeric_values_checked"] for p in n["tasks"].values() for x in p.values()):,}个表格数值，无不一致；数据来源为保留实际场/原生探针，几何后处理仅在临时副本执行，组织者OFFBEAT启动0次。近界面数据按报告声明的材料区局部编号和单元中心解释，不将其当作精确界面面值。未做全模型精度认证。','',
 '核对器的两处格式兼容错误已透明留档：初始历史表规则未接受t_s，初次数值核对误将cell_local_index视为全局ID。分别修正通用列名识别和按材料区映射，未改变判分物理标准或参与者数据；修正前结果保留。见[时间列修正](evaluation-column-correction.json)与[局部编号修正](numeric-index-correction.json)。','',
 '每题仅一次配对，六会话共享CPU/API；完整Skill组与裸DSH对照，不能从该样本估计稳定加速比或拆出单条规则因果作用。源只读、两组同题面和默认不限启动次数、任务工具离线；宿主模型API连接正常。98项完整性检查含产品冻结、隔离、模型路由和调用证据核对；未观察到裸组读取技能或旧答案。','',
 '[全部中文单行轨迹](中文单行轨迹/总索引.md)｜[六次合并轨迹](中文单行轨迹/六次运行_一行事件汇总.md)｜[成本总表](结果汇总.md)｜[数值复核](数值独立复核/复核数据.json)｜[效果与人工标注](capability-effect-audit.json)','',
 '## 剩余路径逐条定位','']
 for tid in ('C08','C05','F02'):
  lines += [f'### {tid} Skill','',f'[完整单行轨迹](中文单行轨迹/{tid}_Skill_一行轨迹.md)','', '| 事件 | 模型轮次 | 分类 | 依据 |','|---:|---:|---|---|']
  for mark in sorted(a['tasks'][tid]['skill']['review_marks'],key=lambda x:x['event']):
   lines.append(f'| {mark["event"]:03} | R{mark["step"]:03} | {mark["label"]} | {mark["reason"]} |')
  lines.append('')
 (r/'能力表效果与剩余路径分析.md').write_text('\n'.join(lines))
 print(r/'能力表效果与剩余路径分析.md')

if __name__=='__main__':main()
