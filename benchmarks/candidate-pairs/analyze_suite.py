#!/usr/bin/env python3
"""Write Chinese reports of observable actions and independently checked results."""
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import re


def load(path): return json.loads(path.read_text())
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def calls(folder):
    result=[]
    for path in (folder/'traces').rglob('session.jsonl'):
        for line in path.open():
            e=json.loads(line)
            if e.get('type')!='tool/call': continue
            d=e.get('data',{}); a=d.get('arguments',{})
            if isinstance(a,str):
                try: a=json.loads(a)
                except ValueError: a={}
            result.append({'time_ms':e.get('time'),'step':d.get('step'),'tool':d.get('name'),'args':a})
    return result


def label(status):
    return {'prepared':'准备完成','completed':'计算及交付完成','partial':'部分完成','incomplete':'未完成','unverified':'需人工核对'}.get(status,status)


def arm_report(root,task,arm,actual,summary,exposure):
    folder=root/task['id']/arm; operations=calls(folder)
    steps=Counter(c['step'] for c in operations)
    edits=Counter(c['args'].get('file_path','') for c in operations if c['tool']=='edit')
    writes=Counter(c['args'].get('file_path','') for c in operations if c['tool']=='write')
    skills=[c['args'].get('name',c['args'].get('skill')) for c in operations if c['tool']=='skill']
    first=min((datetime.fromisoformat(e['started_at_utc']).timestamp() for e in actual['executions']),default=None)
    ended=[datetime.fromisoformat(load(Path(e['evidence_dir'])/'exit.json')['ended_at_utc']).timestamp() for e in actual['executions'] if (Path(e['evidence_dir'])/'exit.json').is_file()]
    last=max(ended,default=None); began=datetime.fromisoformat(actual['run']['started_at_utc']).timestamp(); end=datetime.fromisoformat(actual['run']['ended_at_utc']).timestamp()
    declared=[]
    for path in (folder/'workspace').glob('*.md'):
        for match in re.finditer(r'(?:类别|分类|workflow_class)[：:]\s*`(case|prepare|results|fixed-study|sampling-study|adaptive-study|free)`',path.read_text()):
            declared.append({'class':match.group(1),'file':str(path.relative_to(folder/'workspace'))})
    record={'declared_workflow_records':declared,'expected_workflow_diagnostic':task.get('expected_workflow_diagnostic'),'tool_calls_before_first_solve':sum(c.get('time_ms',0)/1000<first for c in operations) if first else None,'status':actual['status'],'wall_seconds':actual['run']['wall_seconds'],'steps':summary['steps_started'],'tool_calls':summary['tool_calls'],'tool_failures':summary['tool_failures'],'actual_solver_starts':actual['solver_starts'],'blocked_launch_attempts':actual['blocked_launch_attempts'],'normal_solver_exits':sum(e['normal'] for e in actual['executions']),'skill_loads':skills,'tools_by_name':summary['tools_by_name'],'tokens':summary['tokens'],'single_tool_steps':sum(n==1 for n in steps.values()),'multi_tool_steps':sum(n>1 for n in steps.values()),'native_edit_counts':dict(edits),'native_write_counts':dict(writes),'source_unchanged':actual['run'].get('source_unchanged'),'source_model_preserved':actual.get('source_preserving'),'exposure':exposure,'phases_seconds':{'before_first_solve':round(first-began,3) if first else None,'first_to_last_solve_exit_including_gaps':round(last-first,3) if first and last else None,'after_last_solve':round(end-last,3) if last else None}}
    name='裸DSH' if arm=='bare' else 'Skill'
    lines=[f'# {task["id"]} {name}执行过程','',f'交付状态：{label(actual["status"])}；DSH退出码：{actual["run"]["exit_code"]}。',f'墙钟{record["wall_seconds"]:.3f}秒；模型步骤{record["steps"]}；工具{record["tool_calls"]}次；失败{record["tool_failures"]}次。',f'真实OFFBEAT启动{record["actual_solver_starts"]}次，上限{task["solver_start_cap"] if task["solver_start_cap"] is not None else '未设次数上限'}；正常退出{record["normal_solver_exits"]}次。','',f'加载技能：{", ".join(skills) if skills else "无"}。',f'同一模型步骤调用多个工具：{record["multi_tool_steps"]}轮；单工具：{record["single_tool_steps"]}轮。该数值不等于工具已经并行执行，也不表示所有单工具轮次均可合并。','', '下列过程仅来自工具、文件及真实运行证据，不包含内部推理正文。','', '| 启动 | 算例目录 | 退出码 | 正常终止 | 已保存终态 / 物理秒 |','|---|---|---:|---|---:|']
    for i,e in enumerate(actual['executions'],1):
        try: case=str(Path(e['case_root']).relative_to(folder/'workspace'))
        except ValueError: case=e['case_root']
        lines.append(f'| {i} | {case} | {e["exit_code"]} | {"是" if e["normal"] else "否"} | {e["physical_last_time_s"]} |')
    if not actual['executions']: lines.append('| — | 无真实启动 | — | — | — |')
    failed=[c for c in actual['checks'] if not c['passed']]
    if failed: lines+=['','未通过的独立检查：'+', '.join(c['check'] for c in failed)+'。']
    if actual.get('final_oxide'):
        oxide=actual['final_oxide']; lines+=['',f'真实cladOuter终态厚度：{oxide["mean_m"]:.9g} m = {oxide["mean_um"]:.6f} μm。',f'时间单位{actual["model_time_unit"]}，精确终态目录{actual["final_time_directory"]}；物理秒{actual["final_physical_seconds"]:.6f}。',f'原始正时间厚度场：{len(actual["saved_field_history"])}份。']
    if actual.get('geometry_radii_m'): lines+=['','几何半径（m）：'+json.dumps(actual['geometry_radii_m'],ensure_ascii=False)+'。','材料冷态参数（m）：'+json.dumps(actual.get('cold_dimensions_m'),ensure_ascii=False)+'。']
    if declared: lines+=['','已保存分类记录：'+json.dumps(declared,ensure_ascii=False)+'。题库预期分类仅用于诊断，不作为任务结果合格门槛。']
    if 'source_preserving' in actual:
        lines+=['',f'保持源物理选择器：{actual["source_preserving"]}。','正常分段清单：'+json.dumps(actual['normal_segments'],ensure_ascii=False)+'。']
        if actual['checkpoint_carry']: lines+=['交接文件核对：'+json.dumps(actual['checkpoint_carry'],ensure_ascii=False)+'。']
    repeat={p:n for p,n in edits.items() if n>1}
    lines+=['','原生edit重复次数：'+(json.dumps(repeat,ensure_ascii=False) if repeat else '未观察到同一文件多次edit')+'。这不覆盖bash中的文件写入，不能将原生edit为0当作没有反复修改。','', '完整工具索引见[逐步轨迹](../flow-trace.md)；本组原始会话在 `../'+arm+'/traces/`，启动前后快照和独立日志在 `../'+arm+'/workspace/execution-evidence/`。']
    (root/task['id']/'中文过程').mkdir(exist_ok=True)
    (root/task['id']/'中文过程'/f'{name}执行过程.md').write_text('\n'.join(lines)+'\n')
    return record


