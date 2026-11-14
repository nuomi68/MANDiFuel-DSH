#!/usr/bin/env python3
"""Summarize a history replay without exporting model reasoning bodies."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from summarize_traces import arm_summary, markdown_cell
from verify_results import check_arm, DEFAULT_SOURCE


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def metrics(summary, verification):
    run = summary['run']
    starts = verification.get('recorded_solver_starts', [])
    per_step = Counter(c['step'] for c in summary['timeline'])
    first = None
    if starts:
        first = (datetime.fromisoformat(starts[0]['started_at_utc']) -
                 datetime.fromisoformat(run['started_at_utc'])).total_seconds()
    return {
        'run_status': summary['run_status'], 'wall_seconds': run.get('wall_seconds'),
        'steps': summary['steps_started'], 'tool_calls': summary['tool_calls'],
        'tool_failures': summary['tool_failures'],
        'steps_with_multiple_tools': sum(n > 1 for n in per_step.values()),
        'solver_starts': len(starts), 'solver_start_budget_respected': len(starts) <= 3,
        'first_solver_after_seconds': round(first, 3) if first is not None else None,
        'field_values_available_count': verification['field_values_available_count'],
        'normally_completed_count': verification['normally_completed_count'],
        'strict_pass': verification['passed'], 'tokens': summary['tokens'],
        'tools_by_name': summary['tools_by_name'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_root', type=Path)
    args = parser.parse_args()
    root = args.run_root.resolve()
    archive = root / 'baseline-archive'
    summary = arm_summary(root, 'skill')
    previous = json.loads((archive / 'observable_trace.json').read_text())
    old_verified = json.loads((archive / 'verification.json').read_text())
    verified = check_arm(root, 'skill', DEFAULT_SOURCE)
    save(root / 'trace-summary.json', {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'run_root': str(root), 'arms': {'skill': summary},
        'notes': ['Observable actions only; no reasoning bodies exported.'],
    })
    save(root / 'verification.json', {'run_root': str(root), 'arms': {'skill': verified}, 'passed': verified['passed']})
    baseline = metrics(previous, old_verified)
    current = metrics(summary, verified)
    paired = []
    old_cases = {c['q_W_per_m']: c for c in old_verified['cases'] if c.get('independent_response')}
    for case in verified['cases']:
        q = case['q_W_per_m']
        if q in old_cases and case.get('independent_response'):
            for field in ('fuel_T_max_K', 'cladding_T_max_K'):
                delta = case['independent_response'][field] - old_cases[q]['independent_response'][field]
                tolerance = case['rounding_tolerance_K'][field] + old_cases[q]['rounding_tolerance_K'][field]
                paired.append({'q_W_per_m': q, 'field': field, 'new_minus_previous_K': delta,
                               'tolerance_K': tolerance, 'passed': abs(delta) <= tolerance})
    comparison = {'baseline': baseline, 'with_history': current, 'paired_response_checks': paired}
    save(root / 'comparison.json', comparison)

    lines = ['# 附带第一次历史的 DSH 可观察工具轨迹', '',
             '工具参数与返回状态记录；没有模型内部推理正文。时间为北京时间。', '',
             '| 序号 | 模型步骤 | 北京时间 | 工具 | 参数摘要 | 工具返回状态 |',
             '|---:|---:|---|---|---|---|']
    for i, call in enumerate(summary['timeline'], 1):
        when = datetime.fromisoformat(call['started_at_utc']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%H:%M:%S')
        cells = (i, call['step'], when, call['name'], call['arguments_preview'], call['status'])
        lines.append('| ' + ' | '.join(markdown_cell(x) for x in cells) + ' |')
    (root / 'flow-trace.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps(comparison, ensure_ascii=False))


if __name__ == '__main__':
    main()
