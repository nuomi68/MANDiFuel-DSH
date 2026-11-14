"""C02/C08/F01：预先固定的输入、真实场和交付覆盖检查；不启动求解。"""
import ast
import math
from pathlib import Path
import re

from new_case_checks import tables, finish


def artifacts(workspace):
    texts=[]
    for p in workspace.rglob('*'):
        if not p.is_file() or p.suffix not in {'.json','.md','.csv','.tsv'}: continue
        if p.name.startswith('.') or any(x in {'source-case','sources','execution-evidence','polyMesh'} for x in p.relative_to(workspace).parts): continue
        texts.append(p.read_text(errors='replace')[:200000])
    return '\n'.join(texts)


def latest(event, api):
    case=Path(event['case_root'])
    positive=[(t,p) for t,p in api['times'](case) if float(t)>0]
    return case,positive[-1][1]


def model_off(value):
    return value in (['none'],['fromLatestTime'],['constant'])


def zero_gradient(b):
    return b.get('type') in (['zeroGradient'],['empty'],['wedge'],['symmetry'],['symmetryPlane']) or (b.get('type')==['fixedGradient'] and b.get('gradient') in (['uniform','0'],['uniform','0.0']))


def c02(workspace,events,common,api):
    check=api['check'];foam=api['foam'];number=api['number'];field=api['field']
    checks=common[:];result={'checks':checks,'status':'incomplete'}
    source=foam.read_foam(workspace/'source-case/system/controlDict');end=number(source['endTime'])
    normal=[e for e in events if e['normal'] and math.isclose(e['physical_last_time_s'] or -1,end,rel_tol=1e-10)]
    check(checks,'normal_completion_at_source_end',bool(normal))
    if not normal:return result
    event=normal[-1];case,terminal=latest(event,api);before=Path(event['evidence_dir'])/'before'
    solver=foam.read_foam(before/'constant/solverDict');original=foam.read_foam(workspace/'source-case/constant/solverDict')
    bc=foam.read_foam(before/'0/D')['boundaryField']
    check(checks,'inner_60MPa_outer_120MPa',math.isclose(number(bc['inner']['pressure']),60e6) and math.isclose(number(bc['outer']['pressure']),120e6))
    check(checks,'small_strain_thermal_expansion_off',solver.get('mechanicsSolver')==['smallStrain'] and solver.get('rheologyOptions',{}).get('thermalExpansion') in (['off'],['false']))
    check(checks,'constant_elastic_materials_preserved',foam.equivalent(solver['materials'],original['materials']))
    check(checks,'geometry_preserved',foam.equivalent(foam.read_foam(case/'system/blockMeshDict'),foam.read_foam(workspace/'source-case/system/blockMeshDict')))
    data={name:field(terminal/name) for name in ['D','sigma'] if (terminal/name).is_file()}
    check(checks,'finite_displacement_and_stress','D' in data and 'sigma' in data and data['D']['components']==3 and data['sigma']['components']==6)
    catalog=tables(workspace);text=artifacts(workspace)
    cols=' '.join(' '.join(t['columns']) for t in catalog).lower()
    radial=bool(re.search(r'u_?r(?:\b|_)|d_?r(?:\b|_)|radial.*disp|disp.*radial|径向位移',cols))
    rr=bool(re.search(r'(?:sigma|stress|s)_?r{1,2}(?:\b|_)|radial.*stress|stress.*radial|径向应力',cols))
    hoop=bool(re.search(r'\b(?:sigma|stress|s)_?(?:tt|theta|hoop)(?:\b|_)|hoop|tangential|环向应力',cols))
    check(checks,'radial_displacement_and_stress_tables',bool(catalog) and radial and rr and hoop,tables=catalog)
    check(checks,'inner_and_outer_surface_responses',bool(re.search(r'inner|内表面|内侧',text,re.I)) and bool(re.search(r'outer|外表面|外侧',text,re.I)))
    check(checks,'basis_and_units_documented',bool(re.search(r'Pa|MPa|GPa',text)) and bool(re.search(r'径向|radial|spherical|球坐标',text,re.I)))
    result.update(result_root=str(case),final_time_directory=terminal.name,data_tables=catalog,
                  final_fields={k:{x:v for x,v in d.items() if x!='values'} for k,d in data.items()})
    return finish(result)


