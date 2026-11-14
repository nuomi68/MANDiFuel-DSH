"""C05预先声明的输入、实际场和交付覆盖检查；无参考解、无求解调用。"""
import math
from pathlib import Path
import re
from generalization_checks import artifacts
from new_case_checks import tables, finish


def c05(workspace, events, common, api):
    check=api['check'];foam=api['foam'];field=api['field'];number=api['number'];times=api['times']
    checks=common[:];result={'checks':checks,'status':'incomplete'}
    normal=[e for e in events if e['normal'] and math.isclose(e['physical_last_time_s'] or -1,2e8,rel_tol=1e-9)]
    check(checks,'normal_completion_2e8s',bool(normal))
    if not normal:return result
    event=normal[-1];case=Path(event['case_root']);before=Path(event['evidence_dir'])/'before'
    initial=foam.read_foam(before/'0/T');solver=foam.read_foam(before/'constant/solverDict')
    original=foam.read_foam(workspace/'source-case/constant/solverDict')
    boundary=foam.read_foam(before/'0/D')['boundaryField']
    check(checks,'source_mechanics_and_creep_materials_preserved',solver.get('mechanicsSolver')==original.get('mechanicsSolver') and foam.equivalent(solver['materials'],original['materials']))
    check(checks,'source_fast_flux_preserved',solver.get('fastFlux')==original.get('fastFlux') and foam.equivalent(solver['fastFluxOptions'],original['fastFluxOptions']))
    right=next((v for k,v in boundary.items() if k.strip('"')=='right'),{})
    check(checks,'source_tensile_load_50MPa',right.get('type')==['tractionDisplacement'] and math.isclose(number(right.get('pressure',['nan'])),-5e7))
    check(checks,'initial_temperature_600K',math.isclose(number(initial['internalField']),600,rel_tol=1e-10))
    check(checks,'source_geometry_preserved',foam.equivalent(foam.read_foam(case/'system/blockMeshDict'),foam.read_foam(workspace/'source-case/system/blockMeshDict')))
    terminal=next((p for t,p in times(case) if math.isclose(float(t)*event['factor'],2e8,rel_tol=1e-9)),None)
    check(checks,'requested_terminal_directory_present',terminal is not None)
    if terminal is None:return finish(result)
    data={name:field(terminal/name) for name in ('T','epsilon','epsEl','epsilonCreep') if (terminal/name).is_file()}
    check(checks,'final_temperature_600K','T' in data and math.isclose(data['T']['min'],600,abs_tol=1e-5) and math.isclose(data['T']['max'],600,abs_tol=1e-5))
    check(checks,'total_elastic_and_creep_fields_present',all(name in data and data[name]['components']==6 for name in ('epsilon','epsEl','epsilonCreep')))
    if all(name in data for name in ('epsilon','epsEl','epsilonCreep')):
        check(checks,'strain_dimensions_dimensionless',all(data[name]['dimensions']==['[','0','0','0','0','0','0','0',']'] for name in ('epsilon','epsEl','epsilonCreep')))
        values={name:entry['values'] for name,entry in data.items() if name!='T'}
        length=max(len(x) for x in values.values())
        for name,x in values.items():
            if len(x)==6 and length>6:values[name]=x*(length//6)
        aligned=all(len(x)==length for x in values.values())
        error=max((abs(a-b-c) for a,b,c in zip(values['epsilon'],values['epsEl'],values['epsilonCreep'])),default=math.inf)
        check(checks,'total_equals_elastic_plus_creep_with_serialization_tolerance',aligned and error<2e-7,maximum_component_residual=error)
        check(checks,'nonzero_xx_creep_response',max(abs(x) for x in values['epsilonCreep'][::6])>0)
        result['strain_closure_max_abs']=error
    catalog=tables(workspace);text=artifacts(workspace);cols=' '.join(' '.join(t['columns']) for t in catalog)
    history=[t for t in catalog if t['rows']>=2 and re.search(r'time|(?:^|\s)t(?:_s)?(?:\s|$)|时间', ' '.join(t['columns']),re.I) and re.search(r'creep|蠕变',t['file']+' '+' '.join(t['columns']),re.I)]
    check(checks,'creep_time_history_table',bool(history),files=[x['file'] for x in history])
    check(checks,'tensor_component_basis_and_units_documented',bool(re.search(r'xx|XX|epsilonCreep\.XX',cols+' '+text)) and bool(re.search(r'dimensionless|无量纲|strain.*\b1\b',text,re.I)) and bool(re.search(r'elastic|弹性',text,re.I)))
    result.update(result_root=str(case),final_time_directory=terminal.name,fields={name:{k:v for k,v in item.items() if k!='values'} for name,item in data.items()},data_tables=catalog,scope='输入、本构与快通量保持、真实终态、应变分解及交付；不和解析参考值评分。')
    return finish(result)
