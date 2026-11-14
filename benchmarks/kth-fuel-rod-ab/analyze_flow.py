#!/usr/bin/env python3
"""按真实启动事件划分可观察流程，保留中文阶段摘要。"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys


def stamp(value): return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
def load_lines(path): return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def main():
    p=argparse.ArgumentParser(); p.add_argument('run_root',type=Path); args=p.parse_args(); root=args.run_root.resolve()
    trace=json.loads((root/'trace-summary.json').read_text())
    result={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'arms':{}}
    output=root/'中文过程'; output.mkdir(exist_ok=True)
    names={'bare':'裸DSH','skill':'Skill'}
    for arm in ['bare','skill']:
        info=trace['arms'][arm]; run=info['run']; workspace=root/arm/'workspace'
        starts=load_lines(workspace/'solver-starts.jsonl'); exits=[r for r in load_lines(workspace/'solver-exits.jsonl') if r['kind']=='solve']
        began=stamp(run['started_at_utc']); ended=stamp(run['ended_at_utc']) if run.get('ended_at_utc') else None
        first=min((stamp(r['started_at_utc']) for r in starts),default=None)
        last=max((stamp(r['ended_at_utc']) for r in exits),default=None)
        phases={
            '首次求解前':{'wall_seconds':round(first-began,3) if first else None,'calls':0},
            '首次求解至最后求解结束':{'wall_seconds':round(last-first,3) if first and last else None,'calls':0},
            '最后求解后的提取与交付':{'wall_seconds':round(ended-last,3) if ended and last else None,'calls':0},
        }
        for c in info['timeline']:
            t=(c.get('started_at_ms') or 0)/1000
            key='首次求解前' if first is None or t<first else '最后求解后的提取与交付' if last and t>last else '首次求解至最后求解结束'
            phases[key]['calls']+=1
        skills=[c for c in info['timeline'] if c['name']=='skill']
        template=workspace/'study.py'; original=root/'frozen-plugin/skills/orchestrate-offbeat-study/assets/fixed_study.py'
        record={'run_status':info['run_status'],'wall_seconds':run.get('wall_seconds'),'model_steps':info['steps_started'],'tool_calls':info['tool_calls'],'tool_failures':info['tool_failures'],'actual_solver_starts':len(starts),'raw_solver_wall_seconds':sum(r['wall_seconds'] for r in exits),'phases':phases,'skill_loads':[c['arguments_preview'] for c in skills],'fixed_template_unchanged':template.exists() and hashlib.sha256(template.read_bytes()).digest()==hashlib.sha256(original.read_bytes()).digest(),'study_history_present':(workspace/'history.json').exists(),'study_summary':json.loads((workspace/'study-summary.json').read_text()) if (workspace/'study-summary.json').exists() else None}
        result['arms'][arm]=record
        text=[f'# {names[arm]}执行过程（可观察记录）','',f'当前状态：{info["run_status"]}。只记录工具动作、文件与运行证据，不包含内部推理正文。','',f'- 实际OFFBEAT启动：{len(starts)}次；包装器累计求解耗时：{record["raw_solver_wall_seconds"]:.3f}秒。',f'- 模型步骤：{record["model_steps"]}；工具调用：{record["tool_calls"]}；工具失败：{record["tool_failures"]}。',f'- 墙钟耗时：{record["wall_seconds"]}秒。','','| 阶段 | 墙钟秒数 | 工具调用数 |','|---|---:|---:|']
        text += [f'| {key} | {value["wall_seconds"]} | {value["calls"]} |' for key,value in phases.items()]
        text+=['','## 原始启动与退出','','| 次序 | 算例目录 | 实际退出码 | 求解秒数 |','|---|---|---:|---:|']
        exit_map={e['id']:e for e in exits}
        for i,s in enumerate(starts,1):
            e=exit_map.get(s['id'],{})
            text.append(f'| {i} | {s["cwd"]} | {e.get("exit_code")} | {e.get("wall_seconds")} |')
        text+=['','## 操作索引','','完整逐步工具记录见运行根目录的 `flow-trace.md`；原始会话位于本组 `traces/`。','']
        if arm=='skill':
            text += ['模型保存了 `plan.md`，分类为固定点研究，加载Orchestrate、Conduct及三项原子技能。',f'固定控制器与冻结模板逐字节一致：{record["fixed_template_unchanged"]}；共享历史存在：{record["study_history_present"]}。','首次粗网格先经公共单算例执行器运行，随后固定控制器复用该成功记录、运行其余点。这个过程没有额外增加研究点，但首次求解仍单独经过模型轮次。','公共提取器遇到结果网格元数据问题后，模型使用任务局部读者处理所需边界；求解结果被保留，没有为提取失败重新求解。','']
        else:
            text += ['本组没有技能加载，使用任务脚本生成三档算例并通过原生命令运行。','启动记录中粗网格出现两次，其余网格各一次；对照工具轨迹可核对插值设置修改与重新运行。四次启动均纳入预算。','提取阶段多次检查内部界面、面权重、梯度和中心线重构，最终交付状态以独立校验和会话终态为准。','']
        (output/f'{names[arm]}执行过程.md').write_text('\n'.join(text))
    (root/'flow-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
