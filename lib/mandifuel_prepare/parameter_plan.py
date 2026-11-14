"""按已验证参数契约批量准备、执行并核对实际场；不猜测未知输入。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from .foam_edit import _native
from .geometry_angle import validated_case_file
from mandifuel_run.case import inspect_case, locked, run_case, save_json

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'skills/prepare-offbeat-case/assets/parameter-contracts.json'
RECEIPT = '.mandifuel-preparation.json'


class PlanError(ValueError):
    pass


def digest(value):
    if isinstance(value, Path):
        return hashlib.sha256(value.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def fingerprint(root, names=None):
    paths = (root / name for name in names) if names is not None else root.rglob('*')
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)
            if p.is_file() and '__pycache__' not in p.parts}


def read(case, file, entry):
    return _native(validated_case_file(case, file), entry, '-value', executable='foamDictionary')


def keys(case, file, entry):
    return _native(validated_case_file(case, file), entry, '-keywords', executable='foamDictionary').split()


def set_entry(case, file, entry, value, evidence, *, add=False):
    path = validated_case_file(case, file)
    if not add:
        _native(path, entry, '-value', executable='foamDictionary')
    _native(path, entry, '-set', str(value), executable='foamDictionary')
    observed = _native(path, entry, '-value', executable='foamDictionary')
    evidence.append({'file': file, 'entry': entry, 'value': observed})
    return observed


def number(value, name, positive=False):
    if isinstance(value, bool):
        raise PlanError(f'{name} 必须为有限数')
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise PlanError(f'{name} 必须为{"正" if positive else ""}有限数')
    return result


def validate_request(request):
    if set(request) - {'bindings', 'edits', 'expected_fields', 'cs_inventory'}:
        raise PlanError('请求含未知顶层项')
    contracts = json.loads(CATALOG.read_text())['contracts']
    bindings = request.get('bindings', [])
    if len(bindings) != 1:
        raise PlanError('当前入口要求且只支持一个已验证参数契约')
    binding = bindings[0]
    if set(binding) != {'contract', 'zone', 'value'} or binding['contract'] not in contracts:
        raise PlanError('未知参数契约或绑定格式')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', binding['zone']):
        raise PlanError('zone 必须为输入卡中的明确字典名称')
    number(binding['value'], '扩散系数', positive=True)
    seen = set()
    for edit in request.get('edits', []):
        if set(edit) != {'file', 'entry', 'value'} or not isinstance(edit['value'], (str, float, int)):
            raise PlanError('edits 每项为 file、entry、value')
        identity = edit['file'], edit['entry']
        if identity in seen:
            raise PlanError('同一输入项不能重复设置')
        seen.add(identity)
        if edit['file'] == 'constant/solverDict':
            protected = ('materials', 'elementTransport', 'materialProperties')
            if any(edit['entry'] == p or edit['entry'].startswith(p + '/') for p in protected):
                raise PlanError('材料及输运选择器由契约确认，不能同时用通用编辑覆盖')
    allowed = {'T': [0, 0, 0, 1, 0, 0, 0], 'sourceCs': [0, -3, -1, 0, 1, 0, 0]}
    for field, expected in request.get('expected_fields', {}).items():
        if field not in allowed:
            raise PlanError('当前只支持 T、sourceCs 的附加实际场检查')
        number(expected, field)
    if not isinstance(request.get('cs_inventory', False), bool):
        raise PlanError('cs_inventory 为布尔值')
    if request.get('cs_inventory') and request.get('expected_fields', {}).get('sourceCs') != 0:
        raise PlanError('内置库存外释计算要求 expected_fields/sourceCs=0 并通过实际场检查')
    return binding, contracts[binding['contract']]


def apply_binding(case, binding, contract, evidence):
    file = 'constant/solverDict'
    for entry, expected in contract['selectors'].items():
        if read(case, file, entry).strip().strip('"') != expected:
            raise PlanError(f'契约不适用：{entry} 要求 {expected}')
    solvers = read(case, file, 'elementTransportOptions/solvers')
    if re.findall(r'[A-Za-z_][A-Za-z0-9_]*', solvers) != ['FpDiffusion']:
        raise PlanError('契约只覆盖单 FpDiffusion 求解器')
    zone = binding['zone']
    material_keys = keys(case, file, 'materials')
    if set(material_keys) - {'writeMaterialProperties'} != {zone}:
        raise PlanError('契约只覆盖单一材料区，其他材料组合需要新契约')
    owner = 'materials/' + zone
    if read(case, file, owner + '/material') != 'UO2':
        raise PlanError('契约只覆盖 UO2')
    fp = owner + '/fissionProductsTransport'
    if 'fissionProductsTransport' not in keys(case, file, owner):
        set_entry(case, file, fp, '{}', evidence, add=True)
    existing = keys(case, file, fp)
    if 'fissionProductsName' in existing:
        names = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', read(case, file, fp + '/fissionProductsName'))
        if names != ['Cs']:
            raise PlanError('契约只覆盖 Cs 单组分，不改写其他裂变产物设置')
    else:
        set_entry(case, file, fp + '/fissionProductsName', '(Cs)', evidence, add=True)
    if 'Cs' not in existing:
        set_entry(case, file, fp + '/Cs', '{}', evidence, add=True)
    for leaf, value in {'d1': number(binding['value'], 'D', True), 'q1': 0, 'd2': 0, 'q2': 0}.items():
        observed = set_entry(case, file, fp + '/Cs/' + leaf, format(value, '.17g'), evidence, add=True)
        if not math.isclose(float(observed), value, rel_tol=1e-12, abs_tol=0):
            raise PlanError('原生参数回读不一致')


def prepare_case(source, case, request):
    """整套输入在暂存目录完成检查再交付；已准备且输入未变时复用记录。"""
    source, case = Path(source).resolve(), Path(case).absolute()
    validate_request(request)
    if case.is_symlink() or source == case.resolve() or source in case.resolve().parents or case.resolve() in source.parents:
        raise PlanError('源和目标必须是互不包含的独立目录')
    if not source.is_dir() or not all((source / d).is_dir() for d in ('0', 'constant', 'system')):
        raise PlanError('源必须为包含 0、constant、system 的输入骨架')
    if (source / '.mandifuel-execution.json').exists() or any(
            p.is_dir() and re.fullmatch(r'[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', p.name)
            and float(p.name) > 0 for p in source.iterdir()):
        raise PlanError('源含执行记录或正时间结果，请提供独立输入骨架')
    identity = {'request_sha256': digest(request), 'catalog_sha256': digest(CATALOG),
                'source': str(source), 'source_hashes': fingerprint(source)}
    case.parent.mkdir(parents=True, exist_ok=True)
    with locked(case.parent / ('.' + case.name + '.preparation.lock')):
        if case.exists():
            path = case / RECEIPT
            saved = json.loads(path.read_text()) if path.is_file() else {}
            if all(saved.get(k) == v for k, v in identity.items()) and saved.get('input_hashes') == fingerprint(case, saved.get('input_hashes', {})):
                return {**saved, 'reused': True}
            raise PlanError('目标已存在且没有匹配的准备证据；保留现有目录，使用新的独立目标')
        staging = Path(tempfile.mkdtemp(prefix='.' + case.name + '.', dir=case.parent))
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True, symlinks=False)
            evidence = []
            binding, contract = validate_request(request)
            apply_binding(staging, binding, contract, evidence)
            for edit in request.get('edits', []):
                set_entry(staging, edit['file'], edit['entry'], edit['value'], evidence)
            if fingerprint(source) != identity['source_hashes']:
                raise PlanError('准备期间源发生变化')
            prepared = {**identity, 'schema': 1, 'case': str(case), 'request': request,
                        'status': 'input_readback_only', 'reused': False, 'readbacks': evidence,
                        'input_hashes': fingerprint(staging), 'contract_scope': contract['scope']}
            save_json(staging / RECEIPT, prepared)
            os.rename(staging, case)
            return prepared
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def scalar_field(case, time, field):
    file = f'{time}/{field}'
    dims = [int(x) for x in re.findall(r'[-+]?\d+', read(case, file, 'dimensions'))]
    text = read(case, file, 'internalField')
    if text.startswith('uniform '):
        values = [float(text.split()[1].strip(';'))]
    else:
        match = re.fullmatch(r'nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;?', text, flags=re.S)
        if not match:
            raise PlanError(f'{file} 不是受支持的原生标量场')
        values = [float(x) for x in match[2].split()]
        if len(values) != int(match[1]):
            raise PlanError(f'{file} 列表长度不一致')
    if not values or not all(math.isfinite(x) for x in values):
        raise PlanError(f'{file} 含非有限值或为空')
    return {'field': field, 'dimensions': dims, 'min': min(values), 'max': max(values)}


def verify_case(case):
    """只有正常执行后才读取正时间实际场；输入回读不算物理生效。"""
    case = Path(case).resolve()
    prepared = json.loads((case / RECEIPT).read_text())
    request = prepared['request']
    binding, contract = validate_request(request)
    execution_path = case / '.mandifuel-execution.json'
    if not execution_path.is_file():
        return {'status': 'not_run', 'fields': [], 'reason': '没有公共执行器记录，尚未验证实际生效'}
    execution = json.loads(execution_path.read_text())
    checked = inspect_case(case, log=execution.get('log', 'log.offbeat'), end_time=execution.get('end_time'))
    if checked['status'] != 'completed' or checked['exit_code'] != 0:
        return {'status': 'not_completed', 'execution': checked, 'fields': []}
    if prepared['input_hashes'] != fingerprint(case, prepared['input_hashes']):
        raise PlanError('求解期间准备输入已改变，拒绝复用参数确认')
    times = [t for t in checked['times'] if float(t) > 0]
    if not times:
        raise PlanError('没有正时间实际场，不能用初始种子场作验证')
    expected = {'diffCs': (binding['value'], contract['field_dimensions'])}
    dims = {'T': [0, 0, 0, 1, 0, 0, 0], 'sourceCs': [0, -3, -1, 0, 1, 0, 0]}
    expected.update({k: (v, dims[k]) for k, v in request.get('expected_fields', {}).items()})
    fields = []
    # 检查所有保留正时间，而不是只检查初始化种子或终态一个数。
    for time in times:
        for field, (value, dimensions) in expected.items():
            actual = scalar_field(case, time, field)
            actual.update(time=time, expected=float(value))
            actual['passed'] = actual['dimensions'] == dimensions and all(
                math.isclose(actual[x], float(value), rel_tol=1e-9, abs_tol=0) for x in ('min', 'max'))
            fields.append(actual)
    result = {'status': 'verified' if all(f['passed'] for f in fields) else 'mismatch',
              'execution': checked, 'checked_times': times, 'fields': fields}
    save_json(case / '.mandifuel-verification.json', result)
    return result


def export_cs_inventory(case, final_time):
    """均匀初始 Cs、无源单材料算例的计算域库存和终态径向数据。"""
    case = Path(case).resolve()
    initial = number(read(case, 'constant/solverDict', 'elementTransportOptions/FpDiffusionOptions/intialFpConcentration/Cs'), '初始 Cs', True)
    if read(case, 'system/controlDict', 'startFrom') != 'startTime' or float(read(case, 'system/controlDict', 'startTime')) != 0:
        raise PlanError('内置库存提取只覆盖 startTime=0 的新鲜均匀初态')
    if (case / '0/Cs').exists():
        field = scalar_field(case, '0', 'Cs')
        if field['min'] != initial or field['max'] != initial or field['dimensions'] != [0, -3, 0, 0, 1, 0, 0]:
            raise PlanError('0/Cs 与均匀初始浓度设置不一致，需使用通用结果接口')
    sys.path.insert(0, str(ROOT / 'skills/extract-offbeat-results/scripts'))
    from result_api import read_field
    frame = read_field(case, 'Cs', time=final_time, include_volumes=True)
    if scalar_field(case, final_time, 'Cs')['dimensions'] != [0, -3, 0, 0, 1, 0, 0]:
        raise PlanError('Cs 实际量纲不是 mol/m³')
    if not frame.volumes or any(v <= 0 for v in frame.volumes) or any(c is None for c in frame.coordinates):
        raise PlanError('缺少有效体积或坐标')
    volume = math.fsum(frame.volumes)
    final = math.fsum(c * v for c, v in zip(frame.values, frame.volumes))
    start = initial * volume
    output = case / 'results'; output.mkdir(exist_ok=True)
    with (output / 'cs_radial_profile.csv').open('w') as stream:
        writer = csv.writer(stream); writer.writerow(['cell', 'r_m', 'Cs_mol_m3', 'volume_m3'])
        for label, xyz, concentration, cell_volume in sorted(zip(frame.labels, frame.coordinates, frame.values, frame.volumes), key=lambda row: math.dist(row[1], (0, 0, 0))):
            writer.writerow([label, math.dist(xyz, (0, 0, 0)), concentration, cell_volume])
    result = {'scope': '计算网格域（扇区/楔形网格不自动放大为整球）', 'time_s': float(final_time),
              'volume_m3': volume, 'initial_concentration_mol_m3': initial,
              'initial_inventory_mol': start, 'final_inventory_mol': final,
              'release_fraction': 1 - final / start, 'profile': str(output / 'cs_radial_profile.csv'),
              'radius_origin_m': [0, 0, 0]}
    save_json(output / 'cs_inventory.json', result)
    return result


def run_plan(source, case, request, command):
    case = Path(case).resolve()
    prepared = prepare_case(source, case, request)
    execution = run_case(case, command=command, log='log.offbeat')
    verified = verify_case(case)
    result = {}
    if verified['status'] == 'verified' and request.get('cs_inventory'):
        if request.get('expected_fields', {}).get('sourceCs') != 0:
            raise PlanError('内置库存外释计算要求 expected_fields/sourceCs=0 并通过实际场检查')
        result['results'] = export_cs_inventory(case, execution['final_time'])
    # 对模型返回紧凑摘要；全部逐项证据留文件，避免把百行场检查塞回上下文。
    return {'case': str(Path(case).resolve()), 'preparation_reused': prepared['reused'],
            'status': verified['status'], 'execution': execution,
            'checked_positive_times': len(verified.get('checked_times', [])),
            'mismatches': [f for f in verified.get('fields', []) if not f['passed']],
            'results': result.get('results'), 'evidence': [RECEIPT, '.mandifuel-execution.json', '.mandifuel-verification.json']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'run', 'verify'])
    p.add_argument('--source', type=Path); p.add_argument('--case', required=True, type=Path)
    p.add_argument('--request', type=Path)
    p.add_argument('--command', nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.action == 'verify':
        result = verify_case(args.case)
    else:
        if args.source is None or args.request is None:
            p.error('prepare/run 要求 --source 和 --request')
        request = json.loads(args.request.read_text())
        if args.action == 'prepare':
            result = prepare_case(args.source, args.case, request)
        else:
            if not args.command:
                p.error('run 要求 --command 后跟已确认的实际执行配方')
            result = run_plan(args.source, args.case, request, args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result.get('status') not in ('mismatch', 'not_completed', 'not_run') else 2


if __name__ == '__main__':
    raise SystemExit(main())
