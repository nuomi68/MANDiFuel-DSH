#!/usr/bin/env python3
"""基于冻结物理要求、启动快照和原生场核对无预置输入任务；不启动OFFBEAT。"""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'benchmarks/candidate-pairs'))
import evaluate_suite as base
from generalization_checks import artifacts
from new_case_checks import tables
foam=base.foam


def load(p,default=None):return json.loads(p.read_text()) if p.is_file() else default
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def check(out,name,passed,**evidence):out.append({'check':name,'passed':bool(passed),**evidence})
def number(v):return float(v[-1])


def raw_list(path):
    tokens=foam.tokens(path.read_text());start=tokens.index('FoamFile');end=foam.matching(tokens,start+1,'{','}')
    tail=tokens[end+1:];count=int(tail[0]);assert tail[1]=='('
    end=foam.matching(tail,1,'(',')');flat=[float(x) for x in tail[2:end] if x not in ('(',')')]
    return count,flat


def geometry(event,cache):
    eid=event['id'];output=cache/eid;output.mkdir(parents=True,exist_ok=True);saved=output/'geometry.json'
    if saved.is_file():return load(saved)
    before=Path(event['evidence_dir'])/'before';mesh=before/'constant/polyMesh'
    assert mesh.is_dir(),'缺少实际启动前的网格快照'
    _,points=raw_list(mesh/'points');vertices=[points[i:i+3] for i in range(0,len(points),3)]
    zones=foam.cell_zones(mesh/'cellZones') if (mesh/'cellZones').is_file() else {}
    _,owners=raw_list(mesh/'owner');_,neighbors=raw_list(mesh/'neighbour');count=int(max(owners+neighbors))+1
    with tempfile.TemporaryDirectory(prefix='rag-modeling-geometry-') as name:
        case=Path(name)/'case';(case/'system').mkdir(parents=True);(case/'0').mkdir();(case/'constant').mkdir()
        shutil.copytree(mesh,case/'constant/polyMesh')
        (case/'system/controlDict').write_text('FoamFile {version 2.0;format ascii;class dictionary;object controlDict;} application postProcess;startFrom startTime;startTime 0;stopAt endTime;endTime 1;deltaT 1;writeControl timeStep;writeInterval 1;')
        for filename in ('fvSchemes','fvSolution'):
            if (before/'system'/filename).is_file():shutil.copyfile(before/'system'/filename,case/'system'/filename)
        for function in ('writeCellVolumes','writeCellCentres'):
            with (output/(function+'.log')).open('w') as log:
                p=subprocess.run(['postProcess','-case',str(case),'-func',function,'-time','0'],stdout=log,stderr=subprocess.STDOUT,timeout=90)
            if p.returncode:raise RuntimeError(function+'失败，详见独立几何日志')
        def expand(path,components):
            f=base.field(path);values=f['values']*count if f['uniform'] else f['values']
            assert len(values)==count*components,(path,len(values),count)
            return values
        vol=expand(case/'0/V',1);flat=expand(case/'0/C',3);xyz=[flat[i:i+3] for i in range(0,len(flat),3)]
    assert all(v>0 for v in vol)
    result={'vertices':vertices,'volumes':vol,'xyz':xyz,'zones':zones,'cells':count,'mesh_snapshot':str(mesh)}
    save(saved,result);return result


def terminal(event):
    root=Path(event['evidence_dir'])/'after/latest-state'
    directories=[p for p in root.iterdir() if p.is_dir()]
    assert len(directories)==1,'终态快照不唯一'
    return directories[0]


def scalar_frame(path,count):
    f=base.field(path);assert f['components']==1,path
    values=f['values']*count if f['uniform'] else f['values'];assert len(values)==count,path
    return values


def vector_frame(path,count,components):
    f=base.field(path);assert f['components']==components,path
    values=f['values']*count if f['uniform'] else f['values'];assert len(values)==count*components,path
    return [values[i:i+components] for i in range(0,len(values),components)]


def rings(values,tol=1e-8):
    values=sorted(values);out=[]
    for x in values:
        if not out or abs(x-out[-1])>tol:out.append(x)
    return out


def input_scalar(before,file,entry):
    d=foam.read_foam(before/file)
    for key in entry.split('/'):d=d[key]
    return number(d)


