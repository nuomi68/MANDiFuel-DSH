"""Independent arithmetic and explicitly scoped physical comparisons.

Verified means the named check passed its published criterion, never that an
entire simulation is validated. Inapplicable and missing evidence stay distinct.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import re

from . import VERSION,engine_revision
from .case import Case, dot, vector_length
from .inputs import Unavailable, get, scalar, word, zero_vector

TEMPERATURE = (0,0,0,1,0,0,0)
POWER_DENSITY = (1,-1,-3,0,0,0,0)
HEAT_FLUX = (1,0,-3,0,0,0,0)
CONDUCTIVITY = (1,1,-3,-1,0,0,0)
GRAD_T = (0,-1,0,1,0,0,0)
STRESS = (1,-1,-2,0,0,0,0)
DISPLACEMENT = (0,1,0,0,0,0,0)
CONCENTRATION = (0,-3,0,0,1,0,0)
DIFFUSIVITY = (0,2,-1,0,0,0,0)


class NotApplicable(Unavailable): pass


def stable_id(case, key): return 'ev-' + hashlib.sha256((case+'\0'+key).encode()).hexdigest()[:20]


class Report:
    def __init__(self, case):
        self.case = case; self.claims = []; self.checks = []

    def claim(self, key, title, value, unit, operation, *, selection=None, samples=None, note=''):
        try:
            control=self.case.inputs('system/controlDict')
            time_unit={'seconds':'s','days':'d'}.get(word(control,'userTime','type')) if 'userTime' in control else 's'
        except Unavailable:time_unit=None
        item = {'id':stable_id(self.case.relative,key), 'key':key, 'title':title, 'value':value, 'unit':unit,
                'status':'computed', 'caseRoot':self.case.relative, 'time':self.case.time,'timeUnit':time_unit,
                'definition':{'operation':operation, 'selection':selection or '整个计算网格', 'unit':unit},
                'sources':[], 'checks':[], 'note':note}
        if samples is not None: item['samples'] = samples
        self.claims.append(item)
        return item

    def check(self, key, title, status, *, reason='', metric=None, tolerance=None, formula='', scope='', assumptions=None, related=()):
        item = {'id':stable_id(self.case.relative,'check.'+key), 'key':key, 'title':title, 'status':status,
                'reason':reason, 'formula':formula, 'scope':scope, 'assumptions':assumptions or []}
        if metric is not None: item['metric'] = metric
        if tolerance is not None: item['tolerance'] = tolerance
        self.checks.append(item)
        for claim in related: claim['checks'].append(item['id'])
        return item


def selected_log(c):
    receipt = c.sources.json(c.root/'.mandifuel-execution.json') if c.has('.mandifuel-execution.json') else {}
    candidates = []
    if isinstance(receipt.get('log'), str):
        try:
            path = c.sources.path(receipt['log'] if receipt['log'].startswith('/') else c.root/receipt['log'])
            if path.is_relative_to(c.root) and path.is_file(): candidates.append(path)
        except (ValueError, OSError): pass
    candidates += [c.root/name for name in ['log.offbeat','log.mandifuel-runner'] if c.has(name)]
    for path in dict.fromkeys(candidates):
        text = c.sources.text(path, '原生求解日志')
        blocks = list(re.finditer(r'^Time\s*=\s*([0-9.eE+\-]+).*$', text, re.M))
        selected = [m for m in blocks if Decimal(m.group(1)) == Decimal(c.time)]
        if selected:
            match = selected[-1]; end = next((m.start() for m in blocks if m.start() > match.start()), len(text))
            return text[match.end():end], str(path.relative_to(c.sources.workspace))
    raise Unavailable('没有与当前保存时刻精确匹配的原生求解日志')


def execution(c, r):
    if not c.has('.mandifuel-execution.json'): raise Unavailable('没有原生执行回执；仅有场文件不能证明正常求解完成')
    receipt = c.sources.json(c.root/'.mandifuel-execution.json')
    control = c.inputs('system/controlDict')
    end = scalar(control, 'endTime')
    ok = receipt.get('status') == 'completed' and type(receipt.get('exit_code')) is int and receipt.get('exit_code') == 0 and receipt.get('terminal_marker') is True
    ok = ok and Decimal(str(receipt.get('final_time', '-1'))) == Decimal(str(end)) and Decimal(c.time) == Decimal(str(end))
    try:
        block, _ = selected_log(c)
        terminal = bool(re.search(r'^\s*(?:end|End)\s*$', block, re.M))
    except Unavailable: terminal = False
    ok = ok and terminal
    q = r.claim('execution.final_time', '当前已保存终点', float(c.time), '模型时间', '数值目录、controlDict.endTime 与执行回执交叉核对',
                note='执行完成性与各物理量的数值校核分别评价。')
    q['unit']=q['timeUnit'] or '模型时间（单位未核实）';q['definition']['unit']=q['unit']
    r.check('execution', '原生执行完成性', 'verified' if ok else 'not_verified',
            reason='' if ok else '回执、退出码、结束标记、当前保存终点与请求终点未全部一致；未替原生回执改写成功状态。',
            scope='仅核对保存的执行证据', related=[q])
    r.check('execution.inputs','当前输入与执行时版本的绑定','not_verified',reason='当前原生回执没有本核查器可验证的运行时输入指纹协议。此处 SHA-256 记录此次核查读取的版本，不补写历史输入未变的证明。',scope='历史输入版本证明与当前保存输入/场的一致性比较分别评价')


def time_scheme(c):
    schemes=get(c.inputs('system/fvSchemes'),'ddtSchemes')
    if set(schemes)-{'default'}:raise Unavailable('存在逐变量时间离散覆盖或未解析条目，需先核实对应场的时间离散')
    tokens=get(schemes,'default')
    if not isinstance(tokens,list) or not tokens:raise Unavailable('时间离散未明确给出')
    return tokens[0]


def heat(c, r):
    if not c.has(f'{c.time}/T'): raise NotApplicable('当前没有温度保存场')
    solver = c.inputs('constant/solverDict')
    if word(solver, 'thermalSolver') != 'solidConduction': raise NotApplicable('当前稳态热平衡核查仅覆盖 solidConduction')
    if time_scheme(c) != 'steadyState':
        raise NotApplicable('瞬态需要计入储热，本项稳态平衡不适用')
    c.field('T', dimensions=TEMPERATURE, kind='scalar')
    q = c.field('Q', dimensions=POWER_DENSITY, kind='scalar')
    source = math.fsum(row[0]*v for row,v in zip(q,c.geometry['volumes']))
    source_claim = r.claim('heat.source', '体积热源积分', source, 'W', 'Σ Q_cell V_cell',
                            selection='全部真实单元及当前时刻绑定体积', note='为计算域功率，不擅自换算成整棒或整球。')
    vector = c.has(f'{c.time}/heatFluxVec')
    if vector: c.field('heatFluxVec', dimensions=HEAT_FLUX, kind='vector')
    else:
        c.field('k', dimensions=CONDUCTIVITY, kind='scalar'); c.field('gradT', dimensions=GRAD_T, kind='vector')
    flows = []; related = [source_claim]
    for name, patch in c.geometry['patches'].items():
        if not patch['count'] or patch['type'] in {'wedge','empty','symmetry','symmetryPlane','cyclic','cyclicAMI','processor'}: continue
        if vector: flux = c.boundary('heatFluxVec', name, dimensions=HEAT_FLUX)
        else:
            k = c.boundary('k', name, dimensions=CONDUCTIVITY); grad = c.boundary('gradT', name, dimensions=GRAD_T)
            flux = [tuple(-a[0]*v for v in b) for a,b in zip(k,grad)]
        value = math.fsum(dot(row,c.geometry['areas'][face]) for row,face in zip(flux,patch['faces']))
        flows.append(value)
        related.append(r.claim('heat.patch.'+name, name+' 外法向导热功率', value, 'W',
                       'Σ q_face · S_face；q = heatFluxVec' if vector else 'Σ (-k_face gradT_face) · S_face',
                       selection={'patch':name,'faces':patch['count']}, note='正号为离开该材料计算域；内侧边界的流入通常为负。'))
    if not flows: raise Unavailable('没有可积分的真实边界热流')
    outward = math.fsum(flows); scale = max(abs(source),math.fsum(map(abs,flows))/2,1e-30)
    residual = abs(outward-source)/scale
    net = r.claim('heat.net', '全域边界净导热功率', outward, 'W', 'Σ 各非对称/非空边界的外法向导热功率',
                  note='材料接口两侧均积分；内部交换应相互抵消。')
    related.append(net)
    r.check('heat.balance', '保存热流场积分的稳态平衡', 'verified' if residual <= .01 else 'failed',
            metric={'relativeResidual':residual,'imbalance_W':outward-source}, tolerance={'relativeResidual':.01},
            formula='|Σ_boundary q·S − Σ_cells QV| / max(|Σ QV|, Σ|patchPower|/2, 1e−30)',
            scope='保存时刻、实际网格计算域的稳态导热平衡；不是全局仿真精度认证',
            assumptions=['solidConduction','ddtSchemes.default = steadyState','量纲由原场逐项检查','未包含的额外体积能量源需要另行核验'], related=related)
    try:
        block,_=selected_log(c)
        summaries=re.findall(r'Boundary power summary:\s*\n((?:[ \t]+[^\n]+\n)+)',block)
        if not summaries:raise Unavailable('当前时刻没有原生 Boundary power summary')
        powers={name:float(value) for name,value in re.findall(r'^\s*([^\s:]+):\s*([0-9.eE+\-]+)\s*$',summaries[-1],re.M)}
        needed=[name for name,p in c.geometry['patches'].items() if p['count'] and p['type'] not in {'wedge','empty','symmetry','symmetryPlane','cyclic','cyclicAMI','processor'}]
        if set(needed)-powers.keys():raise Unavailable('原生热流摘要未覆盖全部物理边界')
        native_net=math.fsum(powers[name] for name in needed)
        q=r.claim('heat.native_net','原生边界摘要净功率',native_net,'W','Σ 原生日志各边界的外法向导热功率',note='原生有限体积热流与后处理梯度热流分别核对，两者不强行视为同一离散量。')
        error=abs(native_net-source)/max(abs(source),math.fsum(abs(powers[n]) for n in needed)/2,1e-30)
        r.check('heat.native_balance','原生边界功率与原场体积源核对','verified' if error<=.01 else 'failed',metric={'relativeResidual':error,'patchPowers_W':powers},tolerance={'relativeResidual':.01},formula='|Σ BoundaryPower_native − Σ QV| / max(|Σ QV|, Σ|patchPower|/2, 1e−30)',scope='原生边界功率摘要与独立体积积分的一致性；保存热流矢量的积分残差另列',related=[source_claim,q])
    except (Unavailable,OSError,ValueError) as error:r.check('heat.native_balance','原生边界功率与原场体积源核对','not_verified',reason=str(error))


def spherical_surfaces(c):
    g = c.geometry; surfaces = []
    for name,p in g['patches'].items():
        if not p['count'] or p['type'] in {'wedge','empty','symmetry','symmetryPlane'}: continue
        ids = {i for f in p['faces'] for i in g['faces'][f]}
        radii = [vector_length(g['points'][i]) for i in ids]; radius = math.fsum(radii)/len(radii)
        if not radius or max(radii)-min(radii) > radius*1e-6: raise NotApplicable('边界不是以原点为球心的等半径球面')
        for f in p['faces']:
            a,b = g['areas'][f],g['faceCentres'][f]
            if abs(dot(a,b))/(vector_length(a)*vector_length(b)) < .995: raise NotApplicable('边界法向不满足球对称几何')
        surfaces.append((radius,name))
    surfaces.sort()
    if not surfaces or len(surfaces)>2: raise NotApplicable('当前只核对完整球核或单层球壳的球对称几何')
    return surfaces


def lame(r, a, b, pi, po, E, nu):
    A = (pi*a**3-po*b**3)/(b**3-a**3)
    B = (pi-po)*a**3*b**3/(b**3-a**3)
    return ((1-2*nu)*A*r+(1+nu)*B/(2*r*r))/E, A-B/r**3, A+B/(2*r**3)


def sphere(c, r):
    if not c.has(f'{c.time}/D') or not c.has(f'{c.time}/sigma'): raise NotApplicable('没有位移和应力保存场')
    solver = c.inputs('constant/solverDict')
    if word(solver, 'mechanicsSolver') != 'smallStrain': raise NotApplicable('本项仅适用小应变线弹性')
    inertia=get(c.inputs('system/fvSchemes'),'d2dt2Schemes')
    if set(inertia)!={'default'}:raise Unavailable('力学二阶时间离散存在未核实的覆盖条目')
    if word(inertia,'default')!='steadyState':raise NotApplicable('包含力学惯性项时不能作为静态 Lamé 问题核验')
    try:
        if word(solver,'rheologyOptions','thermalExpansion')!='off':raise NotApplicable('热应变未关闭，不能套用纯压力 Lamé 解')
    except NotApplicable:raise
    except Unavailable:pass
    surfaces = spherical_surfaces(c)
    if len(surfaces) != 2: raise NotApplicable('Lamé 对照需要两个真实球面边界')
    (a,inner),(b,outer) = surfaces
    if any(not p.startswith('constant/') for k,p in c.geometry['binding'].items() if k in {'points','faces','owner','neighbour'}):
        raise NotApplicable('本项 Lamé 对照要求固定参考网格')
    if c.has('system/fvOptions') or c.has('constant/fvOptions'): raise Unavailable('存在附加源项，需要独立确认力学体力或初始应力')
    zones = c.geometry['zones']
    active = [(name,ids) for name,ids in zones.items() if ids]
    if len(active) != 1 or set(active[0][1]) != set(range(len(c.geometry['volumes']))):
        raise NotApplicable('当前解析对照只覆盖单一均匀材料球壳')
    materials = get(solver, 'materials'); name = active[0][0]
    matching = [v for key,v in materials.items() if not key.startswith('_') and re.fullmatch(key,name)]
    if len(matching) != 1: raise Unavailable('材料区不能唯一对应材料输入')
    material = matching[0]
    if word(material,'material') != 'constant' or word(material,'rheologyModel') != 'elasticity':
        raise NotApplicable('材料不是明确的常物性弹性模型')
    E,nu = scalar(material,'E',dimensions=STRESS),scalar(material,'nu',dimensions=(0,)*7)
    if E<=0 or not -1<nu<.5: raise Unavailable('弹性参数不在稳定范围')
    try: thermal_off = word(solver,'rheologyOptions','thermalExpansion') == 'off'
    except Unavailable: thermal_off = scalar(material,'alpha') == 0
    if not thermal_off: raise NotApplicable('热应变未关闭，不能套用纯压力 Lamé 解')
    initial = c.inputs('0/D')
    if not zero_vector(initial,'internalField'): raise Unavailable('初始位移不是明确的零场')
    pressure = []
    for patch in [inner,outer]:
        if word(initial,'boundaryField',patch,'type') != 'tractionDisplacement' or not zero_vector(initial,'boundaryField',patch,'traction'):
            raise NotApplicable('需要纯均匀压力边界、零附加切向牵引')
        pressure.append(scalar(initial,'boundaryField',patch,'pressure'))
    D = c.field('D', dimensions=DISPLACEMENT, kind='vector')
    sigma = c.field('sigma', dimensions=STRESS, kind='symmTensor')
    rows = []
    symmetry=[]
    for i,(point,d,s) in enumerate(zip(c.geometry['centres'],D,sigma)):
        radius = vector_length(point); n = [v/radius for v in point]
        xx,xy,xz,yy,yz,zz = s
        rr = xx*n[0]**2+yy*n[1]**2+zz*n[2]**2+2*(xy*n[0]*n[1]+xz*n[0]*n[2]+yz*n[1]*n[2])
        numerical = (dot(d,n), rr, (xx+yy+zz-rr)/2)
        matrix=((xx,xy,xz),(xy,yy,yz),(xz,yz,zz));tt=numerical[2]
        remainder=math.sqrt(sum((matrix[i][j]-rr*n[i]*n[j]-tt*((1 if i==j else 0)-n[i]*n[j]))**2 for i in range(3) for j in range(3)))
        symmetry.append(remainder)
        reference = lame(radius,a,b,*pressure,E,nu)
        rows.append({'cell':i,'radius_m':radius,'numerical':numerical,'reference':reference})
    symmetric_error=max(symmetry)/max(max(abs(v) for row in sigma for v in row),1e-30)
    symmetry_check=r.check('sphere.symmetry','保存应力张量的球对称性','verified' if symmetric_error<=.02 else 'failed',metric={'normalizedTensorRemainder':symmetric_error},tolerance={'normalizedTensorRemainder':.02},formula='||σ−σ_rr e_r⊗e_r−σ_θ(I−e_r⊗e_r)|| / max|σ_ij|',scope='检查径向剪切与两个切向分量的非对称部分，避免均值掩盖非球对称应力')
    for k,key,title,unit in [(0,'displacement','径向位移 u_r','m'),(1,'radial_stress','径向应力 σ_rr','Pa'),(2,'hoop_stress','平均切向应力 σ_θ','Pa')]:
        worst = max(rows,key=lambda row:abs(row['numerical'][k]-row['reference'][k]))
        scale = max((abs(row['reference'][k]) for row in rows), default=0)
        absolute = abs(worst['numerical'][k]-worst['reference'][k]); error = absolute/max(scale,1e-30)
        extreme = max(rows,key=lambda row:abs(row['numerical'][k]))
        samples = [{**row,'numerical':row['numerical'][k],'reference':row['reference'][k]} for row in (rows[0],rows[len(rows)//2],rows[-1],worst)]
        claim = r.claim('sphere.'+key, title+'（绝对值最大单元，保留符号）', extreme['numerical'][k], unit,
                        'u_r=D·e_r；σ_rr=e_rᵀσe_r；σ_θ=(tr(σ)−σ_rr)/2',
                        selection={'cellZone':name,'component':key,'samples':len(rows),'location':'真实单元中心'}, samples=samples,
                        note='平均切向分量的球对称解析对照；单元值不冒充边界面值。')
        claim['checks'].append(symmetry_check['id'])
        r.check('sphere.'+key, title+' 与 Lamé 解析解对照', 'verified' if error<=.02 else 'failed',
                metric={'normalizedMaxError':error,'maxAbsoluteError':absolute,'worstCell':worst['cell']},
                tolerance={'normalizedMaxError':.02}, formula='A=(p_i a³−p_o b³)/(b³−a³); B=(p_i−p_o)a³b³/(b³−a³); σ_rr=A−B/r³; σ_θ=A+B/(2r³); u_r=[(1−2ν)Ar+(1+ν)B/(2r²)]/E',
                scope='仅当前保存帧真实单元中心；误差以解析剖面最大绝对值归一化',
                assumptions=[{'a_m':a,'b_m':b,'innerPressure_Pa':pressure[0],'outerPressure_Pa':pressure[1],'E_Pa':E,'nu':nu},'原点球心、均匀材料、固定参考网格、线弹性、无热应变'],related=[claim])


def sphere_release(tau):
    if tau <= 0: return 0.
    if tau < .025:
        # The omitted image terms are exponentially small here; avoid slow,
        # cancellation-prone summation at very early times.
        return 6*math.sqrt(tau/math.pi)-3*tau
    return 1-6/math.pi**2*math.fsum(math.exp(-n*n*math.pi**2*tau)/(n*n) for n in range(1,501))


def cesium(c, r):
    if not c.has(f'{c.time}/Cs'): raise NotApplicable('当前没有铯浓度保存场')
    values = c.field('Cs', dimensions=CONCENTRATION, kind='scalar')
    inventory = math.fsum(row[0]*v for row,v in zip(values,c.geometry['volumes']))
    current = r.claim('cesium.inventory', '当前计算域铯库存', inventory, 'mol', 'Σ Cs_cell V_cell',
                      selection='所有材料区的真实单元与保存时刻绑定体积',
                      note='库存采用体积积分；未将核芯库存下降当作多层结构的对外释放。')
    block, log_path = selected_log(c)
    labels = {'initial':'Initial Cs amount','production':'Production of Cs','released':'Released Cs amount','remained':'Remained Cs amount','fraction':'Fraction of Cs release'}
    native = {}
    for key,label in labels.items():
        matches = re.findall(re.escape(label)+r':\s*([0-9.eE+\-]+)', block)
        if not matches: raise Unavailable('当前时刻日志缺少 '+label)
        native[key] = float(matches[-1])
    source = c.field('sourceCs', dimensions=(0,-3,-1,0,1,0,0), kind='scalar')
    if any(row[0] != 0 for row in source) or native['production'] != 0:
        raise NotApplicable('非零生成源需要完整累计源项，本版不把瞬时源当作累计生产量')
    n0 = native['initial']
    if not n0>0: raise Unavailable('初始库存不是正数，释放分数未定义')
    fraction = 1-inventory/n0
    release = r.claim('cesium.release_fraction', '原场库存法计算的对外释放分数', fraction, '1', 'F = 1 − Σ(Cs V) / N0_native',
                       note='N0 来自相同时刻原生日志；初始库存的独立复算另列核查，未声称独立通量积分。')
    released = r.claim('cesium.native_released', '原生日志累计外释量', native['released'], 'mol', '读取精确匹配保存时刻的最后一组 Fission products transport 记录',
                        selection={'file':log_path,'time':c.time}, note='这是求解器记录值，不是本核查程序独立积分的边界通量。')
    scale=n0/max(math.fsum(c.geometry['volumes']),1e-300)
    minimum=min(row[0] for row in values)
    bounds=minimum>=-scale*1e-7 and -1e-7<=fraction<=1+1e-7
    r.check('cesium.bounds','零源库存与释放分数的数值范围','verified' if bounds else 'failed',metric={'minimumCs_mol_m3':minimum,'fraction':fraction},tolerance={'relativeInitialConcentration':1e-7,'fractionSlack':1e-7},scope='允许声明范围内的微小舍入噪声；超出范围不以库存相消掩盖',related=[current,release])
    residual = abs(inventory+native['released']-n0)/n0
    agreement = max(abs(inventory-native['remained'])/n0,abs(fraction-native['fraction']))
    r.check('cesium.balance','原场库存与原生日志外释量核对','verified' if max(residual,agreement)<=.005 else 'failed',
            metric={'relativeInventoryReleaseResidual':residual,'maxNormalizedLogDifference':agreement,'native':native},
            tolerance={'relativeInventoryReleaseResidual':.005,'maxNormalizedLogDifference':.005},
            formula='|Σ Cs V + N_released_native − N0_native| / N0_native；同时核对日志剩余量及释放分数',
            scope='零源、当前保存帧的原场/原生日志一致性；不等同于独立累计边界通量积分',
            assumptions=['最新 sourceCs 全域为零','原生日志累计 Production of Cs = 0','计算域范围不换算'],related=[current,release,released])
    # Establish the initial inventory from a real initial field or explicit
    # per-zone initial values; never silently assume unprovided regions are zero.
    try:
        if any(not p.startswith('constant/') for k,p in c.geometry['binding'].items() if k in {'points','faces','owner','neighbour'}):
            raise Unavailable('移动网格的初始体积需要单独读取，当前未独立复算初始库存')
        if c.has('0/Cs'):
            initial = c.field('Cs',time='0',dimensions=CONCENTRATION,kind='scalar')
            initial_values = [row[0] for row in initial]
        else:
            materials = get(c.inputs('constant/solverDict'),'materials'); initial_values = [None]*len(values)
            for zone,ids in c.geometry['zones'].items():
                if not ids: continue
                matching = [v for key,v in materials.items() if not key.startswith('_') and re.fullmatch(key,zone)]
                if len(matching)!=1: raise Unavailable('初始浓度材料映射不唯一')
                concentration = scalar(matching[0],'initialCsConcentration')
                for i in ids:
                    if initial_values[i] is not None: raise Unavailable('初始库存材料区域重叠')
                    initial_values[i] = concentration
            if any(v is None for v in initial_values): raise Unavailable('初始浓度未明确覆盖全部材料区')
        initial_inventory = math.fsum(a*v for a,v in zip(initial_values,c.geometry['volumes']))
        initial_error = abs(initial_inventory-n0)/n0
        r.check('cesium.initial','初始库存独立复算','verified' if initial_error<=.005 else 'failed',metric={'inputInventory_mol':initial_inventory,'nativeInventory_mol':n0,'relativeDifference':initial_error},tolerance={'relativeDifference':.005},formula='Σ C_initial,cell V_cell 对照原生日志 N0',scope='固定初始网格',related=[release])
    except (Unavailable,OSError,ValueError) as error:
        initial_values = None
        r.check('cesium.initial','初始库存独立复算','not_verified',reason=str(error),related=[release])
    try:
        if time_scheme(c) not in {'Euler','backward','CrankNicolson'}:raise NotApplicable('需要明确的物理时间瞬态扩散离散，稳态或局部伪时间不适用本项解析对照')
        if any(not p.startswith('constant/') for k,p in c.geometry['binding'].items() if k in {'points','faces','owner','neighbour'}):raise NotApplicable('移动网格不适用本项固定球域解析解')
        surfaces = spherical_surfaces(c)
        if len(surfaces)!=1: raise NotApplicable('解析释放级数只适用于无内孔、无涂层的均匀球核')
        radius,outer = surfaces[0]
        if min(map(vector_length,c.geometry['points'])) > radius*1e-6: raise NotApplicable('网格不包含球心')
        if initial_values is None or min(initial_values)<=0 or max(initial_values)-min(initial_values)>max(initial_values)*1e-10:
            raise NotApplicable('无法证明整球均匀非零初始浓度')
        diff = [row[0] for row in c.field('diffCs',dimensions=DIFFUSIVITY,kind='scalar')]
        if min(diff)<=0 or max(diff)-min(diff)>max(diff)*1e-10: raise NotApplicable('扩散系数并非全域均匀正数')
        materials = get(c.inputs('constant/solverDict'),'materials')
        active = [name for name,ids in c.geometry['zones'].items() if ids]
        if len(active)!=1: raise NotApplicable('多材料球不适用均匀球扩散解析解')
        matching = [v for key,v in materials.items() if not key.startswith('_') and re.fullmatch(key,active[0])]
        law = get(matching[0],'fissionProductsTransport','Cs')
        if scalar(law,'q1')!=0 or scalar(law,'q2')!=0 or abs(scalar(law,'d1')+scalar(law,'d2')-diff[0])>diff[0]*1e-8:
            raise NotApplicable('不能证明整个历程为同一常扩散系数')
        initial_time = c.inputs('system/controlDict')
        try: unit = word(initial_time,'userTime','type')
        except Unavailable:
            if 'userTime' in initial_time: raise
            unit = 'seconds'
        factor = {'seconds':1,'days':86400}.get(unit)
        if factor is None: raise Unavailable('模型时间单位未核实')
        if scalar(initial_time,'startTime') != 0: raise NotApplicable('续算的扩散年龄需要另行定义')
        bc = c.inputs(f'{c.time}/Cs')
        if word(bc,'boundaryField',outer,'type')!='fixedValue' or scalar(bc,'boundaryField',outer,'value')!=0:
            raise NotApplicable('外表面不是明确的零浓度吸收边界')
        reference = sphere_release(diff[0]*float(c.time)*factor/radius**2)
        difference = abs(fraction-reference)
        r.check('cesium.analytic','裸球恒定扩散系数解析对照','verified' if difference<=.005 else 'failed',
                metric={'fieldFraction':fraction,'analyticFraction':reference,'absoluteDifference':difference,'radius_m':radius,'D_m2_s':diff[0]},
                tolerance={'absoluteDifference':.005},formula='F(t)=1−6/π² Σ[n=1..∞] exp(−n²π²Dt/R²)/n²',
                scope='仅此保存时刻的整域释放分数；不代替全历史或网格收敛验证',
                assumptions=['裸球、球心包含在网格内','均匀初值、恒定均匀 D、零生成源','外表面 Cs=0','模型时间按明确单位转换为秒'],related=[release])
    except NotApplicable as error: r.check('cesium.analytic','裸球恒定扩散系数解析对照','not_applicable',reason=str(error),related=[release])
    except (Unavailable,OSError,ValueError,IndexError) as error: r.check('cesium.analytic','裸球恒定扩散系数解析对照','not_verified',reason=str(error),related=[release])


CHECKS = {'execution':execution,'heat':heat,'sphere':sphere,'cesium':cesium}


def verify_case(case, *, workspace=None, time='latest', checks=None):
    requested = list(CHECKS) if checks is None else list(checks)
    if not requested or set(requested)-CHECKS.keys(): raise ValueError('未知核查类型')
    c = Case(case,workspace,time); report = Report(c)
    for key in requested:
        first = len(report.claims)
        try: CHECKS[key](c,report)
        except NotApplicable as error: report.check(key,{'execution':'执行完成性','heat':'稳态导热核查','sphere':'球壳解析对照','cesium':'铯库存与外释核查'}[key],'not_applicable',reason=str(error))
        except (Unavailable,OSError,ValueError,KeyError,IndexError,ArithmeticError) as error: report.check(key,{'execution':'执行完成性','heat':'稳态导热核查','sphere':'球壳解析对照','cesium':'铯库存与外释核查'}[key],'not_verified',reason=str(error))
        ids = [source['id'] for source in c.sources.records.values()]
        for claim in report.claims[first:]: claim['sources'] = ids
    report.check('discretization','网格与时间步离散误差','not_verified',reason='尚未提供物理输入一致且明确关联的加密计算对；不会根据目录名称自动认定收敛。')
    unchanged = c.sources.unchanged()
    if not unchanged:
        for check in report.checks: check.update(status='stale',reason='核查期间原始文件发生变化，需要重新核查')
        for claim in report.claims: claim['status'] = 'stale'
    body = {'schema':'mandifuel.evidence/v1','engine':VERSION,'engineRevision':engine_revision(),'caseRoot':c.relative,'time':c.time,
            'state':'ready' if unchanged else 'stale','claims':report.claims,'checks':report.checks,
            'sources':list(c.sources.records.values()),
            'limits':['核查结论仅适用于其明确范围和容差','未核验不等于通过；不适用不计作失败','未自动证明跨网格收敛或独立累计边界通量','核查只读取保存数据，不执行或修改求解任务']}
    body['revision'] = hashlib.sha256(json.dumps(body,sort_keys=True,allow_nan=False).encode()).hexdigest()[:20]
    body['generatedAt'] = datetime.now(timezone.utc).isoformat()
    return body
