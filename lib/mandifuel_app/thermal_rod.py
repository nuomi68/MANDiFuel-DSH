"""Registered OFFBEAT adapter for the constant-property, radially resolved fuel rod."""
from pathlib import Path
import ast
import hashlib
import json
import math
import re
import sys

REPO = Path(__file__).resolve().parents[2]
MESH = ('boundary', 'cellZones', 'faces', 'neighbour', 'owner', 'points')
DICTS = ('0/T', 'constant/solverDict', 'system/controlDict', 'system/fvSchemes', 'system/fvSolution')
INPUTS = (*DICTS, *('constant/polyMesh/' + name for name in MESH))
PARAMETERS = {
    'linearPower': ('线功率', 'W/m', ['constant/solverDict:heatSourceOptions.lhgr']),
    'outerTemperature': ('外壁温度', 'K', ['0/T:boundaryField.cladOuter.value']),
    'gapConductance': ('气隙换热系数', 'W/(m²·K)', ['0/T:boundaryField.fuelOuter.alpha', '0/T:boundaryField.cladInner.alpha']),
}
NUM = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric(value, key):
    positive = key != 'linearPower'
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or positive and value == 0):
        raise ValueError(f'{PARAMETERS[key][0]}需要有限的' + ('正数' if positive else '非负数'))
    return float(value)


def bind(case, changes=None):
    """Match registered literal slots in the vetted dictionaries, then read both gap faces back."""
    changes = changes or {}
    result = {}
    for path, slots in [
        ('constant/solverDict', [('linearPower', rf'\blhgr\s*\(\s*(?P<values>{NUM}(?:\s+{NUM})*)\s*\)\s*;')]),
        ('0/T', [(key, rf'\b{patch}\s*\{{[^{{}}]*?\b{entry}\s+uniform\s+(?P<values>{NUM})\s*;')
                 for key, patch, entry in [('outerTemperature','cladOuter','value'),
                                            ('gapConductance','fuelOuter','alpha'), ('gapConductance','cladInner','alpha')]])]:
        file = case / path
        source = file.read_text()
        for key, pattern in slots:
            hits = list(re.finditer(pattern, source))
            if len(hits) != 1:
                raise ValueError(f'无法唯一定位 {path} 中的 {key}')
            match = hits[0]
            parts = match['values'].split()
            values = [numeric(float(p), key) for p in parts]
            if key == 'linearPower':
                times = re.findall(rf'\btimePoints\s*\(\s*({NUM}(?:\s+{NUM})*)\s*\)\s*;', source)
                if len(times)!=1 or len(times[0].split())!=len(values) or len(values)<2:
                    raise ValueError('恒定线功率需要与 timePoints 一一对应')
            if len(set(values)) != 1 or key in result and result[key] != values[0]:
                raise ValueError(f'{key} 的时程或两侧边界不一致')
            result[key] = values[0]
            if key in changes:
                v = numeric(changes[key], key)
                a, b = match.span('values')
                source = source[:a] + ' '.join([repr(v)] * len(parts)) + source[b:]
        if changes:
            file.write_text(source)
    return result


def fingerprint(path, text):
    # Only the three registered parameter slots may differ in these executable dictionaries.
    text = re.sub(r'/\*.*?\*/|//[^\n]*', ' ', text, flags=re.S)
    if '#' in text or '\x00' in text:
        raise ValueError('计算器只接受已注册的 ASCII 字典')
    if path == 'constant/solverDict':
        text = re.sub(rf'(\blhgr\s*\()\s*({NUM}(?:\s+{NUM})*)\s*\)',
                      lambda m:m[1]+' '+' '.join(['POWER']*len(m[2].split()))+' )',text)
    if path == '0/T':
        for patch, entry in [('fuelOuter','alpha'), ('cladInner','alpha'), ('cladOuter','value')]:
            text = re.sub(rf'(\b{patch}\s*\{{[^{{}}]*?\b{entry}\s+uniform\s+){NUM}', r'\1PARAM', text)
    if path == 'constant/polyMesh/boundary':
        text = re.sub(r'\b(nFaces|startFace)\s+\d+', r'\1 COUNT', text)
    return hashlib.sha256(' '.join(text.split()).encode()).hexdigest()