def geometry_tolerance(vertices, cylindrical=False):
    # 小角度楔模型的半径可定义在对称轴截面或圆/球面节点上；二者差异为sec(theta)-1。
    # 不把这个已知几何离散约定误判成尺寸改错。完整周向模型仍使用点文件精度容差。
    directions=[]
    for p in vertices:
        q=p[:2] if cylindrical else p
        r=math.sqrt(sum(x*x for x in q))
        if r>1e-14:directions.append([x/r for x in q])
    mean=[math.fsum(x[i] for x in directions)/len(directions) for i in range(len(directions[0]))]
    norm=math.sqrt(sum(x*x for x in mean))
    if norm<.5:return 1e-5
    axis=[x/norm for x in mean];cosine=min(sum(x*y for x,y in zip(d,axis)) for d in directions)
    if cosine<=0:return 1e-5
    return min(.005,max(1e-5,1/cosine-1+1e-5))


def g01_event(event,cache,req):
    checks=[];mesh=geometry(event,cache);xyz=mesh['xyz'];vol=mesh['volumes'];n=mesh['cells'];rf=req['rf_m'];rci=req['rci_m'];rco=req['rco_m'];L=req['height_m']
    radius=[math.hypot(*p[:2]) for p in xyz];vp=[math.hypot(*p[:2]) for p in mesh['vertices']]
    fuel=[i for i,r in enumerate(radius) if r<rf];clad=[i for i,r in enumerate(radius) if r>=rci-1e-8]
    fuel_r=rings([radius[i] for i in fuel]);clad_r=rings([radius[i] for i in clad]);counts=[len(fuel_r),len(clad_r)]
    check(checks,'material_regions_and_no_gap_cells',bool(fuel) and bool(clad) and len(fuel)+len(clad)==n)
    geom_tol=geometry_tolerance(mesh['vertices'],True)
    check(checks,'target_radial_geometry',all(min(abs(r-value) for r in vp)<geom_tol*value for value in (rf,rci,rco)) and min(vp)<1e-10 and math.isclose(max(vp),rco,rel_tol=geom_tol),relative_tolerance_from_wedge=geom_tol)
    heights=[p[2] for p in mesh['vertices']];check(checks,'target_length',math.isclose(max(heights)-min(heights),L,rel_tol=5e-6))
    check(checks,'requested_radial_mesh',counts in req['radial_cells'],radial_counts=counts)
    check(checks,'single_axial_cell_layer',len(rings([p[2] for p in xyz]))==1)
    end=terminal(event);before=Path(event['evidence_dir'])/'before';T=scalar_frame(end/'T',n);solver=foam.read_foam(before/'constant/solverDict');schemes=foam.read_foam(before/'system/fvSchemes')
    check(checks,'steady_thermal_solver',solver.get('thermalSolver')==['solidConduction'] and schemes.get('ddtSchemes',{}).get('default')==['steadyState'])
    check(checks,'mechanics_inactive',solver.get('mechanicsSolver') in (['constant'],['fromLatestTime']))
    initial=foam.read_foam(before/'0/T')['internalField'];check(checks,'initial_temperature',initial[0]=='uniform' and math.isclose(number(initial),req['wall_K']))
    # 参数与实际场分开核对；无k场时根据材料输入记录，数值响应另行独立约束。
    if (end/'k').is_file():
        k=scalar_frame(end/'k',n);check(checks,'actual_conductivities',all(math.isclose(k[i],req['kf_W_mK'],rel_tol=1e-5) for i in fuel) and all(math.isclose(k[i],req['kc_W_mK'],rel_tol=1e-5) for i in clad))
    else:
        mat=solver.get('materials',{});kv=[number(m['k']) for m in mat.values() if isinstance(m,dict) and 'k' in m]
        check(checks,'constant_conductivity_input',all(any(math.isclose(x,w,rel_tol=1e-5) for x in kv) for w in (req['kf_W_mK'],req['kc_W_mK'])))
    q_path=end/'Q'
    if q_path.is_file():
        Q=scalar_frame(q_path,n);qmean=math.fsum(Q[i]*vol[i] for i in fuel)/math.fsum(vol[i] for i in fuel);effective_q=qmean*math.pi*rf*rf
        check(checks,'actual_line_power',math.isclose(effective_q,req['q_W_m'],rel_tol=3e-3),actual_W_m=effective_q)
    else:
        try:raw=solver['heatSourceOptions']['lhgr'];values=[float(x) for x in raw if x not in ('(',')')];ok=values and all(math.isclose(x,req['q_W_m'],rel_tol=1e-8) for x in values)
        except (ValueError,KeyError):ok=False
        check(checks,'line_power_input',ok)
    q=req['q_W_m'];kc=req['kc_W_mK'];kf=req['kf_W_mK'];wall=req['wall_K'];h=req['h_W_m2K']
    Tci=wall+q*math.log(rco/rci)/(2*math.pi*kc);Tfs=Tci+q/(2*math.pi*rf*h)
    references=[Tfs+q/(4*math.pi*kf)*(1-(r/rf)**2) if i in fuel else wall+q*math.log(rco/r)/(2*math.pi*kc) for i,r in enumerate(radius)]
    error=max(abs(x-y) for x,y in zip(T,references));scale=Tfs+q/(4*math.pi*kf)-wall
    check(checks,'temperature_reference_error_under_3percent_rise',error/scale<=.03,max_error_K=error,relative_to_rise=error/scale)
    return {'checks':checks,'passed':all(c['passed'] for c in checks),'radial_counts':counts,'max_temperature_K':max(T),'max_reference_error_K':error,'case_root':event['case_root'],'event_id':event['id'],'final_time_directory':end.name,'cells':n}