def main():
    p=argparse.ArgumentParser(); p.add_argument('run_root',type=Path); args=p.parse_args(); root=args.run_root.resolve()
    manifest=load(root/'manifest.json'); verification=load(root/'verification.json'); exposure=load(root/'exposure-audit.json')
    output={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'model':manifest['model'],'tasks':{},'integrity':verification['integrity'],'exposure':{k:exposure[k] for k in ['all_arm_isolation_preflights_passed','organizer_or_bare_skill_exposure_observed','interpretation']}}
    lines=['# 三题 skill / 裸DSH 隔离对照结果','',f'报告时间：{datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M（北京时间）")}。模型：{manifest["model"]}。','', 'P02为输入准备题，不启动求解器；C04为单算例腐蚀计算；W01为连续与分段续算。三题各一个配对，共6个独立DSH会话。原题面逐字投放，只检查计算交付和真实执行证据，不与参考解比对。','', '| 题目 | 裸DSH / 秒 | Skill / 秒 | 裸组 / Skill工具数 | 实际启动：裸 / Skill | 裸组交付 | Skill交付 |','|---|---:|---:|---:|---:|---|---|']
    for task in manifest['tasks']:
        tid=task['id']; output['tasks'][tid]={}; summary=load(root/tid/'trace-summary.json')
        for arm in ['bare','skill']:
            output['tasks'][tid][arm]=arm_report(root,task,arm,verification['tasks'][tid][arm],summary['arms'][arm],exposure['arms'][tid+'/'+arm])
        a=output['tasks'][tid]['bare']; b=output['tasks'][tid]['skill']; changed=(b['wall_seconds']-a['wall_seconds'])/a['wall_seconds']
        output['tasks'][tid]['observed_wall_fraction_change_skill_vs_bare']=changed
        lines.append(f'| {tid} | {a["wall_seconds"]:.3f} | {b["wall_seconds"]:.3f} | {a["tool_calls"]} / {b["tool_calls"]} | {a["actual_solver_starts"]} / {b["actual_solver_starts"]} | {label(a["status"])} | {label(b["status"])} |')
    lines+=['','## 可观察结果','']
    for task in manifest['tasks']:
        tid=task['id']; a=verification['tasks'][tid]['bare']; b=verification['tasks'][tid]['skill']; r=output['tasks'][tid]
        lines+=[f'### {tid}：{task["title"]}','']
        both=a['status']==b['status'] and a['status'] in ['prepared','completed']
        if both:
            changed=r['observed_wall_fraction_change_skill_vs_bare']; lines += [f'本轮Skill耗时比裸组{"增加" if changed>0 else "减少"}{abs(changed)*100:.1f}%；两组完成状态相同。']
        else: lines += ['两组完成范围不同，耗时仅作执行记录，不据较早结束判断速度胜出。']
        if tid=='P02':
            for arm,actual in [('裸组',a),('Skill',b)]: lines += [f'{arm}：几何半径（m）{json.dumps(actual.get("geometry_radii_m"),ensure_ascii=False)}；冷态参数（m）{json.dumps(actual.get("cold_dimensions_m"),ensure_ascii=False)}。']
            lines+=['独立检查所有对应包壳块、燃料半径、轴向结构及材料冷态参数；零求解器启动。']
        elif tid=='C04':
            for arm,actual in [('裸组',a),('Skill',b)]:
                if actual.get('final_oxide'): lines += [f'{arm}：cladOuter终点厚度{actual["final_oxide"]["mean_m"]:.9g} m = {actual["final_oxide"]["mean_um"]:.6f} μm；模型时间{actual["model_time_unit"]}；精确终态目录{actual["final_time_directory"]}，对应{actual["final_physical_seconds"]:.6f} s；保存{len(actual["saved_field_history"])}个正时间厚度场。']
            lines+=['实际终点依据高精度时间目录和结果场确认。日志或探针的时间字符串可能舍入，不能直接拿舍入末行判定少算。']
            for arm,actual in [('裸组',a),('Skill',b)]:
                normal_events=[e for e in actual['executions'] if e['normal']]
                if len(normal_events)>1:
                    lines += [f'{arm}存在{len(normal_events)}次正常求解，属于正常完成后的额外重算，不能记为失败恢复。各次时间目录精度为：'+json.dumps([e['control'].get('timePrecision') for e in normal_events],ensure_ascii=False)+'。']
            if a.get('final_oxide') and b.get('final_oxide'):
                x=a['final_oxide']['mean_m']; y=b['final_oxide']['mean_m']
                lines += [f'两组原始场相对差为{abs(y-x)/max(abs(x),abs(y)):.6g}；按6位有效数字记录分别为{format(x,".6g")} m和{format(y,".6g")} m。结果场写出精度不同，不能把尾数差直接解释为物理模型差异。']
            for arm in ['bare','skill']:
                phases=r[arm]['phases_seconds']; lines += [f'{"裸组" if arm=="bare" else "Skill"}启动前{phases["before_first_solve"]} s，首次启动至末次退出（含间隔）{phases["first_to_last_solve_exit_including_gaps"]} s，末次退出后{phases["after_last_solve"]} s。']
        else:
            lines += [f'保持源物理选择器：裸组{a.get("source_preserving")}，Skill{b.get("source_preserving")}。']
            if not (a.get('source_preserving') and b.get('source_preserving')): lines+=['存在物理模型选择差异，不能把两组终态温度/位移直接横向比较。']
            for arm,actual in [('裸组',a),('Skill',b)]:
                normal=actual['normal_segments']; lines += [f'{arm}正常段：A连续{len(normal["continuous"])}，B第一段{len(normal["B_first"])}，B续算{len(normal["B_second"])}。']
                for i,e in enumerate(actual['executions'],1):
                    if not e['normal']: lines += [f'{arm}第{i}次启动失败：退出码{e["exit_code"]}；详见独立日志及中文过程。']
                if actual.get('checkpoint_carry'): lines += [f'{arm}交接状态：'+json.dumps(actual['checkpoint_carry'],ensure_ascii=False)+'。']
            for arm in ['bare','skill']:
                declared=r[arm]['declared_workflow_records']
                if declared: lines += [f'{"裸组" if arm=="bare" else "Skill"}显式分类记录为：'+json.dumps(declared,ensure_ascii=False)+'。']
            if any(e['class']=='case' for e in r['skill']['declared_workflow_records']):
                lines += ['Skill组明确把W01归为case，未把分段路径当成固定点研究。当前协议case包含物理续算，fixed-study主要列扫描/候选；题库预期fixed-study与这一定义存在边界不一致，不能据未使用Study直接判定任务失败或漏加载技能。']
            lines+=['源baseCase为续算骨架，多数模块使用fromLatestTime，气体/FGR未启用。保留源开关时，本题仅验证该配置下的分段执行和状态交接，不能据此声称覆盖完整活跃热机/气体演化模型。']
        lines += ['',f'中文过程：[{tid} 裸DSH]({tid}/中文过程/裸DSH执行过程.md)、[{tid} Skill]({tid}/中文过程/Skill执行过程.md)。完整逐步工具索引：[flow-trace]({tid}/flow-trace.md)。','']
    lines += ['## 隔离、验证与适用范围','','第一轮预跑发现裸组可手动读取技能，另有题库元数据暴露，已标记为受污染，不用于本轮收益结论。第二轮在模型启动前因目录遍历权限退出，没有求解器运行。本轮重新建立独立进程环境，整个DSH进程及后代均受内核Landlock文件内容允许清单约束：两组不能读取题库、历史运行、另一组文件或原始带预期值的Allrun；裸组也不能读取插件。目录名查询允许，文件内容读取仍受限。',f'六组隔离预检全部通过：{exposure["all_arm_isolation_preflights_passed"]}；直接引用的返回中观察到题库提示或裸组技能正文：{exposure["organizer_or_bare_skill_exposure_observed"]}。见[文件读取审计](exposure-audit.json)。','', '每组均在模型请求前通过配置解析、启动帮助、网格预处理及求解器帮助检查，预检不进行物理求解。每题两组使用同一题面、源输入和启动预算；失败、诊断和重试均计入真实启动。组织者没有在组外补算或代替模型修输入。','', '三题各做一次配对，六会话共享CPU和API资源。耗时包含模型生成、工具、求解和交付；只描述本轮观察，不能当作稳定速度估计。W01完成范围或模型不同时不计算有效加速比，不做跨题总耗时平均。技能组比较的是当前插件完整配置与裸DSH，未单独隔离协议文字的因果收益。','', '题面、源清单及哈希、插件快照、配置、原始会话、逐次启动前后状态、退出码和结果场均保留。独立检查见[verification.json](verification.json)，交付一致性见[delivery-consistency.json](delivery-consistency.json)，统计见[comparison.json](comparison.json)，复核说明见[README](README.md)。','', '中文过程和工具索引总结可观察动作，不复写模型内部推理正文。']
    save(root/'comparison.json',output); (root/'结果汇总.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({tid:{arm:{k:r[k] for k in ['status','wall_seconds','tool_calls','actual_solver_starts']} for arm,r in pair.items() if arm in ['bare','skill']} for tid,pair in output['tasks'].items()},ensure_ascii=False))


if __name__=='__main__': main()
