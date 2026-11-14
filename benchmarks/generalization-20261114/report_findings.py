#!/usr/bin/env python3
"""汇总配对结果、数值复核和失败原因；不运行模型或求解器。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[2]

def read(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')


def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
 comp=read(root/'comparison.json');verified=read(root/'verification.json');numeric=read(root/'数值独立复核/复核数据.json')['tasks'];delivery=read(root/'数值独立复核/交付一致性.json')
 cases={}
 for tid,arms in verified['tasks'].items():
  cases[tid]={}
  for arm,a in arms.items():
   cases[tid][arm]={'status':a['status'],'failures':[{'id':e['id'],'exit_code':e['exit_code'],'case_root':e['case_root'],'error':e['error']} for e in a['executions'] if not e['normal']]}
 fail_count=sum(len(a['failures']) for t in cases.values() for a in t.values())
 assert fail_count==7
 maxima={name:{a:case['fuel_T_max_K'] for a,items in numeric['F01'].items() for key,case in items.items() if key==name} for name in ('0.50mm','0.75mm','1.00mm')}
 assert all(x['bare']==x['skill'] for x in maxima.values())
 c02same=all(numeric['C02']['bare']['case'][k]==numeric['C02']['skill']['case'][k] for k in ('u_r_m','sigma_rr_Pa','sigma_tt_mean_Pa'))
 assert c02same and delivery['passed']
 energy=numeric['C08']['bare']['case']['history'][-1]
 with (root/'C08/bare/workspace/pure-thermal/results/temperatures_energies.csv').open() as f:energy_table=list(csv.DictReader(f))[-1]
 findings={'scope':'保留真实失败；不补算、不改产品或任务产物；自动列名误报复核单列',
           'completed_tasks':{'bare':3,'skill':2},'failures':cases,'failed_solver_starts':fail_count,
           'C02_internal_field_stats_identical':c02same,'F01_fuel_Tmax_K':maxima,
           'C08_bare_final_energy':energy,'C08_bare_energy_table_last':energy_table,
           'native_snapshot_field_checks':delivery['native_field_checks'],'energy_table_checks':delivery['energy_comparisons'],
           'tested_plugin_manifest_sha256':'589feb564aab994959ac12294a3c8aeca34771b9d7f9cc0c60061f5b41e8fdf2'}
 save(root/'对照结论与故障.json',findings)
 lines=['# 新任务迁移结果与问题分析','',
 '本轮是当前冻结 Skill 的迁移试验。裸组完成 3/3，Skill 完成 2/3；两个成功配对中 Skill 耗时与模型用量均更低。C08 表明通用输入契约仍有缺口，不能据 C06 的收益宣称当前版本已全面超过裸组。','',
 '| 任务 | 裸DSH：秒 / 工具 | Skill：秒 / 工具 | 完成范围 |', '|---|---:|---:|---|']
 for tid in ('C02','C08','F01'):
  a=comp['tasks'][tid]['bare'];b=comp['tasks'][tid]['skill']
  lines.append(f'| {tid} | {a["wall_seconds"]:.3f} / {a["tool_calls"]} | {b["wall_seconds"]:.3f} / {b["tool_calls"]} | '+('两组完成' if tid!='C08' else '裸组完成；Skill 两次初始化失败')+' |')
 lines += ['','## 已迁移的收益','']
 for tid in ('C02','F01'):
  d=comp['tasks'][tid]['skill_reduction_percent'];lines.append(f'- {tid}：Skill 耗时减少 {d["wall_seconds"]:.1f}%，工具减少 {d["tool_calls"]:.1f}%，totalTokens 减少 {d["totalTokens"]:.1f}%。')
 lines += ['', '三题 Skill 全程求解器源码和插件实现查看尝试均为 0；裸组全程求解器源码查看尝试为 C02 22 次、C08 18 次、F01 22 次。两组网页调用均为 0。Skill 仍有 1、1、2 次环境探测；这些计数基于工具参数，不是操作系统文件读取次数。', '',
 '裸组 C02 额外进行了多轮解析核对、表面外推和报告修订，增加了交付阶段用量。因此这里比较实际端到端行为，不能把所有耗时差归结为工具实现性能。F01 Skill 使用固定点 Study，但仍先单点诊断、修复后再运行剩余两点，且准备脚本、回读、报告有多次修订，收益小于 C02。', '',
 '## 数值结果', '',
 'C02 两组原生 D、sigma 的单元中心统计完全一致。用临时副本的原生 C/V 作独立计算，球坐标径向位移、径向/切向应力也一致；最大归一化误差诊断约为位移 0.0217%、径向应力 0.0762%、切向应力 0.0058%（相对球壳 Lamé 单元中心参考最大幅值）。此诊断不作为额外参考解合格线。', '',
 'C02 表面响应必须保留取值口径：Skill 明确交付 calculated 边界原值；裸组同时交付原值和额外的牵引一致修正/二次外推值。内表面原生环向应力两组均为 −185.016 MPa，裸组修正/外推约 −187.9 MPa；不能混用这两种口径判定两组求解不同。', '',
 '| F01 孔径 | 裸组燃料最大单元温度 / K | Skill / K |','|---|---:|---:|']
 for name,x in maxima.items():lines.append(f'| {name} | {x["bare"]:.3f} | {x["skill"]:.3f} |')
 lines += ['', 'F01 原生 k 场的燃料区均为 3 W/(m·K)，三个实际网格孔径、体积和温度已独立检查；两组均说明孔壁 zeroGradient 面值与首层单元值的关系及采样位置。', '',
 f'C08 裸组保留全部 10 个正时间，原生场独立积分的终态燃料热能增量 {energy["regions"]["fuel"]["delta_energy_J"]:.9f} J，包壳 {energy["regions"]["cladding"]["delta_energy_J"]:.9f} J，合计 {energy["delta_total_energy_J"]:.9f} J。10 帧 × 3 个能量量共 30 项与交付表逐项一致；原生离散耦合的能量残差按报告保留，没有强行归零。', '',
 '9 次正常求解的 11 个关键场文件与各次 OFFBEAT 退出后的独立快照哈希一致。几何复核的 postProcess 只在临时副本运行，不改任务产物，也未额外启动 OFFBEAT。', '',
 '## C08 为什么失败', '',
 '1. Skill 第一次将 `mechanicsSolver` 写为 `none`。本机注册列表没有该值，初始化即失败；日志列出的关闭/固定状态对应可用 `constant`，源中已有 `fromLatestTime` 也提供兼容约定。',
 '2. 第二次修正力学选择器，但仍保留 `gapGas none`；温度边界继续使用 `fuelRodGap`，它要调用间隙气体导热率，因缺少气体模型而再次失败。关闭力学不等于移除热边界依赖的气体模型。',
 '3. 两次真实启动预算用完，没有任何正常瞬态结果。Skill 保留失败输入、凭据、零时刻基准和一个保留气体模型的待运行版本；该版本没有再次实跑，不能计为完成。', '',
 '裸组保留 FRAPCON 气体模型，首次因截断后的载荷表末点越界失败，第二次延长表尾后正常完成。裸组通过大量源码探索获得信息；Skill 需要把这部分已确认知识压缩为输入契约，避免靠增加探索恢复。', '',
 '## 下一步适合固化的操作', '',
 '- **物理开关与依赖**：固定支持的关闭力学写法，按温度边界识别 fuelRodGap → 有效气体模型的依赖；只读相应选择器和边界块即可检查。',
 '- **载荷时间覆盖**：保留源中已有的较晚末点；遇到本机时变线功率表末点正好等于终点的结构，按已确认约定补充区间外尾点，保持请求区间内载荷不变。C02 两组和 C08 裸组均因此消耗一次启动。',
 '- **旧采样配置兼容**：F01 两组各损失一次初始化，裸组为不支持的 lineUniform，Skill 为 patchProbes 的旧 patchName 写法。把受支持采样语法或已有场提取入口固化，避免无关采样阻断物理求解。',
 '- **准备和交付复用**：通用入口集中完成上述检查与已确定改卡，成功后复用状态和响应，减少环境探测、源码目录搜索、重复回读及报告小修。', '',
 '本轮严格保留当前产品版本，没有在组间或失败后修改 Skill、修任务输入或替代模型补算。下一步开发应另建版本后对同题和新题重新配对。', '',
 '## 核对与轨迹', '',
 '核对器首次把 Skill 的 `sigma_r_MPa` 列误认为缺少径向应力，因为只匹配 rr；另有单位后缀匹配修正。物理要求未改变，原始自动结果、具体列名、修正代码哈希均已保留；没有修改模型交付。', '',
 '[六份中文单行轨迹](中文单行轨迹/总索引.md)（523 次工具事件）｜[主对照报告](结果汇总.md)｜[数值独立复核](数值独立复核/复核数据.json)｜[字段与表格一致性](数值独立复核/交付一致性.json)｜[列名误报复核](核对器列名复核.json)｜[原始首轮自动核对](verification.first-pass.json)', '']
 (root/'迁移效果与问题分析.md').write_text('\n'.join(lines))
 report=root/'结果汇总.md';s=report.read_text();anchor='| 任务 | 裸组状态 |'
 s=s.replace(anchor,'本轮裸组 **3/3 完成**，Skill **2/3 完成**。C02、F01 的成功配对中 Skill 更省；C08 暴露了关闭力学与间隙导热依赖缺口。详见[迁移效果与问题分析](迁移效果与问题分析.md)。\n\n'+anchor,1)
 s=s.replace('## 可比性与保存','## 数值复核与故障解释\n\nC02 两组实际内场一致；F01 三种孔径的最大单元温度均一致；C08 裸组热能表 30 项与独立场积分一致。11 个关键场与原生退出快照哈希一致。C08 Skill 两次真实初始化失败，不能按较早退出计算有效加速。详见[数值与问题分析](迁移效果与问题分析.md)。\n\n核对器列名匹配修正和原始自动结果均保留；物理完成标准及任务产物未改。\n\n## 可比性与保存',1)
 report.write_text(s)
 print(json.dumps({'completed':findings['completed_tasks'],'failed_solver_starts':fail_count,'numeric_checks':delivery['passed']},ensure_ascii=False))

if __name__=='__main__':main()
