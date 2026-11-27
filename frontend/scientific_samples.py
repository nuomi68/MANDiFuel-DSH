"""Finite-volume samples bound to a registered case, mesh instance and saved time."""
import hashlib
import math
from functools import lru_cache
from pathlib import Path

from source_metadata import case_time_unit
from mandifuel_verify.case import Case, Sources, foam, result_api, stamp
from mandifuel_verify.checks import CONCENTRATION, TEMPERATURE, initial_cs_inventory
from mandifuel_verify.inputs import Unavailable, dictionary, get, scalar, word


def source_case(work, relative):
    work = Path(work).resolve()
    if not relative:
        raise Unavailable('目标视图缺少原始算例路径')
    return Sources(work).path(work / relative)


def patch_geometry(case, time):
    sources = Sources(case)
    names = result_api.describe_mesh(case, time=time)['primitive_sources']
    paths = tuple(sources.path(case/names[k]) for k in ('boundary','points','faces'))
    return _patch_geometry(paths, tuple(tuple(stamp(p)) for p in paths))


@lru_cache(maxsize=12)
def _patch_geometry(paths, signature):
    from export_case import display_patches
    boundary, points_file, faces_file = paths
    points, faces = foam.parse_points(points_file), foam.parse_faces(faces_file)
    result = {}
    for patch in display_patches(boundary):
        if patch.patch_type in {'wedge','empty','symmetry','symmetryPlane'}:
            continue
        samples = []
        for i in range(patch.start_face, patch.start_face+patch.n_faces):
            centre, _ = foam._face_centre_and_area(points, faces[i], face_label=i)
            radii = [math.hypot(*points[j]) for j in faces[i]]
            radius = max(radii) if math.isclose(min(radii),max(radii),rel_tol=1e-7) else None
            samples.append((i,tuple(map(float,centre)),radius))
        result[patch.name] = samples
    if signature != tuple(tuple(stamp(p)) for p in paths):
        raise Unavailable('读取期间边界网格已更新')
    return result


def boundary_field(sources, case, time, name, patch, count, *, dimensions=None):
    path = case/time/name
    data = foam.parse_boundary_values_text(sources.text(path), patch_name=patch, expected_count=count, source_path=str(path))
    if data.object_name != name or dimensions is not None and tuple(data.dimensions) != dimensions:
        raise Unavailable('边界场对象或量纲与响应定义不一致：'+name)
    return data


def shell_boundary_samples(case, time, choices):
    """Only a unique stored face can supply a point value without averaging."""
    samples = {}
    sources = Sources(case)
    for patch, faces in patch_geometry(case, time).items():
        if len(faces) != 1:
            continue
        face, centre, vertex_radius = faces[0]
        if vertex_radius is None:
            continue
        fields = {}
        for key, name, component in choices:
            try:
                dimensions = {'sigma':(1,-1,-2,0,0,0,0), 'sigmaCyl':(1,-1,-2,0,0,0,0),
                              'D':(0,1,0,0,0,0,0), 'T':TEMPERATURE, 'Cs':CONCENTRATION}.get(name)
                data = boundary_field(sources, case, time, name, patch, 1, dimensions=dimensions)
                if component not in foam.component_names(data.field_kind):
                    continue
                value = float(data.values[0][foam.component_index(data.field_kind, component)])
                if math.isfinite(value):
                    fields[key] = value
            except ValueError:
                # A patch without a saved value is unavailable for this selector.
                continue
        if fields:
            samples[patch] = dict(face=face, point=centre, radius=math.hypot(*centre), fields=fields)
    if not sources.unchanged():
        raise Unavailable('读取期间边界场发生变化')
    return samples


def outlet_wall(case, time):
    """NaCoolantChannel along +z, at the last axial face centre, in kelvin."""
    src = Sources(case)
    bc = get(dictionary(src.text(case/'0/T')), 'boundaryField', 'outerSurface')
    if word(bc,'type') != 'NaCoolantChannel' or scalar(bc,'massFlowRate') <= 0 or ('flowDirection' in bc and scalar(bc,'flowDirection') != 1):
        raise Unavailable('当前边界不符合正向钠冷通道的出口定义')
    faces = patch_geometry(case,time).get('outerSurface',[])
    if not faces:
        raise Unavailable('缺少 outerSurface 边界面')
    highest = max(p[2] for _,p,_ in faces)
    ids = [i for i,(_,p,_) in enumerate(faces) if math.isclose(p[2],highest,rel_tol=1e-12,abs_tol=1e-15)]
    data = boundary_field(src,case,time,'T','outerSurface',len(faces),dimensions=TEMPERATURE)
    values = [float(data.values[i][0]) for i in ids]
    if data.field_kind!='scalar' or not all(math.isfinite(v) for v in values) or min(values)!=max(values):
        raise Unavailable('出口截面有多个不同壁温，需要明确面或面积平均口径')
    if not src.unchanged():
        raise Unavailable('读取期间保存场已更新')
    return {'value':values[0],'faces':[faces[i][0] for i in ids],'z_m':highest,'field':'T','patch':'outerSurface','time':time,'unit':'K'}


