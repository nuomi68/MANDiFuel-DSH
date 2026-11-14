#!/usr/bin/env python3
"""能力查询和已知输入检查：真实原生字典、保留输入及隔离变体，不启动求解器。"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'lib'))
from mandifuel_prepare import capabilities as api
from mandifuel_prepare.foam_edit import set_foam_entry

checks = []
native_calls = []
results = {}
original_run = subprocess.run


def check(name, condition):
    assert condition, name
    checks.append(name)


def guarded_run(command, *args, **kwargs):
    assert isinstance(command, list) and Path(command[0]).name == 'foamDictionary', command
    assert '-disableFunctionEntries' in command and '-no-libs' in command and '-noFunctionObjects' in command
    native_calls.append(command)
    return original_run(command, *args, **kwargs)


def fingerprint(case):
    return {str(p.relative_to(case)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('0', 'constant', 'system') if (case / folder).is_dir()
            for p in (case / folder).rglob('*') if p.is_file() and 'polyMesh' not in p.parts}


def codes(result, kind):
    return {x['code'] for x in result[kind]}


def inspect(label, case, source=None):
    before = fingerprint(case)
    result = api.check_case(case, source=source)
    assert fingerprint(case) == before, label + ': 检查修改了输入'
    assert result['solver_starts'] == 0 and not result['input_files_modified']
    results[label] = result
    return result


catalog = api.load_catalog()
with patch.object(api.subprocess, 'run', side_effect=AssertionError('静态查询不应启动进程')):
    selected = api.query(['mechanics', 'gas', 'constant_power', 'time'])
    check('一次查询返回多个相关能力', set(selected['items']) == {'mechanics', 'gas', 'constant_power', 'time'})
    check('关闭力学值与气体值分别定义', selected['items']['mechanics']['preferred_inactive'] == 'constant'
          and selected['items']['gas']['preferred_inactive'] == 'none')
    check('未知查询不会伪造能力', not any(x['value'] == 'none' for x in selected['items']['mechanics']['choices']))
    try:
        api.query(['unrecorded-capability'])
    except ValueError:
        check('未收录能力明确返回未收录', True)
    else:
        raise AssertionError('未知能力被错误声明')
check('每个选择器证据来源可追溯', all(x['sources'] and all(k in catalog['sources'] for k in x['sources'])
      for selector in catalog['selectors'].values() for x in selector['choices']))
check('未核实材料不输出猜测的selector', all(x['value'] is None for x in catalog['materials'] if not x['spelling_verified']))
check('未核实燃耗单位不补造', next(x for x in catalog['fields'] if x['name'] == 'Bu_kgU')['unit'] is None)
functions = [f for f in ast.parse((ROOT / 'skills/extract-offbeat-results/scripts/result_api.py').read_text()).body
             if isinstance(f, ast.FunctionDef) and not f.name.startswith('_')]
actual_signatures = {f.name: f.name + '(' + ast.unparse(f.args) + ')' for f in functions}
check('八个公共API签名与实际导出一致', {x['name']: x['signature'] for x in catalog['public_apis']} == actual_signatures
      and len(actual_signatures) == 8 and 'list_scopes' in actual_signatures)
references = ROOT / 'skills/prepare-offbeat-case/references'
for doc in [references / 'software-capabilities.md', *(references / 'software-capabilities').glob('*.md')]:
    for link in re.findall(r'\]\(([^)]+)\)', doc.read_text()):
        if '://' not in link and not link.startswith('#'):
            assert (doc.parent / link.split('#')[0]).exists(), (doc, link)
check('能力表的本地引用均可解析', True)
# 公共包装入口可由运行脚本导入，不依赖维护工具。
spec = importlib.util.spec_from_file_location('public_capabilities', ROOT / 'skills/prepare-offbeat-case/scripts/software_capabilities.py')
public = importlib.util.module_from_spec(spec); spec.loader.exec_module(public)
check('公开入口导出批量查询与检查', public.query is api.query and public.check_case is api.check_case)

base = ROOT / 'runs/recovery-c08-pairs-20261114-01/C08'
source = base / 'source-case'
with patch.object(api.subprocess, 'run', side_effect=guarded_run), tempfile.TemporaryDirectory(prefix='capability-check-') as temp:
    work = Path(temp)
    r = inspect('original-source', source)
    check('有效源输入保留可用', not r['errors'] and not r['warnings'])
    r = inspect('known-bad-mechanics-and-gas', base / 'skill/workspace/case', source)
    check('非法力学值和热间隙依赖同时发现', codes(r, 'errors') == {'unsupported_selector', 'gas_conductivity_required'})
    r = inspect('known-bad-gas', base / 'skill/workspace/case-a2', source)
    check('力学修正后只阻断剩余已知冲突', codes(r, 'errors') == {'gas_conductivity_required'})
    r = inspect('endpoint-warning', base / 'skill/workspace/case-a3', source)
    check('相等末点仅提示风险不一刀切拒绝', not r['errors'] and 'load_endpoint_risk' in codes(r, 'warnings'))
    r = inspect('completed-input', base / 'skill/workspace/case-a4', source)
    check('已完成输入不被要求重算', not r['errors'] and 'load_endpoint_risk' not in codes(r, 'warnings'))
    check('源载荷已经满足时提示保留', 'source_load_already_sufficient' in codes(r, 'warnings'))
    r = inspect('cs-constant-d-input', ROOT / 'runs/parameter-plan-c06-20261114-02/C06/skill/workspace/case')
    check('常D任务不因无位移初场而误拦', not r['errors'] and r['status'] == 'no_known_errors')
    fixed = work / 'fixed-temperature'; shutil.copytree(source, fixed)
    set_foam_entry(fixed, 'constant/solverDict', 'mechanicsSolver', 'constant')
    set_foam_entry(fixed, 'constant/solverDict', 'thermalSolver', 'constant')
    set_foam_entry(fixed, 'constant/solverDict', 'gapGas', 'none')
    r = inspect('fixed-temperature-inactive-gap', fixed)
    check('未被评价的热边界不强制开启气体', not r['errors'] and 'fuelRodGap' in r['observed']['temperature_boundaries'].values())
    unknown = work / 'unrecorded-model'; shutil.copytree(fixed, unknown)
    set_foam_entry(unknown, 'constant/solverDict', 'mechanicsSolver', 'customExtensionModel')
    r = inspect('unrecorded-selector', unknown)
    check('新模型未收录仅告知而不封闭能力范围', not r['errors'] and 'unverified_selector' in codes(r, 'warnings'))
    missing = work / 'missing-initial'; shutil.copytree(fixed, missing)
    (missing / '0/T').unlink()
    r = inspect('initial-state-unchecked', missing)
    check('未检查的初态明确标记覆盖限制', not r['errors'] and 'initial_boundary_not_checked' in codes(r, 'warnings'))
    mismatch = work / 'invalid-table'; shutil.copytree(source, mismatch)
    set_foam_entry(mismatch, 'constant/solverDict', 'heatSourceOptions/lhgr', '(18000)')
    r = inspect('mismatched-load-table', mismatch)
    check('时间和载荷数量不匹配提前发现', 'load_table_length' in codes(r, 'errors'))
    r = inspect('missing-dictionary', work)
    check('缺字典返回未完全检查而不伪造通过', r['status'] == 'partially_checked' and 'check_incomplete' in codes(r, 'warnings'))
    f01 = json.loads((ROOT / 'runs/generalization-pairs-20261114-01/verification.json').read_text())['tasks']['F01']['skill']
    before = Path(next(e for e in f01['executions'] if e['normal'])['evidence_dir']) / 'before'
    r = inspect('resistive-gap-without-gas', before)
    check('固定界面热阻组合不误套fuelRodGap依赖', not r['errors'] and r['observed']['gapGas'] == 'none'
          and 'resistiveGap' in r['observed']['temperature_boundaries'].values())
check('全部动态检查只调用禁用函数入口的原生字典工具', bool(native_calls))
print(json.dumps({'passed': len(checks), 'checks': checks, 'results': results, 'native_calls': len(native_calls),
                  'solver_starts': 0, 'network_calls': 0, 'retained_inputs_modified': False}, ensure_ascii=False, indent=2))