def g02_event(event,cache,req):
    checks=[];mesh=geometry(event,cache);n=mesh['cells'];before=Path(event['evidence_dir'])/'before';end=terminal(event)
    rv=[math.sqrt(sum(x*x for x in p)) for p in mesh['vertices']];radii=[math.sqrt(sum(x*x for x in p)) for p in mesh['xyz']]
    geom_tol=geometry_tolerance(mesh['vertices'])
    check(checks,'target_spherical_shell_radii',math.isclose(min(rv),req['a_m'],rel_tol=geom_tol) and math.isclose(max(rv),req['b_m'],rel_tol=geom_tol),relative_tolerance_from_wedge=geom_tol)
    check(checks,'minimum_radial_resolution',len(rings(radii))>=req['minimum_radial_cells'],radial_rings=len(rings(radii)))
    solver=foam.read_foam(before/'constant/solverDict');materials=[m for m in solver.get('materials',{}).values() if isinstance(m,dict) and 'material' in m]
    check(checks,'small_strain_elasticity',solver.get('mechanicsSolver')==['smallStrain'] and all(m.get('rheologyModel')==['elasticity'] for m in materials))
    check(checks,'target_E_nu',bool(materials) and all(math.isclose(number(m['E']),req['E_Pa'],rel_tol=1e-8) and math.isclose(number(m['nu']),req['nu'],rel_tol=1e-8) for m in materials))
    check(checks,'thermal_expansion_off',solver.get('rheologyOptions',{}).get('thermalExpansion') in (['off'],['false']))
    initial=foam.read_foam(before/'0/D')['boundaryField'];pressures=[]
    for key,bc in initial.items():
        if isinstance(bc,dict) and 'pressure' in bc:
            try:pressures.append(number(bc['pressure']))
            except ValueError:pass
    pressure=next((p for p in req['pressures_inner_Pa'] if any(math.isclose(v,p,rel_tol=1e-8) for v in pressures)),None)
    check(checks,'inner_pressure_identified',pressure is not None,pressure_values_Pa=pressures)
    check(checks,'outer_pressure_5MPa',any(math.isclose(v,req['pressure_outer_Pa'],rel_tol=1e-8) for v in pressures))
    T=scalar_frame(end/'T',n);check(checks,'actual_temperature_300K',all(math.isclose(x,req['T_K'],abs_tol=1e-5) for x in T))
    D=vector_frame(end/'D',n,3);S=vector_frame(end/'sigma',n,6)
    projected=[]
    for x,r,u,s in zip(mesh['xyz'],radii,D,S):
        a,b,c=[v/r for v in x];xx,xy,xz,yy,yz,zz=s;rr=xx*a*a+2*xy*a*b+2*xz*a*c+yy*b*b+2*yz*b*c+zz*c*c
        projected.append((sum(ui*xi/r for ui,xi in zip(u,x)),rr,(xx+yy+zz-rr)/2))
    errors={}
    if pressure is not None:
        a=req['a_m'];b=req['b_m'];po=req['pressure_outer_Pa'];E=req['E_Pa'];nu=req['nu'];A=(pressure*a**3-po*b**3)/(b**3-a**3);B=(pressure-po)*a**3*b**3/(b**3-a**3)
        references=[((1-2*nu)*A*r/E+(1+nu)*B/(2*E*r*r),A-B/r**3,A+B/(2*r**3)) for r in radii]
        for component,label in enumerate(('radial_displacement','radial_stress','tangential_stress')):
            scale=max(abs(v[component]) for v in references);err=max(abs(x[component]-y[component]) for x,y in zip(projected,references));errors[label]={'max_absolute':err,'relative_to_reference_max':err/scale}
            check(checks,label+'_reference_error_under_3percent',err/scale<=.03,**errors[label])
    return {'checks':checks,'passed':all(c['passed'] for c in checks),'pressure_inner_Pa':pressure,'reference_errors':errors,'case_root':event['case_root'],'event_id':event['id'],'final_time_directory':end.name,'cells':n,'radial_rings':len(rings(radii))}