def channel_rows(work, spec, table, views):
    # Use the original CSV column semantics even if a presentation aliases them.
    columns = {c.get('path',c['id']):c['id'] for c in spec.get('columns',table['columns'])}
    wall = columns.get('wall_outlet_T_K')
    if not wall:
        return table
    identity = table.get('caseIdentity', {})
    roots = {v['id']:v.get('caseRoot') for v in views}
    rows, audits = [], []
    for row in table['rows']:
        point = row.get(identity.get('column'))
        view = identity.get('views', {}).get(point)
        case_root = roots.get(view) or identity.get('roots', {}).get(point)
        item = dict(view=view, caseRoot=case_root, point=point, delivered=row.get(wall))
        try:
            case = source_case(work, case_root)
            sources = Sources(case)
            receipt = sources.json(case/'.mandifuel-execution.json')
            time = str(receipt['final_time'])
            time_column = columns.get('final_time')
            if receipt.get('status') != 'completed' or receipt.get('exit_code') != 0 or not receipt.get('terminal_marker'):
                raise Unavailable('未找到完整的终态求解回执')
            if not math.isfinite(float(time)) or time_column and float(time) != row.get(time_column):
                raise Unavailable('样本时刻与运行回执不一致')
            item.update(outlet_wall(case, time))
            if not sources.unchanged():
                raise Unavailable('读取期间执行回执已更新')
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            item.update(value=None, reason=str(exc))
        rows.append({**row, wall:item['value']})
        audits.append(item)
    note = '出口壁温取自 outerSurface 最末轴向面中心的保存 T（K）。'
    changed = sum(a['value'] is not None and a['value'] != a['delivered'] for a in audits)
    if changed:
        note += f'其中 {changed} 行与交付表不同，显示原始边界面读数。'
    if any(a['value'] is None for a in audits):
        note += '缺少同工况原场或截面取值不唯一的行留空。'
    return {**table, 'rows':rows, 'outletAudit':audits, 'scientificNoteColumns':[wall], 'scientificNote':note}


@lru_cache(maxsize=2048)
def file_digest(path, identity):
    source = Sources(path.parent)
    data = source.read(path)
    if tuple(stamp(path)) != identity:
        raise Unavailable('读取期间源文件已更新')
    return hashlib.sha256(data).digest()


def inventory_signature(case, dates):
    for folder in case.iterdir():
        try:
            float(folder.name)
        except ValueError:
            continue
        if (folder/'polyMesh').exists():
            raise Unavailable('库存曲线需要固定网格，移动网格的体积须逐帧核查')
    sources = Sources(case)
    names = ['constant/solverDict','system/controlDict']
    names.extend('constant/polyMesh/'+name for name in ('points','faces','owner','neighbour','boundary','cellZones'))
    if (case/'0/Cs').exists():
        names.append('0/Cs')
    names.extend(t+'/Cs' for t in dates)
    signature = hashlib.sha256()
    stamps = []
    for name in names:
        path = sources.path(case/name)
        identity = tuple(stamp(path))
        signature.update(name.encode()+b'\0'+file_digest(path,identity))
        stamps.append(identity)
    return signature.hexdigest(),tuple(stamps)


def inventory_rows(work, view, view_id):
    """Inventory depletion on the displayed mesh. Never infer external flux from a fitted curve."""
    case = source_case(work, view.get('caseRoot'))
    task = view['task']
    if 'Cs' not in {f['id'] for f in task.get('fields', [])}:
        raise Unavailable('库存曲线需要该视图的 Cs 浓度场')
    times = result_api.list_times(case, 'Cs')
    names = {float(t): t for t in times}
    requested = task.get('savedTimes')
    if not requested or len(names) != len(times) or any(t not in names for t in requested):
        raise Unavailable('模型帧无法唯一匹配 Cs 原始保存目录')
    dates = tuple(names[t] for t in requested)
    signature, stamps = inventory_signature(case, dates)
    if signature != task.get('csInventorySource'):
        raise Unavailable('无法核对展示帧与库存来源版本，请从同一算例重新导出 Cs 视图')
    unit = case_time_unit(case)
    if not unit or unit != task.get('timeUnit'):
        raise Unavailable('保存时刻单位不一致')
    data = _inventory(case, dates, stamps)
    if inventory_signature(case, dates)[1] != stamps:
        raise Unavailable('读取期间库存来源已变化')
    return {'columns':[{'id':'time','unit':unit},{'id':'inventory','label':'计算域库存','unit':'mol'},{'id':'initial','label':'初始库存','unit':'mol'},{'id':'fraction','label':'相对初始库存亏损','unit':'1'}],
            'rows':[{**row,'selection':{'view':view_id,'time':row['time'],'timeUnit':unit}} for row in data],
            'scientificNote': '按当前网格计算库存亏损 (N₀ − Σ CᵢVᵢ)/N₀。两项接近时，相减会放大保存精度的影响。判断微量外释应另查源项、衰变及外部通量或原生外释记录。'}


@lru_cache(maxsize=8)
def _inventory(case, dates, stamps):
    c = Case(case, time=dates[0])
    initial, _ = initial_cs_inventory(c)
    if not math.isfinite(initial) or initial <= 0:
        raise Unavailable('初始铯库存必须为有限正数')
    volumes = c.geometry['volumes']
    rows = []
    for t in dates:
        values = c.field('Cs', time=t, dimensions=CONCENTRATION, kind='scalar')
        remaining = math.fsum(row[0] * v for row, v in zip(values, volumes, strict=True))
        rows.append(dict(time=float(t), inventory=remaining, initial=initial, fraction=(initial - remaining) / initial))
    if not c.sources.unchanged():
        raise Unavailable('读取期间场或初态已更新，请重试')
    return rows
