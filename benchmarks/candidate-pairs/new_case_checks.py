"""Independent delivery/input checks for C06 and F02; no analytic answer scoring."""
from pathlib import Path
import csv
import math
import re


def tables(workspace):
    found=[]
    for path in workspace.rglob('*'):
        if path.suffix.lower() not in {'.csv','.tsv'} or not path.is_file():continue
        if any(p in {'source-case','sources','execution-evidence','polyMesh'} for p in path.relative_to(workspace).parts):continue
        try:
            with path.open() as stream:
                rows=list(csv.DictReader((line for line in stream if line.strip() and not line.lstrip().startswith('#')),delimiter='\t' if path.suffix=='.tsv' else ','))
            found.append({'file':str(path.relative_to(workspace)),'rows':len(rows),'columns':list(rows[0]) if rows else []})
        except (ValueError,UnicodeError,csv.Error):pass
    return found


def finish(result):
    result['status']='completed' if all(c['passed'] for c in result['checks']) else 'partial'
    return result


def c06(workspace,events,common,api):
    check=api['check'];foam=api['foam'];field=api['field'];number=api['number'];times=api['times']
    checks=common[:];result={'checks':checks,'status':'incomplete'}
    normal=[e for e in events if e['normal'] and abs((e['physical_last_time_s'] or -1)-50000)<1e-6]
    check(checks,'normal_completion_50000s',bool(normal))
    if not normal:return result
    event=normal[-1];case=Path(event['case_root']);end=next((p for t,p in times(case) if abs(float(t)*event['factor']-50000)<1e-6),None)
    if end is None:return result
    control=event['control'];solver=foam.read_foam(Path(event['evidence_dir'])/'before/constant/solverDict')
    check(checks,'requested_100s_step',abs(number(control['deltaT'])*event['factor']-100)<1e-9)
    check(checks,'mechanics_not_solved',solver.get('mechanicsSolver') in [['fromLatestTime'],['none']])
    initialT=foam.read_foam(case/'0/T');check(checks,'initial_temperature_1873_15K',abs(number(initialT['internalField'])-1873.15)<1e-8)
    finalT=field(end/'T');check(checks,'final_temperature_1873_15K',abs(finalT['min']-1873.15)<1e-6 and abs(finalT['max']-1873.15)<1e-6)
    cs=end/'Cs';check(checks,'Cs_field_present',cs.is_file())
    if cs.is_file():
        values=field(cs);raw=foam.read_foam(cs);outer=raw.get('boundaryField',{}).get('outer',{})
        check(checks,'absorbing_outer_boundary',outer.get('type')==['fixedValue'] and abs(number(outer['value']))<1e-12)
        check(checks,'finite_nonnegative_concentration',values['min']>=-1e-10)
        result['final_Cs']={k:v for k,v in values.items() if k!='values'}
    diffusivities=[]
    for path in end.iterdir():
        if path.is_file() and re.search(r'diff.*cs|cs.*diff',path.name,re.I):
            try:
                item=field(path);diffusivities.append({'field':path.name,'min':item['min'],'max':item['max'],'dimensions':item.get('dimensions')})
            except (ValueError,KeyError,TypeError):pass
    check(checks,'effective_diffusivity_1e_13',any(math.isclose(d['min'],1e-13,rel_tol=2e-6) and math.isclose(d['max'],1e-13,rel_tol=2e-6) for d in diffusivities),fields=diffusivities)
    catalog=tables(workspace);check(checks,'data_tables_present',bool(catalog))
    profile=[t for t in catalog if t['rows']>=3 and any(re.search(r'radius|radial|^r(?:_|$)|^x(?:_|$)',c,re.I) for c in t['columns'])]
    check(checks,'radial_concentration_table',bool(profile),files=[t['file'] for t in profile])
    result.update(result_root=str(case),final_time_directory=end.name,effective_diffusivities=diffusivities,data_tables=catalog,
        inventory_verification='Volume integral checked separately from retained mesh/fields; not an analytical reference comparison.')
    return finish(result)


def f02(workspace,events,common,api):
    check=api['check'];foam=api['foam'];field=api['field'];number=api['number'];times=api['times']
    checks=common[:];result={'checks':checks,'status':'partial','pressure_cases':{},'data_tables':[]}
    source=foam.read_foam(workspace/'source-case/constant/solverDict');sourceD=foam.read_foam(workspace/'source-case/0/D')
    for pressure in [1e7,2e7]:
        matched=[]
        for e in events:
            if not e['normal'] or abs((e['physical_last_time_s'] or -1)-1)>1e-8:continue
            before=Path(e['evidence_dir'])/'before/0/D';before=before if before.is_file() else Path(e['case_root'])/'0/D'
            try:bc=foam.read_foam(before)['boundaryField']
            except (KeyError,ValueError):continue
            if math.isclose(number(bc['inner']['pressure']),pressure,rel_tol=1e-10):matched.append((e,bc))
        label=str(int(pressure/1e6))+'MPa';check(checks,label+'_normal_completion',bool(matched))
        if not matched:continue
        e,bc=matched[-1];case=Path(e['case_root']);solver=foam.read_foam(Path(e['evidence_dir'])/'before/constant/solverDict')
        check(checks,label+'_outer_pressure_zero',abs(number(bc['outer']['pressure']))<1e-12)
        check(checks,label+'_small_strain',solver.get('mechanicsSolver')==['smallStrain'])
        check(checks,label+'_thermal_expansion_off',solver.get('rheologyOptions',{}).get('thermalExpansion') in [['off'],['false']])
        check(checks,label+'_materials_preserved',foam.equivalent(solver.get('materials'),source.get('materials')))
        actualbc={k:v for k,v in bc.items() if k!='inner'};basebc={k:v for k,v in sourceD['boundaryField'].items() if k!='inner'}
        check(checks,label+'_remaining_boundary_constraints_preserved',foam.equivalent(actualbc,basebc))
        check(checks,label+'_geometry_preserved',foam.equivalent(foam.read_foam(case/'system/blockMeshDict'),foam.read_foam(workspace/'source-case/system/blockMeshDict')))
        end=next(p for t,p in times(case) if abs(float(t)-1)<1e-8)
        data={}
        for name in ['D','sigma','sigmaCyl']:
            if (end/name).is_file():
                item=field(end/name);data[name]={k:v for k,v in item.items() if k!='values'}
        check(checks,label+'_finite_D_and_stress','D' in data and ('sigma' in data or 'sigmaCyl' in data))
        result['pressure_cases'][label]={'result_root':str(case),'event_id':e['id'],'fields':data}
    catalog=tables(workspace);result['data_tables']=catalog
    profile=[];interface=[]
    for t in catalog:
        text=' '.join(t['columns']).lower();name=t['file'].lower()
        if t['rows']>=4 and (re.search(r'rr|radial.*stress|stress.*radial',text) and re.search(r'tt|theta|hoop',text)):
            profile.append(t)
        if re.search(r'interfac|interface|界面',name+' '+text):interface.append(t)
    check(checks,'radial_and_hoop_profile_tables',bool(profile),files=[t['file'] for t in profile])
    check(checks,'interface_displacement_and_traction_table',bool(interface),files=[t['file'] for t in interface])
    result['scope']='Requested pressure cases, preserved inputs, finite result fields and delivered table coverage; no analytical-reference accuracy scoring.'
    return finish(result)
