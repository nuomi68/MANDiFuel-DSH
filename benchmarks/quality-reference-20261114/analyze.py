#!/usr/bin/env python3
"""分开核对改编题与原版参考：同对象、同位置、同单位，保留边界误差与兼容失败。"""
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('model_review',REPO/'benchmarks/rag-modeling-20261114/evaluate.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
OLD=REPO/'runs/rag-modeling-pairs-20261114-03'
ROOT=REPO/'runs/quality-reference-20261114-01'
LIBRARY=Path('/home/lwz/offbeat')


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
def percent(actual,expected):return 100*(actual-expected)/abs(expected)
def literal_expected(path):return {key:float(value) for key,value in re.findall(r'^([A-Za-z0-9_]+Expected)=([-+0-9.eE]+)\s*$',path.read_text(),re.M)}
def boundary_vector(case,field,patch):
    d=api.foam.read_foam(case/field)['boundaryField'][patch]['value']
    payload=d[1:] if d[0]=='uniform' else d[4:-1]
    values=[float(x) for x in payload if x not in ('(',')')]
    components=3 if field=='D' else 6;assert len(values)%components==0
    return [math.fsum(values[i::components])/(len(values)//components) for i in range(components)]


def surface_sphere(case,patch):
    # 原版及本轮球壳为沿+x的对称小楔，内/外面中心都在x轴；径向=x。
    u=boundary_vector(case,'D',patch);s=boundary_vector(case,'sigma',patch)
    result={'u_r_m':u[0],'sigma_r_Pa':s[0],'sigma_t_Pa':(s[3]+s[5])/2}
    if (case/'epsilon').exists():
        eps=boundary_vector(case,'epsilon',patch);result.update(epsilon_r=eps[0],epsilon_t=(eps[3]+eps[5])/2)
    return result


def sphere_ref(a,b,E,nu,pi,po,r):
    A=(pi*a**3-po*b**3)/(b**3-a**3);B=(pi-po)*a**3*b**3/(b**3-a**3)
    u=(1-2*nu)*A*r/E+(1+nu)*B/(2*E*r*r)
    return {'u_r_m':u,'sigma_r_Pa':A-B/r**3,'sigma_t_Pa':A+B/(2*r**3),
            'epsilon_r':(1-2*nu)*A/E-(1+nu)*B/(E*r**3),'epsilon_t':u/r}


def main():
    v=load(OLD/'verification.json');taskbank={t['id']:t for t in load(OLD/'tasks.json')['tasks']}
    record={'modified_tasks':{},'original_cases':{},'new_review_solver_starts':3,'new_DSH_sessions':0,'scope':'改编题的解析参照与原始样例的固定答案分开；原版复核不计入此前六次会话成本。'};rows=[]
    def row(group,arm,case,quantity,unit,expected,actual,**detail):
        r={'group':group,'arm':arm,'case':case,'quantity':quantity,'unit':unit,'reference':expected,'actual':actual,'signed_error':actual-expected,'relative_error_percent':percent(actual,expected),**detail};rows.append(r);return r
    # G01：在实际最热单元中心使用同位置解析值，另列真正边界温度。
    req=taskbank['G01']['requirements'];q=req['q_W_m'];rf=req['rf_m'];rci=req['rci_m'];rco=req['rco_m'];kf=req['kf_W_mK'];kc=req['kc_W_mK'];h=req['h_W_m2K'];wall=req['wall_K']
    Tci=wall+q*math.log(rco/rci)/(2*math.pi*kc);Tfs=Tci+q/(2*math.pi*rf*h)
    record['modified_tasks']['G01']={'reference_kind':'同参数圆柱稳态导热解析式','formula':'Tci=Tw+q*ln(rco/rci)/(2*pi*kc); Tfs=Tci+q/(2*pi*rf*h); Tf(r)=Tfs+q/(4*pi*kf)*(1-r^2/rf^2)','arms':{}}
    for arm in ('bare','skill'):
        x=v['tasks']['G01'][arm];case=next(c for c in x['case_checks'] if c['radial_counts']==[40,12]);e=next(e for e in x['executions'] if e['id']==case['event_id']);mesh=load(OLD/'独立几何核对'/e['id']/'geometry.json');end=api.terminal(e);values=api.scalar_frame(end/'T',mesh['cells']);i=max(range(len(values)),key=lambda i:values[i]);r=math.hypot(*mesh['xyz'][i][:2]);reference=Tfs+q/(4*math.pi*kf)*(1-r*r/rf**2)
        selected=[row('modified',arm,'G01-fine','hottest_cell_temperature','K',reference,values[i],r_m=r)]
        data=api.foam.read_foam(end/'T')['boundaryField']
        for patch,expected in [('fuelOuter',Tfs),('cladInner',Tci),('cladOuter',wall)]:
            values_raw=data[patch]['value'];flat=values_raw[1:] if values_raw[0]=='uniform' else values_raw[4:-1];points=[float(t) for t in flat if t not in ('(',')')];actual=math.fsum(points)/len(points)
            selected.append(row('modified',arm,'G01-fine',patch+'_temperature','K',expected,actual))
        record['modified_tasks']['G01']['arms'][arm]={'rows':selected,'max_profile_error_K':case['max_reference_error_K'],'result_root':case['case_root']}
    # G02：分别列内部剖面与边界面，避免用一个漂亮的剖面指标覆盖边界误差。
    req=taskbank['G02']['requirements'];record['modified_tasks']['G02']={'reference_kind':'同参数球壳Lame解析解','arms':{}}
    for arm in ('bare','skill'):
        x=v['tasks']['G02'][arm];selected=[];chosen=[]
        for pi in req['pressures_inner_Pa']:
            if arm=='skill':case=next(c for c in x['case_checks'] if c['pressure_inner_Pa']==pi)
            else:case=next(c for c in reversed(x['case_checks']) if c['pressure_inner_Pa']==pi and Path(c['case_root']).name.startswith(('caseA_','caseB_')))
            chosen.append(case);event=next(e for e in x['executions'] if e['id']==case['event_id']);end=api.terminal(event)
            for patch,r in [('inner',req['a_m']),('outer',req['b_m'])]:
                actual=surface_sphere(end,patch);reference=sphere_ref(req['a_m'],req['b_m'],req['E_Pa'],req['nu'],pi,req['pressure_outer_Pa'],r)
                for name in ('u_r_m','sigma_r_Pa','sigma_t_Pa'):
                    selected.append(row('modified',arm,f'G02-{pi/1e6:g}MPa-{patch}',name,'m' if name=='u_r_m' else 'Pa',reference[name],actual[name]))
        record['modified_tasks']['G02']['arms'][arm]={'rows':selected,'radial_cells':[c['radial_rings'] for c in chosen],'max_cell_profile_error_percent':{name:100*max(c['reference_errors'][name]['relative_to_reference_max'] for c in chosen) for name in chosen[0]['reference_errors']}}
    # M01：既列要求的主算例，也列裸组额外加密结果，保留精度/成本差异。
    reference=load(OLD/'tasks.json')['organizer_only_references']['M01']['release_fraction_30000s'];record['modified_tasks']['M01']={'reference_kind':'恒D、零源、均匀初值、完美吸收球体扩散级数','arms':{}}
    for arm in ('bare','skill'):
        unique={c['case_root']:c for c in v['tasks']['M01'][arm]['case_checks'] if c['passed']};selected=[]
        for case in unique.values():
            selected.append(row('modified',arm,'M01-'+str(case['radial_rings'])+'cells','release_fraction','1',reference,case['release_fraction_actual'],radial_cells=case['radial_rings']))
        record['modified_tasks']['M01']['arms'][arm]={'rows':selected,'effective_D_m2_s':2.5e-14,'T_K':1650,'sourceCs_mol_m3_s':0}
    # 原版球核：只读之前已经正常完成的原参数参考运行，不新增求解。
    cs_source=LIBRARY/'Cases/Verification/trisoFpDiffusion/case_1a';cs_event=next(e for e in v['tasks']['M01']['bare']['executions'] if e['physical_last_time_s']==720000);before=Path(cs_event['evidence_dir'])/'before'
    matches={name:api.foam.equivalent(api.foam.read_foam(cs_source/name),api.foam.read_foam(before/name)) for name in ('constant/solverDict','0/T','system/blockMeshDict','system/fvSchemes','system/fvSolution','system/controlDict')};assert all(matches.values()),matches
    mesh=api.geometry(cs_event,ROOT/'independent-geometry');end=api.terminal(cs_event);Cs=api.scalar_frame(end/'Cs',mesh['cells']);C0=api.input_scalar(before,'constant/solverDict','elementTransportOptions/FpDiffusionOptions/intialFpConcentration/Cs');volume=math.fsum(mesh['volumes']);fraction=1-math.fsum(c*vol for c,vol in zip(Cs,mesh['volumes']))/(C0*volume)
    expected=literal_expected(cs_source/'Allrun')['CsExpected'];log=(Path(cs_event['evidence_dir'])/'solver.log').read_text();printed=float(re.findall(r'Fraction of Cs release:\s*([0-9.eE+-]+)',log)[-1])
    csrow=row('original','retained-bare-reference','case_1a','Cs_release_fraction','1',expected,fraction)
    record['original_cases']['case_1a']={'row':csrow,'printed_release_fraction':printed,'normal':cs_event['normal'],'event_id':cs_event['id'],'source_physical_inputs_match':matches,'reference_path':str(cs_source/'Allrun'),'reference_sha256':sha(cs_source/'Allrun'),'parameters':{'R_m':250e-6,'T_K':1473.15,'C0':C0,'end_s':720000,'deltaT_s':3600},'comparison_limit':'这是保留的原版参考运行，不是本次Skill新题的0.2460665与0.4673直接相减。'}
    # 原版球壳：原样卡失败、区间外尾点兼容修复、固定物理参数的80单元诊断分别保留。
    sphere_source=LIBRARY/'Cases/Verification/trisoModulesTest/hollowsphere_1D';expected=literal_expected(sphere_source/'Allrun');events=api.base.execution(ROOT/'workspace');shell_rows=[]
    names={'innerHoopStressExpected':('inner','sigma_t_Pa','Pa'),'innerRadialStressExpected':('inner','sigma_r_Pa','Pa'),'innerHoopStrainExpected':('inner','epsilon_t','1'),'innerRadialStrainExpected':('inner','epsilon_r','1'),'innerDispExpected':('inner','u_r_m','m'),'outerHoopStressExpected':('outer','sigma_t_Pa','Pa'),'outerRadialStressExpected':('outer','sigma_r_Pa','Pa'),'outerHoopStrainExpected':('outer','epsilon_t','1'),'outerRadialStrainExpected':('outer','epsilon_r','1'),'outerDispExpected':('outer','u_r_m','m')}
    for event in events:
        if not event['normal']:continue
        label='original20-compatibility-repaired' if Path(event['case_root']).name=='hollowsphere-a2' else 'refined80-same-physics';end=api.terminal(event);surfaces={p:surface_sphere(end,p) for p in ('inner','outer')}
        selected=[]
        for key,(patch,name,unit) in names.items():selected.append(row('original',label,'hollowsphere_1D-'+patch,name,unit,expected[key],surfaces[patch][name]))
        shell_rows.append({'attempt':label,'event_id':event['id'],'normal':True,'rows':selected})
    assert len(shell_rows)==2
    record['original_cases']['hollowsphere_1D']={'original_unchanged_attempt_normal':False,'unchanged_attempt_error':'时变零功率表末点10s与endTime相等，查询下一标记越界；未把已写出10s当正常完成。','reference_path':str(sphere_source/'Allrun'),'reference_sha256':sha(sphere_source/'Allrun'),'parameters':{'a_m':200e-6,'b_m':300e-6,'E_Pa':10e9,'nu':.3,'pi_Pa':100e6,'po_Pa':200e6,'end_s':10},'attempts':shell_rows,'compatibility_patch':load(ROOT/'compatibility-repair.json'),'refinement_patch':load(ROOT/'mesh-refinement.json'),'comparison_limit':'原版未声明统一通过公差。仅报告各物理量误差；兼容修复算例与不改卡复现分开。'}
    record['original_cases']['case1_solved']={'reference_kind':'本地教程有工况数据与MATLAB grader说明，没有本地公开固定温度答案表。','reference_path':str(LIBRARY/'Cases/testCases/exerciseOFFBEAT/case1_solved/README.md'),'comparison_limit':'本次G01改变了尺寸、功率、h、壁温等，采用同参数解析式核对；未宣称原版全年瞬态官方答案已复现。'}
    # 旧实验和会话保持原样；本轮新增3次原版/加密尝试单列。
    old_delivery=load(OLD/'交付核对.json');assert sha(OLD/'结果汇总.md')==old_delivery['结果报告SHA256']
    traces=load(OLD/'中文单行轨迹/翻译清单.json');assert all(sha(OLD/name)==digest for name,digest in traces['源文件SHA256'].items())
    record['prior_experiment_unchanged']=True
    api.save(ROOT/'numeric-reference-check.json',record)
    headers=['group','arm','case','quantity','unit','reference','actual','signed_error','relative_error_percent']
    with (ROOT/'数值对标.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=headers,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    print(json.dumps({'original_Cs':csrow,'original_sphere_max_errors_percent':{a['attempt']:{name:max(abs(x['relative_error_percent']) for x in a['rows'] if x['quantity']==name) for name in ('u_r_m','sigma_t_Pa','epsilon_r')} for a in shell_rows},'modified_rows':sum(x['group']=='modified' for x in rows),'new_solver_starts':3,'prior_experiment_unchanged':True},ensure_ascii=False))

if __name__=='__main__':main()
