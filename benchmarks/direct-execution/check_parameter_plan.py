#!/usr/bin/env python3
"""使用真实原生字典解析器和保留场，检查参数契约及事务边界；不启动求解器。"""
from pathlib import Path
import copy
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'lib'))
from mandifuel_prepare import parameter_plan as api
from mandifuel_prepare.foam_edit import set_foam_entry, get_foam_entry

SOURCE = ROOT / 'runs/run-assistant-newcases-20261113-01/C06/source-case'
request = {
    'bindings': [{'contract': 'fpdiffusion-cs-constant-v1', 'zone': 'Kernel', 'value': 2e-13}],
    'edits': [{'file': 'system/controlDict', 'entry': 'endTime', 'value': '20000'},
              {'file': '0/T', 'entry': 'internalField', 'value': 'uniform 1800'}],
    'expected_fields': {'T': 1800, 'sourceCs': 0}
}
checks = []

def check(name, condition):
    assert condition, name
    checks.append(name)


def rejected(source, target, plan):
    try:
        api.prepare_case(source, target, plan)
    except (ValueError, RuntimeError):
        check('失败不交付目标：' + target.name, not target.exists())
    else:
        raise AssertionError('应拒绝 ' + target.name)


with tempfile.TemporaryDirectory(prefix='parameter-plan-check-') as work:
    work = Path(work); source = work / 'source'
    shutil.copytree(SOURCE, source)
    original = api.fingerprint(source)
    case = work / 'case'
    prepared = api.prepare_case(source, case, request)
    check('参数绑定真实所有者', float(api.read(case, 'constant/solverDict', 'materials/Kernel/fissionProductsTransport/Cs/d1')) == 2e-13)
    check('批量跨文件编辑', api.read(case, 'system/controlDict', 'endTime') == '20000' and api.read(case, '0/T', 'internalField') == 'uniform 1800')
    check('源输入未改', api.fingerprint(source) == original)
    check('无关初场未改', (source/'system/fvSchemes').read_bytes() == (case/'system/fvSchemes').read_bytes() and not (case/'0/D').exists())
    check('准备和物理生效分开', prepared['status'] == 'input_readback_only' and api.verify_case(case)['status'] == 'not_run')
    with patch.object(api, '_native', side_effect=AssertionError('不应重复解析')):
        check('重复准备零原生回读', api.prepare_case(source, case, request)['reused'])
    for value in (0, -1, float('nan'), float('inf')):
        bad = copy.deepcopy(request); bad['bindings'][0]['value'] = value
        rejected(source, work / ('invalid-' + str(value)), bad)
    bad = copy.deepcopy(request); bad['edits'].append({'file': 'system/controlDict', 'entry': 'typoUnknownEntry', 'value': 5})
    rejected(source, work / 'unknown', bad)
    bad = copy.deepcopy(request); bad['edits'].append({'file': 'constant/solverDict', 'entry': 'materials/Kernel/material', 'value': 'other'})
    rejected(source, work / 'conflict', bad)
    altered = work / 'wrong-source'; shutil.copytree(source, altered)
    set_foam_entry(altered, 'constant/solverDict', 'materials/Kernel/material', 'Zr')
    rejected(altered, work / 'wrong-material', request)
    set_foam_entry(altered, 'constant/solverDict', 'materials/Kernel/material', 'UO2')
    set_foam_entry(altered, 'constant/solverDict', 'elementTransportOptions/solvers', '(FpDiffusion other)')
    rejected(altered, work / 'wrong-solver', request)
    # 已有契约块附加未修改项应保留。
    extra = work / 'extra'; shutil.copytree(case, extra); (extra/api.RECEIPT).unlink()
    api._native(extra/'constant/solverDict', 'materials/Kernel/fissionProductsTransport/Cs/retainedOption', '-set', '17', executable='foamDictionary')
    prepared_extra = work / 'prepared-extra'
    api.prepare_case(extra, prepared_extra, request)
    check('保留契约块其他项', api.read(prepared_extra, 'constant/solverDict', 'materials/Kernel/fissionProductsTransport/Cs/retainedOption') == '17')
    # 正、反实际场来自既有真实运行，完全只读，不另启动 OFFBEAT。
    correct = ROOT / 'runs/c06-bare-retest-20261114-01/C06/bare/workspace/cs-sphere-diffusion/case'
    good = api.scalar_field(correct, '50000', 'diffCs')
    check('实际常 D 正例', good['min'] == good['max'] == 1e-13 and good['dimensions'] == [0,2,-1,0,0,0,0])
    wrongs = list((ROOT / 'runs/run-assistant-newcases-20261113-01/C06/skill/workspace').glob('**/50000/diffCs'))
    check('实际 D 失配反例', any(api.scalar_field(p.parent.parent, '50000', 'diffCs')['min'] != 1e-13 for p in wrongs))
    # 用真实保留场/日志和明确标注的测试凭据覆盖完整验证及库存操作，不启动求解。
    fixture_plan = copy.deepcopy(request)
    fixture_plan['bindings'][0]['value'] = 1e-13
    fixture_plan['edits'][0]['value'] = '50000'
    fixture_plan['edits'][1]['value'] = 'uniform 1873.15'
    fixture_plan['edits'] += [
        {'file': 'system/controlDict', 'entry': 'startFrom', 'value': 'startTime'},
        {'file': 'system/controlDict', 'entry': 'startTime', 'value': '0'}]
    fixture_plan['expected_fields']['T'] = 1873.15
    fixture_case = work / 'actual-field-fixture'
    api.prepare_case(source, fixture_case, fixture_plan)
    shutil.copytree(correct/'50000', fixture_case/'50000')
    shutil.copytree(correct/'constant/polyMesh', fixture_case/'constant/polyMesh')
    actual_log = (correct.parent/'logs/offbeat_launch1.log').read_text().splitlines()
    end_index = max(i for i, line in enumerate(actual_log) if line.strip().lower() == 'end')
    (fixture_case/'log.fixture').write_text('\n'.join(actual_log[:end_index+1]) + '\n')
    api.save_json(fixture_case/'.mandifuel-execution.json', {
        'fixture_only': True, 'status': 'completed', 'exit_code': 0,
        'end_time': '50000', 'final_time': '50000', 'log': str(fixture_case/'log.fixture')})
    verification = api.verify_case(fixture_case)
    assert verification['status'] == 'verified', json.dumps(verification, ensure_ascii=False)
    check('完整实际场检查通过', True)
    inventory = api.export_cs_inventory(fixture_case, '50000')
    check('公共结果 API 库存与独立留存值一致', abs(inventory['release_fraction'] - 0.7173675647542952) < 1e-10)
    fixture_plan['cs_inventory'] = True
    # 新计划需独立目标；先准备，再装入同一只读保留场夹具。
    relative_case = work / 'relative-case'
    api.prepare_case(source, relative_case, fixture_plan)
    shutil.copytree(fixture_case/'50000', relative_case/'50000')
    shutil.copytree(fixture_case/'constant/polyMesh', relative_case/'constant/polyMesh')
    shutil.copyfile(fixture_case/'.mandifuel-execution.json', relative_case/'.mandifuel-execution.json')
    original_directory = Path.cwd()
    try:
        os.chdir(work)
        relative = api.run_plan(Path('source'), Path('relative-case'), fixture_plan, ['false'])
        check('相对路径完整入口与终态复用', relative['status'] == 'verified' and relative['preparation_reused'] and abs(relative['results']['release_fraction'] - inventory['release_fraction']) < 1e-14)
    finally:
        os.chdir(original_directory)
    shutil.copyfile(wrongs[0], fixture_case/'50000/diffCs')
    check('实际场失配被拦截', api.verify_case(fixture_case)['status'] == 'mismatch')
    api.save_json(fixture_case/'.mandifuel-execution.json', {
        'fixture_only': True, 'status': 'failed', 'exit_code': 1,
        'end_time': '50000', 'final_time': '50000', 'log': str(fixture_case/'log.fixture')})
    check('失败凭据不能靠终态文件冒充完成', api.verify_case(fixture_case)['status'] == 'not_completed')
    # 输入改动后禁止复用；保留已有目录，不能覆盖证据。
    set_foam_entry(case, 'system/controlDict', 'endTime', '123')
    try:
        api.prepare_case(source, case, request)
    except ValueError:
        check('改动后拒绝复用并保留输入', api.read(case, 'system/controlDict', 'endTime') == '123')
    else:
        raise AssertionError('应拒绝旧目标')
print(json.dumps({'passed': len(checks), 'checks': checks, 'solver_starts': 0}, ensure_ascii=False, indent=2))
