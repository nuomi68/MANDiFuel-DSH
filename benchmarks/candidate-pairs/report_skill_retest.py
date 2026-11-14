#!/usr/bin/env python3
"""Compare a skill-only rerun with retained observable evidence, without new solves."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

analysis=module('skill_retest_analysis','analyze_suite.py')
audit=module('skill_retest_audit','audit_workflow.py')

def load(path):return json.loads(path.read_text())
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def change(old,new):return (new-old)/old*100

def read_activity(folder):
    calls=audit.read_calls(folder);counts=Counter();before=0;first_skill=None;read_calls=0
    for i,c in enumerate(calls):
        tool=c['tool'];a=c['arguments'];command=str(a.get('command',''))
        if tool=='skill' and first_skill is None:first_skill=i
        reading=tool=='read' or (tool=='bash' and bool(re.search(r'\bcat\b(?!\s*[<>])|\b(?:sed|head|tail|grep)\b|read_text\(',command)))
        if not reading:continue
        read_calls+=1
        paths=set()
        if tool=='read':paths.add(str(a.get('file_path','')))
        paths.update(re.findall(r'(?:source-case|sources)/[^\s\'\";|<>()]+',command))
        for path in paths:
            # Preserve visible shell paths; this is a call-argument observation,
            # not an assertion about expanded globs or actual filesystem IO.
            path=re.sub(r'^.*?(?=source-case/|sources/)','',path)
            counts[path]+=1
        if first_skill is None:before+=1
    return {'read_like_calls':read_calls,'read_like_calls_before_first_skill':before,
            'calls_before_first_skill':first_skill,'literal_path_mentions':dict(counts),
            'repeated_literal_paths':{p:n for p,n in counts.items() if n>1},
            'scope':'工具参数中可观察的读取类动作与字面路径；不含通配符展开或实际文件IO计数'}


def main():
    p=argparse.ArgumentParser();p.add_argument('run_root',type=Path);p.add_argument('--old-run',required=True,type=Path)
    args=p.parse_args();root=args.run_root.resolve();oldroot=args.old_run.resolve()
    manifest=load(root/'manifest.json');verified=load(root/'verification.json');exposure=load(root/'exposure-audit.json')
    old=load(oldroot/'comparison.json');workflow=load(root/'workflow-audit.json');integrity=load(root/'integrity.json')
    assert manifest['arms']==['skill']
    comparison={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'model':manifest['model'],
        'arms':['skill'],'tasks':{},'integrity':verified['integrity'],'old_run':str(oldroot),
        'comparison_scope':'跨轮描述性比较；旧轮6会话，本轮3会话，不是本轮成对对照，不注入旧轨迹'}
    lines=['# 离线配置 Skill 三题复算','',f'报告时间：{comparison["created_at_beijing"]}。模型：{manifest["model"]}。','',
        'P02、C04、W01 各复算一次 skill 组，三个独立会话同时运行。原题面、源输入、模型、隔离与启动预算沿用。仅完成准备/计算与交付，不给受测模型旧轨迹、参考答案或组织者分析；任务工具保持离线，DSH 宿主模型接口保留。','',
        '旧轮为 candidate-pairs-20261113-direct-02；本轮只运行 skill，未重跑裸组。下表是跨轮描述性结果，旧轮6会话、本轮3会话，不能据单次耗时断言稳定提速或公平战胜当前裸基线。','',
        '| 题目 | 旧Skill / 秒 | 本轮Skill / 秒 | 耗时变化 | 工具数 旧→新 | 真实启动 旧→新 | 本轮独立核对 |',
        '|---|---:|---:|---:|---:|---:|---|']
    result={}
    for task in manifest['tasks']:
        tid=task['id'];actual=verified['tasks'][tid]['skill'];summary=load(root/tid/'trace-summary.json')['arms']['skill']
        stats=analysis.arm_report(root,task,'skill',actual,summary,exposure['arms'][tid+'/skill'])
        stats['read_activity']=read_activity(root/tid/'skill');comparison['tasks'][tid]={'skill':stats}
        prior=old['tasks'][tid]['skill'];delta=change(prior['wall_seconds'],stats['wall_seconds'])
        comparable=actual['status']==prior['status'] and actual['status'] in ['prepared','completed']
        if tid=='W01':comparable=comparable and actual.get('source_preserving',False)
        wording=f'{delta:+.1f}%' if comparable else '完成范围不同'
        lines.append(f'| {tid} | {prior["wall_seconds"]:.3f} | {stats["wall_seconds"]:.3f} | {wording} | {prior["tool_calls"]}→{stats["tool_calls"]} | {prior["actual_solver_starts"]}→{stats["actual_solver_starts"]} | {analysis.label(actual["status"])} |')
        result[tid]={'old_skill':prior,'current_skill':stats,'wall_change_percent':delta,'comparable_completion_scope':comparable,
            'old_bare_reference':old['tasks'][tid]['bare'],
            'new_vs_old_bare_wall_change_percent':change(old['tasks'][tid]['bare']['wall_seconds'],stats['wall_seconds'])}
    lines+=['','## 链路与联网观察','','| 题目 | 网页工具 旧→新 | 启动前源码查看 旧→新 | 启动前环境探测 旧→新 | 首次求解前耗时 旧→新 / 秒 | 末次退出后耗时 旧→新 / 秒 |',
            '|---|---:|---:|---:|---|---|']
    for task in manifest['tasks']:
        tid=task['id'];now=result[tid]['current_skill'];prior=result[tid]['old_skill']
        currentwf=workflow['current']['tasks'][tid]['skill'];oldwf=workflow['old']['tasks'][tid]['skill']
        web=lambda item:sum(item['tools_by_name'].get(t,0) for t in ['web_fetch','web_search'])
        lines.append(f'| {tid} | {web(prior)}→{web(now)} | {oldwf["before_counts"]["solver_source_content"]}→{currentwf["before_counts"]["solver_source_content"]} | {oldwf["before_counts"]["environment_probe"]}→{currentwf["before_counts"]["environment_probe"]} | {prior["phases_seconds"]["before_first_solve"]}→{now["phases_seconds"]["before_first_solve"]} | {prior["phases_seconds"]["after_last_solve"]}→{now["phases_seconds"]["after_last_solve"]} |')
    lines+=['','P02 无求解阶段。源码、环境统计按相同工具参数分类规则计算，代表可观察的查看/探测尝试，不是文件IO次数；一次命令可读取多个文件。网页工具次数为0也不单独证明所有脚本从未发起网络尝试，任务子进程的 seccomp 与启动配置另提供执行限制。','']
    for task in manifest['tasks']:
        tid=task['id'];actual=verified['tasks'][tid]['skill'];stats=result[tid]['current_skill'];reads=stats['read_activity']
        lines += [f'## {tid}','','技能加载：'+', '.join(stats['skill_loads'])+'。',
            f'工具{stats["tool_calls"]}次，模型步骤{stats["steps"]}，其中多工具步骤{stats["multi_tool_steps"]}轮；多工具提交不保证宿主并行执行。',
            f'首次技能加载前有{reads["calls_before_first_skill"]}次工具调用，其中读取类动作{reads["read_like_calls_before_first_skill"]}次；全程读取类动作{reads["read_like_calls"]}次。']
        repeated=reads['repeated_literal_paths']
        lines += ['读取类调用中重复提及的字面路径：'+(json.dumps(repeated,ensure_ascii=False) if repeated else '未在可识别的字面路径中发现')+'。']
        if tid=='P02':lines+=['几何半径与材料冷态尺寸：'+json.dumps({'radii_m':actual.get('geometry_radii_m'),'cold_dimensions_m':actual.get('cold_dimensions_m')},ensure_ascii=False)+'。']
        elif tid=='C04' and actual.get('final_oxide'):
            lines+=[f'原始 cladOuter 终态厚度：{actual["final_oxide"]["mean_m"]:.12g} m = {actual["final_oxide"]["mean_um"]:.9f} μm；实际目录 `{actual["final_time_directory"]}`；物理秒{actual["final_physical_seconds"]:.6f}。']
        elif tid=='W01':
            lines+=['源物理选择器保持：'+str(actual.get('source_preserving'))+'；正常分段：'+json.dumps(actual.get('normal_segments'),ensure_ascii=False)+'。',
                '交接状态：'+json.dumps(actual.get('checkpoint_carry'),ensure_ascii=False)+'。',
                '源 baseCase 为续算骨架，多数模块为 fromLatestTime、气体/FGR 未开启；比较范围以该源配置为准。']
        failed=[item['check'] for item in actual['checks'] if not item['passed']]
        if failed:lines+=['未通过检查：'+', '.join(failed)+'。']
        for i,event in enumerate(actual['executions'],1):
            lines += [f'启动{i}：退出码{event["exit_code"]}，正常终止{event["normal"]}，实际终态{event["physical_last_time_s"]}物理秒。']
        lines+=['']
    lines += ['## 证据','',f'完整性检查通过：{integrity["passed"]}，共{len(integrity["checks"])}项。源、原题面和冻结插件保持不变；所有实际启动均纳入预算，独立核对未进行补算。未启动的 bare 目录仅为读取拒绝检查的输入夹具，不是本轮裸组运行。','',
        '[中文单行轨迹](中文单行轨迹/总索引.md)｜[独立完成度](verification.json)｜[单位与交接核对](delivery-consistency.json)｜[完整性](integrity.json)｜[链路分类](workflow-audit.json)｜[机器可读对比](skill-retest-summary.json)']
    save(root/'comparison.json',comparison);save(root/'skill-retest-summary.json',result)
    (root/'结果汇总.md').write_text('\n'.join(lines)+'\n')
    # Evaluation code is outside the participant read boundary; retain the exact versions used.
    evidence=root/'evaluation';evidence.mkdir(exist_ok=True)
    files=['evaluate_suite.py','check_delivery.py','audit_exposure.py','audit_workflow.py','finalize_evidence.py','analyze_suite.py','report_skill_retest.py']
    import shutil
    for name in files:shutil.copy2(HERE/name,evidence/name)
    shutil.copy2(HERE.parent/'fuel-rod-power-ab/verify_results.py',evidence/'reference_reader.py')
    save(evidence/'manifest.json',{'scope':'组织者只读独立核对，无求解启动','files':{name:sha(evidence/name) for name in files+['reference_reader.py']}})
    print(json.dumps({tid:{'status':r['current_skill']['status'],'wall_seconds':r['current_skill']['wall_seconds'],'tools':r['current_skill']['tool_calls'],'starts':r['current_skill']['actual_solver_starts'],'change_percent':r['wall_change_percent']} for tid,r in result.items()},ensure_ascii=False))

if __name__=='__main__':main()
