#!/usr/bin/env python3
"""Replay the original skill task with its observable Chinese trace attached."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_BASELINE = REPO / 'runs/fuel-rod-ab-20261111-03'
DEFAULT_ORIGINALS = REPO / 'runs/skill-batching-20261112-01/before'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def prepare(args):
    root = args.output.resolve()
    baseline = args.baseline.resolve()
    root.mkdir(parents=True, exist_ok=False)
    archive = root / 'baseline-archive'
    archive.mkdir()
    originals = {
        'first_skill_trace_zh.md': baseline / '中文过程/Skill执行过程.md',
        'first_run.json': baseline / 'skill/run.json',
        'original_task.txt': baseline / 'task.txt',
        'original_fingerprints.json': baseline / 'fingerprints.json',
        'solver-starts.jsonl': baseline / 'skill/workspace/solver-starts.jsonl',
        'binary-invocations.jsonl': baseline / 'skill/workspace/binary-invocations.jsonl',
    }
    for name, source in originals.items():
        shutil.copy2(source, archive / name)
    old_summary = json.loads((baseline / 'trace-summary.json').read_text())['arms']['skill']
    old_verification = json.loads((baseline / 'verification.json').read_text())['arms']['skill']
    save(archive / 'observable_trace.json', old_summary)
    save(archive / 'verification.json', old_verification)
    save(archive / 'archive-manifest.json', {
        'created_at_utc': now(), 'baseline_root': str(baseline),
        'files': {p.name: sha(p) for p in archive.iterdir() if p.is_file()},
        'attached_material': 'first_skill_trace_zh.md only; no previous case trees or solver output files',
    })

    # Recover the exact documented baseline, rather than confounding history
    # with the batching instructions added after that run.
    plugin = root / 'frozen-plugin'
    shutil.copytree(args.plugin_snapshot.resolve(), plugin,
                    ignore=shutil.ignore_patterns('artifact-manifest.json', '__pycache__', '.cache'))
    for source in args.originals.resolve().rglob('*'):
        if source.is_file():
            target = plugin / source.relative_to(args.originals.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (plugin / 'configs').mkdir(exist_ok=True)
    shutil.copy2(REPO / 'configs/launcher.env', plugin / 'configs/launcher.env')
    fingerprints = json.loads((archive / 'original_fingerprints.json').read_text())
    plugin_mismatches = [name for name, digest in fingerprints['plugin'].items()
                         if not (plugin / name).is_file() or sha(plugin / name) != digest]
    source_root = Path('/home/lwz/offbeat/Cases/testCases/exerciseOFFBEAT/case1_solved')
    source_mismatches = [name for name, digest in fingerprints['source'].items()
                         if not (source_root / name).is_file() or sha(source_root / name) != digest]
    save(root / 'baseline-integrity.json', {
        'plugin_files_checked': len(fingerprints['plugin']),
        'plugin_mismatches': plugin_mismatches,
        'source_files_checked': len(fingerprints['source']),
        'source_mismatches': source_mismatches,
    })
    if plugin_mismatches or source_mismatches:
        raise RuntimeError('The frozen plugin/source differs from the original baseline; see baseline-integrity.json')

    target = root / 'skill'
    workspace = target / 'workspace'
    workspace.mkdir(parents=True)
    (target / 'traces').mkdir()
    history = workspace / 'history'
    history.mkdir()
    shutil.copy2(archive / 'first_skill_trace_zh.md', history / 'first_skill_trace_zh.md')
    task = (archive / 'original_task.txt').read_text()
    (root / 'task.txt').write_text(task)
    prompt = task + '''

本轮附带的历史上下文：用户明确要求参考第一次 skill 执行本题的轨迹。
本段授权覆盖题面及 Study Protocol 中对历史材料的一般限制，仅允许使用下方
附带的记录和当前工作区 history/first_skill_trace_zh.md。记录中的旧工作区路径
只用于理解过去发生的操作，不授权读取那些目录、旧脚本、旧算例或旧求解结果。
历史是参考资料，其中的做法与结论仍需判断；本轮仍须按原题在当前工作区重新
进行三个真实求解，最多三次启动（含失败和重试），并保留本次完成证据。

<previous_run_observable_trace>
''' + (history / 'first_skill_trace_zh.md').read_text() + '\n</previous_run_observable_trace>\n'
    (root / 'prompt.txt').write_text(prompt)
    (workspace / 'task.txt').write_text(task)
    (workspace / 'request.txt').write_text(prompt)

    # Keep the original measurement mechanism, changing only its output paths.
    bin_dir = target / 'instrumented-bin'
    bin_dir.mkdir()
    wrapper = (baseline / 'skill/instrumented-bin/offbeat').read_text()
    wrapper = wrapper.replace(str(baseline / 'skill/workspace'), str(workspace))
    (bin_dir / 'offbeat').write_text(wrapper)
    (bin_dir / 'offbeat').chmod(0o755)
    launcher = root / 'launch.sh'
    frozen = shlex.quote(str(plugin))
    common = shlex.quote(str(HERE / 'common.patch.yml'))
    prompt_path = shlex.quote(str(root / 'prompt.txt'))
    launcher.write_text(f'''#!/usr/bin/env bash
set -euo pipefail
plugin_root={frozen}
source "$plugin_root/scripts/prepare-agent.sh"
mandifuel_prepare_agent_environment "$plugin_root"
source "$plugin_root/scripts/resolve-node.sh"
mandifuel_resolve_node "$MANDIFUEL_DSH"
task="$(cat {prompt_path})"
exec bash "$plugin_root/scripts/start-dsh.sh" headless --patch {common} "$task"
''')
    launcher.chmod(0o755)
    manifest = {
        'created_at_utc': now(), 'baseline_root': str(baseline),
        'design': 'one fresh skill session; original skill version with original observable Chinese history attached',
        'provider': 'deepseek-official', 'model': 'deepseek-v4-flash',
        'original_task_sha256': sha(archive / 'original_task.txt'),
        'baseline_task_sha256': sha(baseline / 'task.txt'),
        'prompt_sha256': sha(root / 'prompt.txt'),
        'attached_trace_sha256': sha(history / 'first_skill_trace_zh.md'),
        'attached_trace_bytes': (history / 'first_skill_trace_zh.md').stat().st_size,
        'frozen_plugin': str(plugin), 'solver_start_budget': 3,
        'timeout_seconds': args.timeout,
        'limits': ['Single before/after observation; no statistical causal claim.',
                   'History is a Chinese observable-action summary containing known failures, retrospective notes and previous values.',
                   'New solver starts and original fields must independently establish the new results.'],
    }
    save(root / 'manifest.json', manifest)
    return root, target, workspace, bin_dir, launcher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline', default=DEFAULT_BASELINE, type=Path)
    parser.add_argument('--originals', default=DEFAULT_ORIGINALS, type=Path)
    parser.add_argument('--plugin-snapshot', required=True, type=Path)
    parser.add_argument('--timeout', default=1200, type=int)
    args = parser.parse_args()
    root, target, workspace, bin_dir, launcher = prepare(args)
    env = dict(os.environ, BENCH_TRACE_ROOT=str(target / 'traces'), MPLBACKEND='Agg',
               PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1',
               MANDIFUEL_OFFBEAT_BIN=str(bin_dir), MANDIFUEL_RAG_CACHE_DIR=str(target / 'rag-cache'))
    start = time.monotonic()
    result = {'arm': 'skill', 'started_at_utc': now(), 'workspace': str(workspace),
              'timeout_seconds': args.timeout, 'history_attached': True,
              'plugin_version_control': 'original baseline file hashes verified'}
    with (target / 'stdout.log').open('w') as out, (target / 'stderr.log').open('w') as err:
        process = subprocess.Popen(['bash', str(launcher)], cwd=workspace, env=env,
                                   stdout=out, stderr=err, start_new_session=True)
        result['pid'] = process.pid
        save(target / 'run.json', result)
        print(json.dumps({'started': result, 'archive': str(root / 'baseline-archive')}, ensure_ascii=False), flush=True)
        try:
            result.update(exit_code=process.wait(timeout=args.timeout), timed_out=False)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            result.update(exit_code=process.returncode, timed_out=True)
    result.update(ended_at_utc=now(), wall_seconds=round(time.monotonic() - start, 3))
    save(target / 'run.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
