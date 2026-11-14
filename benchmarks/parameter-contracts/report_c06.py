#!/usr/bin/env python3
"""从保留证据生成中文参数计划对照报告；不启动模型或求解器。"""
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import csv
import hashlib
import json
import math

REPO = Path(__file__).resolve().parents[2]
RUNS = [
    ('已有裸 DSH', 'c06-bare-retest-20261114-01', 'bare'),
    ('已有 Skill', 'run-assistant-newcases-20261113-01', 'skill'),
    ('固化入口首次联调', 'parameter-plan-c06-20261114-01', 'skill'),
    ('固化入口修复后', 'parameter-plan-c06-20261114-02', 'skill')]


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


records = []
for name, directory, arm in RUNS:
    root = REPO / 'runs' / directory
    manifest = read(root / 'manifest.json')
    trace = read(root / 'C06/trace-summary.json')['arms'][arm]
    verified = read(root / 'verification.json')['tasks']['C06'][arm]
    workflow = read(root / 'workflow-audit.json')['current']['tasks']['C06'][arm]
    run = read(root / f'C06/{arm}/run.json')
    sources = read(root / 'C06/source-manifest.json')['actor_source_hashes']
    item = {'name': name, 'directory': directory, 'arm': arm,
            'seconds': run['wall_seconds'], 'tools': trace['tool_calls'],
            'steps': trace['steps_completed'], 'tokens': trace['tokens'],
            'starts': verified['solver_starts'], 'status': verified['status'],
            'D': verified['effective_diffusivities'],
            'solver_source_attempts': sum(workflow[stage]['solver_source_content'] for stage in ('before_counts', 'after_counts')),
            'web_calls': sum(trace['tools_by_name'].get(tool, 0) for tool in ('web_fetch', 'web_search')),
            'tool_failures': trace['tool_failures'],
            'identity': {'prompt': hashlib.sha256((root/'C06/task.txt').read_bytes()).hexdigest(),
                         'source': sources, 'model': manifest['model'],
                         'solver_start_cap': next(t for t in manifest['tasks'] if t['id']=='C06')['solver_start_cap']}}
    records.append(item)
assert all(r['identity'] == records[0]['identity'] for r in records)
output = REPO / 'runs/parameter-plan-c06-20261114-02'
first = REPO / 'runs/parameter-plan-c06-20261114-01'
case = output / 'C06/skill/workspace/case'
receipt = read(case/'.mandifuel-preparation.json')
check = read(case/'.mandifuel-verification.json')
inventory = read(case/'results/cs_inventory.json')
with (case/'results/cs_radial_profile.csv').open() as stream:
    profile = list(csv.DictReader(stream))
volume = math.fsum(float(r['volume_m3']) for r in profile)
final = math.fsum(float(r['Cs_mol_m3']) * float(r['volume_m3']) for r in profile)
assert len(profile) == 50
assert math.isclose(volume, inventory['volume_m3'], rel_tol=1e-14)
assert math.isclose(final, inventory['final_inventory_mol'], rel_tol=1e-14)
assert check['status'] == 'verified' and all(f['passed'] for f in check['fields'])
assert check['checked_times'] and all(float(t)>0 for t in check['checked_times'])
assert len(check['fields']) == 3*len(check['checked_times']) and float(check['checked_times'][-1]) == 50000
for key, hash_value in receipt['input_hashes'].items():
    assert hashlib.sha256((case/key).read_bytes()).hexdigest() == hash_value
current, bare, old = records[3], records[0], records[1]
reductions = {r['name']: {key: 100*(1-current[key]/r[key]) for key in ('seconds','tools','steps')}
              | {'totalTokens': 100*(1-current['tokens']['totalTokens']/r['tokens']['totalTokens'])}
              for r in (bare, old)}
bare_fraction = read(REPO/'runs/c06-bare-retest-20261114-01/C06对照核对.json')['bare']['release_fraction']
for root in (first, output):
    assert read(root/'integrity.json')['passed']
    assert read(root/'中文单行轨迹/翻译清单.json')['原始轨迹保持不变']