def check_template(case):
    from .registered import FINGERPRINTS, SOLID_ROD, STEADY_HEAT_BALANCE
    families=[FINGERPRINTS,SOLID_ROD,STEADY_HEAT_BALANCE]
    for name in INPUTS:
        path = case / name
        if path.resolve() != case.resolve() / name or not path.is_file():
            raise ValueError(f'缺少独立输入 {name}')
        text = path.read_text(encoding='ascii')
        if name in FINGERPRINTS:
            signature=fingerprint(name,text)
            families=[family for family in families if signature==family[name]]
            if not families:
                raise ValueError(f'{name} 与已注册的稳态燃料棒模型不匹配')
        elif '#' in text or '\x00' in text:
            raise ValueError(f'网格文件格式不受支持 {name}')
    return bind(case)


def has_heat_flow(case,end):
    from .registered import SOLID_ROD
    name='constant/polyMesh/boundary'
    return (case/'rodDict').is_file() and (case/end/'Q').is_file() and fingerprint(name,(case/name).read_text())==SOLID_ROD[name]


def heat_flows(case,end,profile):
    """Full-circle powers for the registered solid, constant-k radial rod."""
    from export_case import foam,mesh_data,result_api
    mesh,_,_=mesh_data(case,end)
    vertices=mesh['points']
    fuel_vertices={i for row in profile if row['region']=='fuel' for i in mesh['cellEdges'][row['cell']]}
    radius=max(math.hypot(*vertices[i][:2]) for i in fuel_vertices)
    height=max(p[2] for p in vertices)-min(p[2] for p in vertices)
    # The reviewed wedge is centred on +x. Derive its opening from its rays.
    angles=[math.atan2(y,x) for x,y,_ in vertices if x or y]
    opening=max(angles)-min(angles)
    if not 0<opening<math.pi or height<=0 or radius<=0:
        raise ValueError('楔形网格无法换算为完整圆周')
    geometry=ast.literal_eval((case/'rodDict').read_text())
    scale=geometry['convertToMeters']
    nominal_radius=geometry['rOuterFuel'][0]*scale
    nominal_height=geometry['heightFuel'][0]*scale
    angle=math.radians(geometry['wedgeAngle'])
    if not (0<angle<math.pi and math.isclose(opening,angle,rel_tol=1e-6)
            and math.isclose(height,nominal_height,rel_tol=1e-6)
            and math.isclose(radius,nominal_radius*math.sqrt(math.sin(angle/2)/(angle/2)),rel_tol=1e-6)):
        raise ValueError('名义燃料尺寸与 rodMaker 扇区网格不一致')
    radius,height,opening=nominal_radius,nominal_height,angle
    source=result_api.read_field(case,'Q',time=end,scope=('cellZone','fuel'),include_volumes=True)
    if tuple(foam.parse_field(case/end/'Q').dimensions)!=(1,-1,-3,0,0,0,0):
        raise ValueError('Q 的量纲与体积热源不一致')
    generation=math.fsum(q*v for q,v in zip(source.values,source.volumes,strict=True))*math.tau/opening
    from .registered import STEADY_HEAT_BALANCE
    if fingerprint('constant/solverDict',(case/'constant/solverDict').read_text())==STEADY_HEAT_BALANCE['constant/solverDict']:
        from mandifuel_verify.case import Case
        from mandifuel_verify.checks import selected_log
        block,_=selected_log(Case(case,time=end))
        summaries=block.split('Boundary power summary:')
        if len(summaries)<2:raise ValueError('终态缺少原生边界功率摘要')
        rows=[dict(quantity='燃料产热',direction='体积热源为正',method='燃料区 ΣQ·V，折算全周',value=generation)]
        for patch,label,sign in [('fuelOuter','燃料向外传热',1),('cladInner','包壳内侧接收',-1),('cladOuter','包壳向外散热',1)]:
            hits=re.findall(rf'^\s*{patch}:\s*({NUM})\s*$',summaries[-1],re.M)
            if len(hits)!=1:raise ValueError(f'终态边界功率缺少唯一的 {patch} 记录')
            rows.append(dict(quantity=label,direction='沿 +r',method=f'终态 Boundary power summary · {patch}，按外法向符号换算全周',value=sign*float(hits[0])*math.tau/opening))
        return rows
    def slope(zone,transform):
        samples=[(transform(p['radius']),p['T']) for p in profile if p['region']==zone]
        xbar=math.fsum(x for x,_ in samples)/len(samples)
        tbar=math.fsum(t for _,t in samples)/len(samples)
        return math.fsum((x-xbar)*(t-tbar) for x,t in samples)/math.fsum((x-xbar)**2 for x,_ in samples)
    # These conductivities are fixed in the reviewed solver dictionary.
    fuel=-3.0*2*slope('fuel',lambda r:r*r)*radius**2*math.tau*height
    clad=-21.5*slope('cladding',math.log)*math.tau*height
    return [
        dict(quantity='燃料产热',direction='体积热源为正',method='燃料区 ΣQ·V，折算全周',value=generation),
        dict(quantity='燃料向外传热',direction='沿 +r 离开燃料',method='燃料区 T 对 r² 拟合，按外表面积积分',value=fuel),
        dict(quantity='包壳内侧接收',direction='沿 +r 进入包壳',method='包壳区 T 对 ln(r) 拟合，按内表面积积分',value=clad),
        dict(quantity='包壳向外散热',direction='沿 +r 离开包壳',method='同一对数拟合，按外表面积积分',value=clad),
    ]


