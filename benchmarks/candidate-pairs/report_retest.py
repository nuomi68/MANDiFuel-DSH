#!/usr/bin/env python3
"""Report a corrected-plugin paired experiment and diagnostic old/new context."""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path


def load(p):return json.loads(p.read_text())
def label(s):return {'prepared':'准备完成','completed':'计算及交付完成','partial':'部分完成','incomplete':'未完成','unverified':'未核实'}.get(s,s)
def ratio(a,b):return (b-a)/a*100

def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);parser.add_argument('--old-run',required=True,type=Path);args=parser.parse_args();root=args.run_root.resolve();oldroot=args.old_run.resolve()
    c=load(root/'comparison.json');v=load(root/'verification.json');old=load(oldroot/'comparison.json');wf=load(root/'workflow-audit.json');integrity=load(root/'integrity.json');design=load(root/'experiment-design.json')
    lines=['# 修正后 Skill 与裸 DSH 对比实验','',f'报告时间：{datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M（北京时间）")}。模型：{c["model"]}。','', '选择与前轮相同的P02、C04、W01，三对共六个独立会话。原题面、源输入、模型、读取隔离和启动预算沿用；只完成准备/计算及交付，不对照参考解。新Skill包含默认环境就绪交接、明确公开接口、受限源码诊断及时间舍入完成判定修复。','', '| 题目 | 裸DSH / 秒 | Skill / 秒 | Skill相对耗时 | 工具数 裸/Skill | 实际启动 裸/Skill | 交付 |','|---|---:|---:|---|---:|---:|---|']
    statuses={}
    for tid,pair in c['tasks'].items():
        a=pair['bare'];b=pair['skill'];av=v['tasks'][tid]['bare'];bv=v['tasks'][tid]['skill']
        comparable=a['status']==b['status'] and a['status'] in ['prepared','completed'] and (tid!='W01' or (av.get('source_preserving') and bv.get('source_preserving')))
        change=ratio(a['wall_seconds'],b['wall_seconds']);word=('慢' if change>0 else '快')+f'{abs(change):.1f}%' if comparable else '范围不同，不判速度胜出'
        outcome=label(a['status']) if a['status']==b['status'] else f'裸组{label(a["status"])}；Skill{label(b["status"])}'
        lines.append(f'| {tid} | {a["wall_seconds"]:.3f} | {b["wall_seconds"]:.3f} | {word} | {a["tool_calls"]}/{b["tool_calls"]} | {a["actual_solver_starts"]}/{b["actual_solver_starts"]} | {outcome} |')
        statuses[tid]={'comparable_completion_scope':comparable,'skill_wall_change_percent':change,'bare_status':a['status'],'skill_status':b['status']}
    lines+=['','## 对修正目标的观察','', '| 题目 | 首次求解前环境探测尝试 旧Skill→新Skill | 求解器源码查看尝试 旧Skill→新Skill | 新Skill其中远程 | 本轮裸组源码尝试 |','|---|---:|---:|---:|---:|']
    for tid in ['P02','C04','W01']:
        now=wf['current']['tasks'][tid]['skill'];prior=wf['old']['tasks'][tid]['skill'];bare=wf['current']['tasks'][tid]['bare']
        remote=sum('solver_source_content' in e['categories'] and e['transport']=='web' and e['before_first_solve_or_prepare_only'] for e in now['classified_calls'])
        lines.append(f'| {tid} | {prior["before_counts"]["environment_probe"]}→{now["before_counts"]["environment_probe"]} | {prior["before_counts"]["solver_source_content"]}→{now["before_counts"]["solver_source_content"]} | {remote} | {bare["before_counts"]["solver_source_content"]} |')
    lines+=['', 'P02为纯准备，以上统计覆盖整个任务；其余两题覆盖第一次真实启动之前。数值是工具参数中可观察的探测/查看尝试，不是文件IO计数，不保证远程下载成功。分类允许重叠；具体命中和URL保存在[workflow-audit.json](workflow-audit.json)。原诊断发现远程源码查看后补充web_fetch识别，旧轮和本轮使用相同规则重算，不把本地读取0当作没有查看源码。','']
    for tid in ['P02','C04','W01']:
        pair=c['tasks'][tid];a=pair['bare'];b=pair['skill'];av=v['tasks'][tid]['bare'];bv=v['tasks'][tid]['skill']
        lines += [f'### {tid}','']
        if tid=='P02':
            lines+=['两组按全部对应几何块、轴向结构、冷态尺寸和源输入完整性核对。',f'裸组状态：{label(a["status"])}；Skill状态：{label(b["status"])}。']
            for arm,actual in [('裸组',av),('Skill',bv)]:lines += [f'{arm}冷态参数（m）：{json.dumps(actual.get("cold_dimensions_m"),ensure_ascii=False)}。']
        elif tid=='C04':
            for arm,actual in [('裸组',av),('Skill',bv)]:
                if actual.get('final_oxide'):
                    field=actual['final_oxide'];lines += [f'{arm}：cladOuter终点厚度{field["mean_m"]:.12g} m = {field["mean_um"]:.9f} μm；目录{actual["final_time_directory"]}，对应{actual["final_physical_seconds"]:.6f}物理秒。']
            lines += [f'Skill实际启动{b["actual_solver_starts"]}次，正常退出{b["normal_solver_exits"]}次；前轮Skill为{old["tasks"][tid]["skill"]["actual_solver_starts"]}次真实启动。是否避免了额外重算依据实际启动和凭据，不按模型自述判断。']
            receipts=list((root/tid/'skill/workspace').rglob('.mandifuel-execution.json'))
            for path in receipts:
                record=load(path)
                if record.get('status')=='completed':lines += ['本轮公共执行器完成凭据：'+json.dumps({k:record.get(k) for k in ['status','end_time','final_time','time_match','exit_code']},ensure_ascii=False)+'。']
        else:
            for arm,actual in [('裸组',av),('Skill',bv)]:
                segments=actual.get('normal_segments',{});lines += [f'{arm}：保留源物理选择器{actual.get("source_preserving")}；正常A/B第一段/B续算数量为{len(segments.get("continuous",[]))}/{len(segments.get("B_first",[]))}/{len(segments.get("B_second",[]))}。']
                if actual.get('checkpoint_carry'):lines += [f'{arm}交接文件：'+json.dumps(actual['checkpoint_carry'],ensure_ascii=False)+'。']
            lines += ['源baseCase为续算骨架，多数模块为fromLatestTime、气体/FGR未开启。本题只能说明该源配置的执行与状态交接，不能据此声称完整活跃燃料演化模型验证。']
        phases=b['phases_seconds']
        if phases['before_first_solve'] is None:
            lines += ['纯输入准备，无求解阶段；耗时为准备、核对与交付的总和。','']
        else:
            lines += [f'Skill耗时分解：首次启动前{phases["before_first_solve"]}秒；首次启动到末次退出（含间隔）{phases["first_to_last_solve_exit_including_gaps"]}秒；末次退出后{phases["after_last_solve"]}秒。','']
    lines += ['## 本轮结论','']
    if all(item['comparable_completion_scope'] for item in statuses.values()):
        descriptions=[]
        for tid in ['P02','C04','W01']:
            change=statuses[tid]['skill_wall_change_percent']
            descriptions.append(tid+('慢' if change>0 else '快')+f'{abs(change):.1f}%')
        lines += ['同等完成范围下，Skill相对裸组：'+'；'.join(descriptions)+'。这是一次配对观察，尚不能证明所有任务或重复运行都有同样收益。','']
    else:lines += ['部分任务完成范围不同，耗时只作记录，不按更早退出判定速度胜出。','']
    prior=wf['old']['tasks']['C04']['skill']['before_counts']['solver_source_content'];current=wf['current']['tasks']['C04']['skill']['before_counts']['solver_source_content']
    lines += [f'C04首次求解前的源码查看尝试为前轮{prior}次、本轮{current}次；实际求解为前轮{old["tasks"]["C04"]["skill"]["actual_solver_starts"]}次、本轮{c["tasks"]["C04"]["skill"]["actual_solver_starts"]}次。实际目录及公共执行器凭据见上文。','']
    remote=sum('solver_source_content' in h['categories'] and h['transport']=='web' and h['before_first_solve_or_prepare_only'] for h in wf['current']['tasks']['W01']['skill']['classified_calls'])
    if remote:lines += [f'W01仍有{remote}次远程C++源码请求，普通任务边界尚未完全落实。','']
    skill_phase=c['tasks']['W01']['skill']['phases_seconds'];bare_phase=c['tasks']['W01']['bare']['phases_seconds']
    lines += [f'W01 Skill首次启动前{skill_phase["before_first_solve"]}秒，裸组{bare_phase["before_first_solve"]}秒；末次退出后{skill_phase["after_last_solve"]}秒，裸组{bare_phase["after_last_solve"]}秒。差距同时涉及前置查询、续算恢复和后处理交付；后续应分阶段复测。下一次可专门检验不依赖实现的续算输入卡配方，以及按已完成阶段复用提取数据。','','## 与旧轮的描述性参照','','| 题目 | 旧Skill / 秒 | 新Skill / 秒 | 旧Skill相对同轮裸组 | 新Skill相对同轮裸组 |','|---|---:|---:|---:|---:|']
    for tid in ['P02','C04','W01']:
        o=old['tasks'][tid];n=c['tasks'][tid]
        lines.append(f'| {tid} | {o["skill"]["wall_seconds"]:.3f} | {n["skill"]["wall_seconds"]:.3f} | {ratio(o["bare"]["wall_seconds"],o["skill"]["wall_seconds"]):+.1f}% | {ratio(n["bare"]["wall_seconds"],n["skill"]["wall_seconds"]):+.1f}% |')
    lines+=['','旧轮与本轮各题都只有一个配对，API排队、模型采样和共享资源有波动；前后绝对时间只能作描述，不能当作严格因果效应。本轮判断优先依据同轮裸组、完成度和实际执行证据。','', '## 保存与有效性','',f'证据完整性检查通过：{integrity["passed"]}。题面、源输入和插件快照及启动配置均已冻结；裸组关闭技能发现且不能读取插件。两组不能读取题库、评分元数据、另一组文件或旧运行内容。命名查询允许，文件内容读取受Landlock限制；公开网页工具两组均可用。','', '本次第一尝试candidate-pairs-20261113-direct-01暴露了新增shellEnv键缺少DSH_前缀的真实适配错误，三个Skill会话在模型前失败。失去配对对象的裸组由组织者停止；该轮无真实求解，完整保留记录且不计作性能结果。修复后通过已安装DSH的真实ShellEnvRegistry及错误前缀负例测试，再冻结本轮版本。','', '本轮六会话共享CPU与API。执行期间没有替受测模型修改输入、提示答案或额外补跑求解；失败和重试都计预算。原始轨迹及逐次输入/状态/日志/退出码保留，工具返回成功不等同物理任务完成。','', '[中文单行轨迹总索引](中文单行轨迹/总索引.md)｜[六次合并轨迹](中文单行轨迹/六次运行_一行事件汇总.md)｜[独立交付核对](verification.json)｜[单位与交接一致性](delivery-consistency.json)｜[文件读取审计](exposure-audit.json)｜[证据完整性](integrity.json)']
    (root/'结果汇总.md').write_text('\n'.join(lines)+'\n')
    (root/'retest-summary.json').write_text(json.dumps({'tasks':statuses,'old_run':str(oldroot),'current_run':str(root),'one_pair_per_task':True,'reference_answer_scoring':False},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(statuses,ensure_ascii=False))


if __name__=='__main__':main()