assert read(output/'integrity.json')['runtime'] == read(REPO/'runs/c06-bare-retest-20261114-01/integrity.json')['runtime']
summary = {'generated_at_beijing': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
           'matching_conditions': True, 'records': records, 'reductions_percent': reductions,
           'inventory': inventory, 'bare_release_fraction': bare_fraction,
           'release_fraction_absolute_difference': abs(inventory['release_fraction']-bare_fraction),
           'checks': {'product_tests': read(REPO/'benchmarks/parameter-contracts/validation.json')['passed'],
                      'independent_completion': len(read(output/'verification.json')['tasks']['C06']['skill']['checks']),
                      'integrity': len(read(output/'integrity.json')['checks']),
                      'saved_positive_times': len(check['checked_times']), 'field_checks': len(check['fields']),
                      'profile_rows': len(profile), 'input_hashes_unchanged': True},
           'note': '跨轮单题比较；token为运行器usage计数，不换算为货币，不把reasoningTokens再加到outputTokens。'}
save(output/'固化操作对照数据.json', summary)
manual = [{'step': c['step'], 'description': c.get('description'),
           'automatic_category': 'plugin_implementation_read',
           'review': '同一 shell 命令调用公共 parameter_plan.py，并用 cat 读取结果/错误文件；没有读取插件实现文件。'}
          for c in read(first/'workflow-audit.json')['current']['tasks']['C06']['skill']['classified_calls']
          if 'plugin_implementation_read' in c['categories']]
assert len(manual) == 3
save(first/'混合命令分类复核.json', {'automatic_hits_preserved': 3, 'reviewed_implementation_reads': 0, 'items': manual})
lines = ['# C06 固化操作对比', '', f'生成时间：{summary["generated_at_beijing"]}。全部开发在 MANDiFuel-DSH-lwz。', '',
         '本题结果支持继续固化可重复操作：原 Skill 没能正确绑定 D，修复后的参数计划正确完成，同时显著减少模型往返和用量。此结论限于本次 C06 单题跨轮观察。', '',
         '| 组别 | 正确完成 | 秒 | 工具调用 | 模型轮次 | OFFBEAT 启动 | 实际 D / m²·s⁻¹ |',
         '|---|---|---:|---:|---:|---:|---:|']
for r in records:
    ds = r['D'][0]['min']
    lines.append(f'| {r["name"]} | {"是" if r["status"]=="completed" else "否，D 未绑定"} | {r["seconds"]:.3f} | {r["tools"]} | {r["steps"]} | {r["starts"]} | {ds:.8g} |')
lines += ['', f'修复后相对已有裸组：耗时减少 {reductions[bare["name"]]["seconds"]:.1f}%，工具调用减少 {reductions[bare["name"]]["tools"]:.1f}%；相对旧 Skill：耗时减少 {reductions[old["name"]]["seconds"]:.1f}%，工具调用减少 {reductions[old["name"]]["tools"]:.1f}%，并从未正确完成变为正确完成。', '',
          '## 固化了什么', '',
          'Skill 对已覆盖组合强制使用公开参数计划入口。模型只需按题目填写计划、选择相关输入与配方；工具执行固定步骤：单材料/模型门槛 → 独立复制 → 参数所有者绑定及跨文件批量编辑 → 原生回读 → 公共执行器 → 实际正时间场核对 → 适用的径向表和库存提取。', '',
          'Cs 常 D 的真实所有者是 `materials/<zone>/fissionProductsTransport/Cs`，绑定 `d1=D, q1=d2=q2=0` 并确认 `fissionProductsName (Cs)`。不能靠写 0/diffCs 或位移场 0/D 代替。工具仅覆盖已验证的单 UO2、byZone/byList、单 FpDiffusion、单 Cs；未覆盖项报告缺口，其他任务继续一般工作流。', '',
          '相同计划、源和未变输入复用准备记录，省去再次改写和回读；执行凭据保证重复调用不额外启动求解。准备状态只证明输入，物理生效另由实际场检查证明。脚本内部仍执行必要的原生读取和核对，减少的是模型探索、往返及错误求解。', '',
          '## 实际结果与核对', '',
          f'真实 OFFBEAT 正常完成 50000 s、500 步，实际步长 100 s；{len(check["checked_times"])} 个保留正时间的 diffCs、T、sourceCs 共 {len(check["fields"])} 项检查通过，分别为 1e-13 m²/s、1873.15 K、0 mol/(m³·s)。独立完成度 {summary["checks"]["independent_completion"]} 项和完整性 {summary["checks"]["integrity"]} 项通过。输入哈希与执行后输入一致。', '',
          f'初始库存 {inventory["initial_inventory_mol"]:.15g} mol，终态库存 {inventory["final_inventory_mol"]:.15g} mol，外释分数 {inventory["release_fraction"]:.15g}（约 {inventory["release_fraction"]*100:.8f}%）。库存按实际楔形计算域积分；径向表 50 行，CSV 再积分与 JSON 一致。与已完成裸组外释分数的绝对差为 {summary["release_fraction_absolute_difference"]:.4g}，这里只做运行及数据一致性核对。', '',
          '## 模型用量', '',
          '| 组别 | 非缓存输入 token | 缓存读取 token | 输出 token | totalTokens |',
          '|---|---:|---:|---:|---:|']
