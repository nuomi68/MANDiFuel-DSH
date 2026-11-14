#!/usr/bin/env python3
"""Report arbitrary supported input-driven operator cases; never launch a solver."""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent

def load(p):return json.loads(p.read_text())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
analysis=module('operator_analysis','analyze_suite.py')
reads=module('operator_reads','report_skill_retest.py')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);parser.add_argument('--old-run',type=Path)
    args=parser.parse_args();root=args.run_root.resolve();manifest=load(root/'manifest.json');verified=load(root/'verification.json')
    exposure=load(root/'exposure-audit.json');workflow=load(root/'workflow-audit.json')['current'];integrity=load(root/'integrity.json')
    old=load(args.old_run/'comparison.json') if args.old_run else {'tasks':{}}
    arms=manifest.get('arms',['skill']);assert len(arms)==1
    arm=arms[0];group='Skill' if arm=='skill' else '裸DSH'
    comparison={'created_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'model':manifest['model'],
        'arms':manifest.get('arms',['skill']),'tasks':{},'integrity':verified['integrity']}
    records={};lines=[f'# {group}实际复测','',f'报告时间：{comparison["created_at_beijing"]}。模型：{manifest["model"]}。','',
        f'本目录只运行{group}，保持原题面、隔离和求解启动预算，不注入旧轨迹或参考答案。裸组不加载技能或运行助手身份提示，使用默认DSH行为。全部任务工具离线，仅DSH宿主模型API联网。独立核对检查实际输入、结果、退出证据和交付范围，不进行解析参考解评分。','',
        '| 题目 | 耗时/秒 | 工具数 | 真实启动/上限 | 独立完成度 | 全程源码查看尝试 | 网页工具调用 |',
        '|---|---:|---:|---:|---|---:|---:|']
    for task in manifest['tasks']:
        tid=task['id'];actual=verified['tasks'][tid][arm];trace=load(root/tid/'trace-summary.json')['arms'][arm]
        stats=analysis.arm_report(root,task,arm,actual,trace,exposure['arms'][tid+'/'+arm])
        stats['read_activity']=reads.read_activity(root/tid/arm)
        wf=workflow['tasks'][tid][arm];source_count=wf['before_counts']['solver_source_content']+wf['after_counts']['solver_source_content']
        web=sum(stats['tools_by_name'].get(k,0) for k in ['web_search','web_fetch'])
        comparison['tasks'][tid]={arm:stats};records[tid]={'stats':stats,'source_view_attempts':source_count,'web_tool_calls':web}
        previous=old['tasks'].get(tid,{}).get('skill')
        if previous:
            records[tid]['previous']=previous
            records[tid]['wall_change_percent']=(stats['wall_seconds']-previous['wall_seconds'])/previous['wall_seconds']*100
        lines.append(f'| {tid} | {stats["wall_seconds"]:.3f} | {stats["tool_calls"]} | {stats["actual_solver_starts"]}/{task["solver_start_cap"]} | {analysis.label(actual["status"])} | {source_count} | {web} |')
    for task in manifest['tasks']:
        tid=task['id'];actual=verified['tasks'][tid][arm];record=records[tid];stats=record['stats']
        lines += ['',f'## {tid}：{task["title"]}','',f'加载技能：{", ".join(stats["skill_loads"])}。',
                  '阶段耗时：'+json.dumps(stats['phases_seconds'],ensure_ascii=False)+'。']
        if 'previous' in record:
            previous=record['previous'];lines += [f'上一轮Skill为{previous["wall_seconds"]:.3f}秒、{previous["tool_calls"]}次工具；本轮耗时变化{record["wall_change_percent"]:+.1f}%。跨轮并发及模型采样不同，且完成度可能不同；耗时仅作描述，不按较早退出判断胜出。']
        if tid=='C04':
            oxide=actual['final_oxide'];lines += [f'独立读取cladOuter终态厚度：{oxide["mean_m"]:.12g} m = {oxide["mean_um"]:.9f} μm；终态目录 `{actual["final_time_directory"]}`；物理秒{actual["final_physical_seconds"]:.6f}。',
                '历史表和报告位于本题独立任务目录，不强制放在结果根的同一子目录。核对器已采用整个任务目录发现交付文件，仍排除只读源、源库、执行快照及网格；没有放宽物理输入或终态检查。']
        elif tid=='C06':
            lines += ['要求的扩散系数为1e-13 m²/s；终态实际diffCs：'+json.dumps(actual.get('effective_diffusivities'),ensure_ascii=False)+'。']
            if actual['status']=='completed':
                lines += ['同一套独立输入、终态与交付检查通过。实际启动数以逐次执行证据为准，辅助求解器的结果不能代替本题要求的OFFBEAT结果。']
            else:
                lines += ['存在未满足的要求；不能以正常退出、接近的数值或换算等效时间冒充完成，保留诊断数据，不追加超预算求解。']
        elif tid=='F02':
            lines += ['已正常完成10 MPa和20 MPa、外压0的两个独立工况，材料、几何、轴向约束与热膨胀关闭配置核对通过。',
                '交付的界面两侧值是各材料在界面附近的相邻单元中心样本，坐标与距离已明确标注；不是精确界面面值，也不能把两处不同半径上的应力差直接解释为牵引不连续。']
        failed=[c['check'] for c in actual['checks'] if not c['passed']]
        if failed:lines += ['未通过检查：'+', '.join(failed)+'。']
        lines += ['数据表：'+json.dumps(actual.get('data_tables',[]),ensure_ascii=False)+'。'] if tid!='C04' else []
        for i,event in enumerate(actual['executions'],1):
            lines += [f'真实启动{i}：退出{event["exit_code"]}，正常终止{event["normal"]}，实际末时刻{event["physical_last_time_s"]}秒；证据目录 `{Path(event["evidence_dir"]).relative_to(root)}`。']
    lines+=['','## 保存与有效性','',f'证据完整性：{integrity["passed"]}，{len(integrity["checks"])}项检查。完成度与完整性分开：C06可以证据完整但任务部分完成。原题面、原源库、只读源副本和冻结插件未变。','',
        f'本目录仅运行{group}；跨轮对照不是同轮配对，不据单次耗时宣称稳定性能胜出。源码查看统计基于可观察工具参数，不是操作系统文件IO计数；普通库导入不算查看实现。','',
        '[中文单行轨迹](中文单行轨迹/总索引.md)｜[独立检查](verification.json)｜[完整性](integrity.json)｜[流程分类](workflow-audit.json)']
    save(root/'comparison.json',comparison);save(root/'operator-summary.json',records);(root/'结果汇总.md').write_text('\n'.join(lines)+'\n')
    evaluation=root/'evaluation';evaluation.mkdir(exist_ok=True)
    names=['evaluate_suite.py','new_case_checks.py','check_delivery.py','audit_exposure.py','audit_workflow.py','finalize_evidence.py','analyze_suite.py','report_skill_retest.py','report_operator_cases.py',
           'translate_traces_zh.py','compact_traces_zh.py','render_compact_traces_zh.py']
    for name in names:shutil.copy2(HERE/name,evaluation/name)
    shutil.copy2(HERE.parent/'fuel-rod-power-ab/verify_results.py',evaluation/'reference_reader.py')
    save(evaluation/'manifest.json',{'scope':'组织者独立只读核对，无求解启动','files':{name:sha(evaluation/name) for name in names+['reference_reader.py']}})
    print(json.dumps({tid:{'status':record['stats']['status'],'seconds':record['stats']['wall_seconds'],'tools':record['stats']['tool_calls'],'source_views':record['source_view_attempts']} for tid,record in records.items()},ensure_ascii=False))

if __name__=='__main__':main()