def c08(workspace,events,common,api):
    check=api['check'];foam=api['foam'];number=api['number'];field=api['field']
    checks=common[:];result={'checks':checks,'status':'incomplete'}
    normal=[e for e in events if e['normal'] and math.isclose(e['physical_last_time_s'] or -1,10,rel_tol=1e-10)]
    check(checks,'normal_completion_10s',bool(normal))
    if not normal:return result
    event=normal[-1];case,terminal=latest(event,api);before=Path(event['evidence_dir'])/'before'
    solver=foam.read_foam(before/'constant/solverDict');original=foam.read_foam(workspace/'source-case/constant/solverDict');control=event['control']
    check(checks,'seconds_one_second_step',event['unit']=='seconds' and math.isclose(number(control['deltaT']),1))
    check(checks,'all_ten_saved_frames',all(any(abs(float(t)*event['factor']-i)<1e-8 and (p/'T').is_file() for t,p in api['times'](case)) for i in range(1,11)))
    check(checks,'Euler_time_scheme',foam.read_foam(case/'system/fvSchemes')['ddtSchemes'].get('default')==['Euler'])
    check(checks,'mechanics_disabled',model_off(solver.get('mechanicsSolver')))
    check(checks,'density_heat_capacity_preserved',all(foam.equivalent(solver['materials'][z][v],original['materials'][z][v]) for z in ('fuel','cladding') for v in ('rho','Cp')))
    temp=foam.read_foam(before/'0/T');bc=temp['boundaryField']
    check(checks,'initial_temperature_300K',math.isclose(number(temp['internalField']),300))
    outside={k:v for k,v in bc.items() if k not in ('fuelOuter','cladInner')}
    check(checks,'all_external_boundaries_adiabatic',bool(outside) and all(zero_gradient(v) for v in outside.values()))
    check(checks,'internal_thermal_coupling_retained',all(bc.get(z,{}).get('type') in (['fuelRodGap'],['resistiveGap']) and bc[z].get('coupled') in (['true'],['on']) for z in ('fuelOuter','cladInner')))
    h=solver.get('heatSourceOptions',{});powers=h.get('lhgr',[])
    check(checks,'constant_18000W_per_m',bool(powers) and all(math.isclose(float(v),18000) for v in powers if v not in ('(',')')))
    final=field(terminal/'T');check(checks,'finite_temperature_field',final['min']>=299.99 and final['max']>300)
    catalog=tables(workspace);text=artifacts(workspace);cols=' '.join(' '.join(t['columns']) for t in catalog)
    check(checks,'temperature_and_energy_history_tables',any(t['rows']>=10 for t in catalog) and bool(re.search(r'energy|heat|\bQ\b|J\b|能|热',cols,re.I)),tables=catalog)
    check(checks,'both_regions_and_integration_scope_documented',bool(re.search(r'fuel|燃料',text,re.I)) and bool(re.search(r'clad|包壳',text,re.I)) and bool(re.search(r'volume|体积|计算域|wedge|sector|扇区',text,re.I)))
    result.update(result_root=str(case),final_time_directory=terminal.name,data_tables=catalog,final_T={k:v for k,v in final.items() if k!='values'})
    return finish(result)


def f01(workspace,events,common,api):
    check=api['check'];foam=api['foam'];number=api['number'];field=api['field']
    checks=common[:];result={'checks':checks,'status':'partial','hole_cases':{}}
    source=ast.literal_eval((workspace/'source-case/rodDict').read_text())
    original=foam.read_foam(workspace/'source-case/constant/solverDict')
    normal=[e for e in events if e['normal'] and math.isclose(e['physical_last_time_s'] or -1,1,rel_tol=1e-10)]
    for radius in (.0005,.00075,.001):
        label=f'{radius*1000:.2f}mm';matched=[]
        for event in normal:
            before=Path(event['evidence_dir'])/'before'
            if not (before/'rodDict').is_file():continue
            rod=ast.literal_eval((before/'rodDict').read_text());unit=float(rod['convertToMeters'])
            if all(math.isclose(float(v)*unit,radius,rel_tol=1e-10) for v in rod['rInnerFuel']):matched.append((event,rod))
        check(checks,label+'_normal_completion',bool(matched))
        if not matched:continue
        event,rod=matched[-1];case,terminal=latest(event,api);before=Path(event['evidence_dir'])/'before'
        solver=foam.read_foam(before/'constant/solverDict');bc=foam.read_foam(before/'0/T')['boundaryField'];unit=float(rod['convertToMeters']);oldunit=float(source['convertToMeters'])
        check(checks,label+'_remaining_geometry_preserved',all(len(rod[k])==len(source[k]) and all(math.isclose(float(x)*unit,float(y)*oldunit,rel_tol=1e-10) for x,y in zip(rod[k],source[k])) for k in ['rOuterFuel','rInnerClad','rOuterClad','heightFuel','heightClad']))
        check(checks,label+'_pure_thermal_steady_state',model_off(solver.get('mechanicsSolver')) and foam.read_foam(case/'system/fvSchemes')['ddtSchemes']['default']==['steadyState'] and event['unit']=='seconds')
        fuel=solver['materials']['fuel'];powers=solver.get('heatSourceOptions',{}).get('lhgr',[])
        check(checks,label+'_k3_and_lhgr20000',fuel.get('conductivityModel')==['constant'] and math.isclose(number(fuel['k']),3) and bool(powers) and all(math.isclose(float(v),20000) for v in powers if v not in ('(',')')))
        check(checks,label+'_hole_adiabatic_wall573_gap5000',zero_gradient(bc['fuelInner']) and math.isclose(number(bc['cladOuter']['value']),573) and all(math.isclose(number(bc[z]['alpha']),5000) for z in ('fuelOuter','cladInner')))
        check(checks,label+'_cladding_material_preserved',foam.equivalent(solver['materials']['cladding'],original['materials']['cladding']))
        values=field(terminal/'T');check(checks,label+'_finite_T',values['min']>=572.99 and values['max']>573)
        result['hole_cases'][label]={'result_root':str(case),'event_id':event['id'],'final_T':{k:v for k,v in values.items() if k!='values'}}
    catalog=tables(workspace);text=artifacts(workspace);cols=' '.join(' '.join(t['columns']) for t in catalog)
    check(checks,'temperature_profiles_present',any(t['rows']>=3 and any(re.search(r'radius|radial|^r(?:_|$)|^x(?:_|$)',c,re.I) for c in t['columns']) for t in catalog),tables=catalog)
    check(checks,'source_volume_and_heat_rate_documented',bool(re.search(r'volume|体积',text,re.I)) and bool(re.search(r'W/m3|W/m\^3|W/m³|W m|volumetric|qvol|q_vol|发热率|体积热源',text,re.I)))
    result['data_tables']=catalog
    return finish(result)
