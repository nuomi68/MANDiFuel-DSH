#!/usr/bin/env python3
"""固定扫描的共享入口；复制到任务目录为 study.py，再编写 study_definition.py。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition', default='study_definition.py',
                        help='当前任务目录中的绑定文件，默认 study_definition.py')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    definition = (root / args.definition).resolve()
    if not definition.is_relative_to(root) or not definition.is_file():
        raise ValueError('绑定文件必须存在于当前任务目录内；先复制模板并编写 study_definition.py')
    plugin_value = os.environ.get('MANDIFUEL_PLUGIN_ROOT')
    if not plugin_value:
        raise ValueError('缺少 MANDIFUEL_PLUGIN_ROOT；请使用配置好的 MANDiFuel 启动环境')
    plugin = Path(plugin_value).resolve()
    entry = plugin / 'skills/conduct-offbeat-study/scripts'
    if not (entry / 'study_runner.py').is_file():
        raise ValueError('插件中的共享 Study 入口不存在')
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(entry))
    from study_runner import Study

    spec = importlib.util.spec_from_file_location('mandifuel_task_definition', definition)
    if spec is None or spec.loader is None:
        raise ValueError('无法加载任务绑定文件')
    bindings = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bindings
    spec.loader.exec_module(bindings)
    points = list(bindings.POINTS)
    if not points or any(not isinstance(p, dict) for p in points):
        raise ValueError('POINTS 必须是非空的参数字典列表')
    keys = [json.dumps(p, sort_keys=True, allow_nan=False) for p in points]
    if len(set(keys)) != len(keys):
        raise ValueError('点身份重复；有意复测或授权重试需要独立 id 或 seed')
    prepare = bindings.prepare
    reporting = bindings.extract_reporting
    writer = getattr(bindings, 'write_report', None)
    if not callable(prepare) or not callable(reporting) or (writer is not None and not callable(writer)):
        raise ValueError('prepare、extract_reporting 和可选 write_report 必须可调用')
    workers = getattr(bindings, 'WORKERS', 1)
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError('WORKERS 必须是正整数')
    command = getattr(bindings, 'COMMAND', ['bash', 'run.sh'])
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(v, str) for v in command):
        raise ValueError('COMMAND 必须是非空的命令参数列表')

    study = Study(root, prepare=prepare, command=command)
    history = study.run(points, workers=workers)
    history = study.collect(reporting)
    records = {json.dumps(r['point'], sort_keys=True, allow_nan=False): r for r in history}
    requested = [records[k] for k in keys if k in records]
    completed = sum(r['status'] == 'completed' for r in requested)
    collected = sum(r['status'] == 'completed' and r.get('reporting_status') == 'completed'
                    for r in requested)
    summary = {
        'entrypoint': 'study_runner.Study',
        'requested_points': len(points),
        'history_entries': len(history),
        'normal_completed': completed,
        'reporting_completed': collected,
        'missing_points': len(points) - len(requested),
        'delivery_status': 'pending' if writer else 'not_requested',
        'passed': len(requested) == len(points) and completed == collected == len(points),
    }
    path = root / 'study-summary.json'
    write_json(path, summary)
    if writer:
        try:
            writer(history)
            summary['delivery_status'] = 'completed'
        except Exception as exc:
            summary.update(delivery_status='failed', delivery_error=f'{type(exc).__name__}: {exc}',
                           passed=False)
        write_json(path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'研究配置或执行失败：{type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)