def m01_event(event,cache,req):
    checks=[];mesh=geometry(event,cache);n=mesh['cells'];before=Path(event['evidence_dir'])/'before';end=terminal(event)
    vertices_r=[math.sqrt(sum(x*x for x in p)) for p in mesh['vertices']];rr=[math.sqrt(sum(x*x for x in p)) for p in mesh['xyz']]
    geom_tol=geometry_tolerance(mesh['vertices'])
    check(checks,'target_solid_sphere_radius',min(vertices_r)<1e-10 and math.isclose(max(vertices_r),req['radius_m'],rel_tol=geom_tol),relative_tolerance_from_wedge=geom_tol)
    check(checks,'minimum_radial_resolution',len(rings(rr))>=req['minimum_radial_cells'],radial_rings=len(rings(rr)))
    solver=foam.read_foam(before/'constant/solverDict');materials=[m for m in solver.get('materials',{}).values() if isinstance(m,dict) and 'material' in m]
    check(checks,'single_UO2_material',len(materials)==1 and materials[0].get('material')==['UO2'])
    T=scalar_frame(end/'T',n);diff=scalar_frame(end/'diffCs',n);source=scalar_frame(end/'sourceCs',n);Cs=scalar_frame(end/'Cs',n)
    check(checks,'actual_temperature_1650K',all(math.isclose(x,req['T_K'],abs_tol=1e-5) for x in T))
    check(checks,'effective_diffusivity_2_5e_14',all(math.isclose(x,req['D_m2_s'],rel_tol=1e-5) for x in diff),actual_min=min(diff),actual_max=max(diff))
    check(checks,'actual_generation_source_zero',all(abs(x)<1e-20 for x in source))
    check(checks,'finite_nonnegative_concentration',min(Cs)>=-1e-10)
    boundaries=foam.read_foam(end/'Cs').get('boundaryField',{});absorbing=[name for name,bc in boundaries.items() if isinstance(bc,dict) and bc.get('type')==['fixedValue'] and bc.get('value') is not None and abs(number(bc['value']))<1e-12]
    check(checks,'absorbing_outer_boundary',bool(absorbing),patches=absorbing)
    C0=input_scalar(before,'constant/solverDict','elementTransportOptions/FpDiffusionOptions/intialFpConcentration/Cs');check(checks,'initial_concentration_0_6',math.isclose(C0,req['C0_mol_m3'],rel_tol=1e-9))
    control=event['control'];schemes=foam.read_foam(before/'system/fvSchemes')
    check(checks,'Euler_fixed_100s_step',schemes.get('ddtSchemes',{}).get('default')==['Euler'] and math.isclose(number(control['deltaT'])*event['factor'],100,rel_tol=1e-10) and control.get('adjustableTimeStep',['false']) in (['false'],['off'],['0']))
    # 明确检查实际保留时刻，不用显示精度要求触发重算。
    saved=[float(x)*event['factor'] for x in event.get('after_state',{}).get('time_directories',[]) if float(x)>=0];saved=sorted(set(saved));gaps=[y-x for x,y in zip(saved,saved[1:])]
    check(checks,'saved_history_spacing_at_most_1000s',len(saved)>=31 and gaps and max(gaps)<=1000+1e-6,positive_time_count=len(saved)-1,max_gap_s=max(gaps) if gaps else None)
    volume=math.fsum(mesh['volumes']);inventory=math.fsum(c*v for c,v in zip(Cs,mesh['volumes']));release=1-inventory/(C0*volume)
    Fo=req['D_m2_s']*req['end_s']/req['radius_m']**2;reference=1-6/math.pi**2*math.fsum(math.exp(-i*i*math.pi**2*Fo)/(i*i) for i in range(1,1000))
    check(checks,'release_fraction_reference_abs_error_at_most_0_02',abs(release-reference)<=.02,actual=release,reference=reference,absolute_error=abs(release-reference))
    return {'checks':checks,'passed':all(c['passed'] for c in checks),'release_fraction_actual':release,'release_fraction_reference':reference,'whole_sphere_inventory_mol':inventory*(4*math.pi/3*req['radius_m']**3)/volume,'native_domain_volume_m3':volume,'case_root':event['case_root'],'event_id':event['id'],'final_time_directory':end.name,'cells':n,'radial_rings':len(rings(rr))}