def extract(case, folder, end, inputs):
    if str(REPO/'frontend') not in sys.path:
        sys.path.insert(0, str(REPO/'frontend'))
    from export_case import export_case, result_api, foam
    from mandifuel_run.case import save_json
    temperature=foam.parse_field(case/end/'T')
    if temperature.field_kind!='scalar' or temperature.object_name!='T' or tuple(temperature.dimensions)!=(0,0,0,1,0,0,0):
        raise ValueError('终态 T 必须是绝对温度量纲的标量场')
    points = []
    axial = []
    for zone in ('fuel', 'cladding'):
        f = result_api.read_field(case, 'T', time=end, scope=('cellZone', zone))
        if f.unit!='K' or not f.values:
            raise ValueError(f'{zone} 缺少以 K 为单位的终态温度')
        axial.extend(c[2] for c in f.coordinates)
        rows = sorted([(math.hypot(x,y), label, value) for (x,y,_), label, value in
                       zip(f.coordinates, f.labels, f.values, strict=True)])
        points += [dict(region=zone, radius=r, cell=label, T=value) for r, label, value in rows]
    if not math.isclose(min(axial),max(axial),rel_tol=1e-8,abs_tol=1e-12):
        raise ValueError('该适配器只支持同一轴向截面的径向单元')
    fuel = [r for r in points if r['region']=='fuel']
    peak = max(fuel, key=lambda r:r['T'])
    wall = result_api.read_field(case, 'T', time=end, scope=('patch','cladOuter'), owner_zone='cladding')
    if not wall.values or any(not math.isclose(v, inputs['outerTemperature'], rel_tol=6e-6) for v in wall.values):
        raise ValueError('终态外壁场与输入回读不一致')
    export_case(case, folder/'field.json', selectors=['T'], time=end, write_handoff=False)
    bundle = json.loads((folder/'field.json').read_text())
    bundle['caseRoot'] = 'case'
    save_json(folder/'field.json', bundle)
    summary = dict(time=end, fuelMaxTemperature=peak['T'], peakCell=peak['cell'], profile=points,
                   fieldFile=f'{end}/T', fieldSha256=digest(case/end/'T'), wallTemperature=wall.values[0])
    if has_heat_flow(case,end):
        summary.update(heatFlows=heat_flows(case,end,points),sourceFile=f'{end}/Q',sourceSha256=digest(case/end/'Q'))
    save_json(folder/'result.json', summary)
    return summary