for r in records:
    t = r['tokens'];lines.append(f'| {r["name"]} | {t["inputTokens"]} | {t["cacheReadTokens"]} | {t["outputTokens"]} | {t["totalTokens"]} |')
lines += ['', f'修复后 totalTokens 相对旧 Skill 减少 {reductions[old["name"]]["totalTokens"]:.1f}%，相对裸组减少 {reductions[bare["name"]]["totalTokens"]:.1f}%。包含运行器计入的缓存读取；没有按未核实价格折算费用。输出已包含推理用量，未重复相加。工程开发与回归测试成本另计，不能把表中单次运行数据当作本轮开发总成本。', '',
          '## 首次联调和剩余冗余', '',
          '首次联调的实际求解已正确完成；提取入口未将相对 case 路径转为绝对路径，导致两次工具失败和多次诊断调用。模型最终改用绝对路径完成，执行凭据始终将真实启动保持为 1。已修复入口，并补上相对路径完整运行及终态复用回归测试；共 23 项测试通过，测试没有额外启动 OFFBEAT。首轮数据和 36 行轨迹全部保留。', '',
          '首轮自动分类的 3 次插件实现查看命中来自混合 shell 命令，公共 CLI 调用与 cat 结果文件出现在同一命令。自动记录原样保留，具体目标经人工复核并保存到首轮《混合命令分类复核.json》。修复后全程环境探测、求解器源码查看、插件实现查看和网页调用均为 0。', '',
          '修复后仍有可压缩环节：开场列目录/读取隔离记录/列技能目录；核对已有验证 JSON 后再看日志和终态场；交付脚本先写再改半径文字；末尾又回读已确认输入。它们可在后续用统一交付摘要继续收拢。首次联调还额外做了题面未要求的解析核对。当前改善主要来自真实绑定和批量公共入口。', '',
          '## 可比范围与文件', '',
          '四组原题面、冻结源输入、模型、两次启动上限相同；修复后与裸组的 DSH、Node、求解器二进制身份也一致。新会话不附带旧轨迹或答案；任务工具保持离线，宿主模型 API 正常访问。裸组与 Skill 的角色/可用技能差异是原有组别设置。各会话按题目自主选择写出频率：修复后保留 5 个正时间、首次联调保留 25 个、裸组保留 50 个；都到达相同终点且使用 500 个时间步，题面没有要求中间写出频率。耗时包含相应 I/O 与检查成本。时间和用量是不同轮次的单次观测，后续应在其他 D 值、温度和新题上重复验证迁移与稳定性。内置库存流程本次验证范围为秒制、从零开始、均匀初态、原点为球心、无持续生成；其他情况使用通用 Extract。', '',
          '[本次中文单行轨迹](中文单行轨迹/C06_Skill_一行轨迹.md)｜[首次联调轨迹](../parameter-plan-c06-20261114-01/中文单行轨迹/C06_Skill_一行轨迹.md)｜[机器可读对照](固化操作对照数据.json)｜[独立检查](verification.json)｜[完整性](integrity.json)', '',
          '[公共入口说明](../../skills/prepare-offbeat-case/references/parameter-plan.md)｜[回归测试](../../benchmarks/direct-execution/check_parameter_plan.py)｜[23 项验证记录](../../benchmarks/parameter-contracts/validation.json)', '']
(output/'固化操作对比.md').write_text('\n'.join(lines))
print(json.dumps({'report': str(output/'固化操作对比.md'), 'reductions_percent': reductions, 'verified': True}, ensure_ascii=False))