def evidence_common(root,tid,arm,events):
    work=root/tid/arm/'workspace';checks=[];text=artifacts(work);catalog=tables(work)
    retrieval=[];choice=[]
    for p in work.rglob('*'):
        if not p.is_file() or any(x in ('execution-evidence','polyMesh') for x in p.relative_to(work).parts) or p.stat().st_size>1_000_000:continue
        if p.suffix in ('.json','.jsonl','.txt','.out','.log') and (p.suffix=='.json' or re.search(r'retriev|rag|search|query',str(p.relative_to(work)),re.I)):
            try:raw=p.read_text()
            except UnicodeError:continue
            decoder=json.JSONDecoder();offset=0
            while True:
                start=raw.find('{',offset)
                if start<0:break
                try:d,length=decoder.raw_decode(raw[start:]);offset=start+length
                except ValueError:offset=start+1;continue
                if isinstance(d,dict) and d.get('interface')=='mandifuel-rag-query.v2' and d.get('candidates'):
                    retrieval.append({'file':str(p.relative_to(work)),'mode':d.get('mode'),'network_requests':d.get('provider_telemetry',{}).get('network_requests'),'top_candidates':[x['card_path'] for x in d['candidates'][:5]]})
        if p.suffix in ('.md','.json','.txt','.py','.sh'):
            try:s=p.read_text()
            except UnicodeError:continue
            if re.search(r'Cases/(?:Verification|testCases|restart)/',s):choice.append(str(p.relative_to(work)))
    check(checks,'retrieval_result_saved',bool(retrieval),files=[x['file'] for x in retrieval])
    check(checks,'retrieval_offline',bool(retrieval) and all(x['mode']=='local' and x['network_requests']==0 for x in retrieval))
    check(checks,'reference_choice_traceable',bool(choice),files=choice[:15])
    check(checks,'mesh_check_log_present',any(p.is_file() and 'checkmesh' in p.name.lower() for p in work.rglob('*') if 'execution-evidence' not in p.parts))
    check(checks,'data_tables_present',bool(catalog),tables=catalog)
    # 交付字段别名仅作覆盖辅助，最终按实际表和说明人工复核。
    headers=' '.join(' '.join(t['columns']) for t in catalog)
    if tid=='G01':
        check(checks,'radial_temperature_profiles',bool(re.search(r'radius|radial|r_m|r_mm|径向',headers,re.I)) and bool(re.search(r'temp|T_|\bT\b|温度',headers,re.I)))
        check(checks,'surface_responses_and_mesh_comparison',bool(re.search(r'fuelOuter|fuel.surface|燃料.*表面',text,re.I)) and bool(re.search(r'cladInner|clad.inner|包壳.*内',text,re.I)) and bool(re.search(r'coarse|fine|粗|细|20|40',text,re.I)))
    elif tid=='G02':
        check(checks,'radial_displacement_and_stress_profiles',bool(re.search(r'u_?r|radial.*disp|径向位移',headers,re.I)) and bool(re.search(r'rr|radial.*stress|径向应力',headers,re.I)) and bool(re.search(r'tt|theta|tangent|hoop|(?:sigma|stress|s)_t(?:_|\b)|切向|环向',headers,re.I)))
        check(checks,'inner_outer_surface_responses',bool(re.search(r'inner|内表面|内侧',text,re.I)) and bool(re.search(r'outer|外表面|外侧',text,re.I)))
    else:
        check(checks,'radial_concentration_profile',bool(re.search(r'radius|radial|r_m|r_mm|r_um|径向',headers,re.I)) and bool(re.search(r'Cs|concentration|浓度',headers,re.I)))
        check(checks,'inventory_release_history',bool(re.search(r'release|释放',headers,re.I)) and bool(re.search(r'inventory|moles|mol|库存',headers,re.I)) and bool(re.search(r'time|t_s|时间',headers,re.I)))
        check(checks,'whole_sphere_conversion_documented',bool(re.search(r'solid.angle|4\s*\*?\s*pi|4π|whole.(?:sphere|kernel)|full.(?:sphere|kernel)|整个球|整球|立体角|体积比例|V_kernel/V_mesh',text,re.I)))
    return checks,{'retrieval':retrieval,'reference_choice_files':choice[:30],'data_tables':catalog}


def main():
    root=Path(sys.argv[1]).resolve();manifest=load(root/'manifest.json');bank={t['id']:t for t in load(root/'tasks.json')['tasks']};cache=root/'独立几何核对';cache.mkdir(exist_ok=True)
    output={'scope':'冻结物理要求、实际启动前网格/输入、实际退出及终态场、检索和交付；不以DSH自述代替完成。','tasks':{},'organizer_solver_starts':0}
    for tid in manifest['task_ids']:
        output['tasks'][tid]={}
        for arm in ('bare','skill'):
            folder=root/tid/arm;work=folder/'workspace';events=base.execution(work);req=bank[tid]['requirements'];checks,common=evidence_common(root,tid,arm,events)
            normal=[e for e in events if e['normal'] and math.isclose(e['physical_last_time_s'] or -1,req['end_s'],rel_tol=1e-9,abs_tol=1e-8)];cases=[]
            for e in normal:
                try:cases.append({'G01':g01_event,'G02':g02_event,'M01':m01_event}[tid](e,cache,req))
                except Exception as exc:cases.append({'passed':False,'event_id':e['id'],'case_root':e['case_root'],'evaluation_error':str(exc),'checks':[]})
            if tid=='G01':
                for pair in req['radial_cells']:
                    valid=[x for x in cases if x.get('radial_counts')==pair];check(checks,'requested_mesh_'+str(pair),any(x['passed'] for x in valid),events=[x['event_id'] for x in valid])
            elif tid=='G02':
                for p in req['pressures_inner_Pa']:
                    valid=[x for x in cases if x.get('pressure_inner_Pa')==p];check(checks,'requested_pressure_'+str(p),any(x['passed'] for x in valid),events=[x['event_id'] for x in valid])
            else:check(checks,'requested_diffusion_case',any(x['passed'] for x in cases))
            result={'status':'completed' if all(c['passed'] for c in checks) else 'partial' if normal else 'incomplete','checks':checks,'case_checks':cases,'executions':events,'solver_starts':len(base.rows(work/'solver-starts.jsonl')),'blocked_launch_attempts':0,'run':load(folder/'run.json'),'deliverables':base.scan_deliverables(work),**common}
            output['tasks'][tid][arm]=result
    output['integrity']={'plugin_unchanged':manifest.get('plugin_unchanged'),'shared_resources_unchanged':manifest.get('shared_resources_unchanged'),'no_target_inputs_supplied':True}
    save(root/'verification.json',output)
    print(json.dumps({tid:{arm:{'status':x['status'],'starts':x['solver_starts'],'failed':[c['check'] for c in x['checks'] if not c['passed']],'case_errors':[y.get('evaluation_error') or [c['check'] for c in y['checks'] if not c['passed']] for y in x['case_checks']]} for arm,x in pair.items()} for tid,pair in output['tasks'].items()},ensure_ascii=False))

if __name__=='__main__':main()
