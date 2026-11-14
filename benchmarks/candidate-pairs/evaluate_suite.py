#!/usr/bin/env python3
"""Check requested deliverables and execution evidence; no analytic reference solve."""
import argparse
import ast
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import new_case_checks
import generalization_checks
import capability_task_checks
reader=HERE/'reference_reader.py'
if not reader.exists(): reader=HERE.parent/'fuel-rod-power-ab/verify_results.py'
spec=importlib.util.spec_from_file_location('independent_foam',reader); foam=importlib.util.module_from_spec(spec); spec.loader.exec_module(foam)


def load(path,default=None): return json.loads(path.read_text()) if path.is_file() else default

def rows(path): return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def hashes(root): return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}

def check(items,name,passed,**evidence): items.append({'check':name,'passed':bool(passed),**evidence})

def number(words): return float(words[-1])

def times(case):
    out=[]
    if not case.is_dir(): return out
    for path in case.iterdir():
        if not path.is_dir(): continue
        try: value=Decimal(path.name)
        except InvalidOperation: continue
        if value.is_finite() and value>=0: out.append((value,path))
    return sorted(out,key=lambda item:item[0])


def unit_factor(control):
    kind=control.get('userTime',{}).get('type',['seconds'])[0]
    return kind,{'seconds':1.,'days':86400.,'hours':3600.,'years':31536000.}[kind]


def field(path):
    data=foam.read_foam(path)
    if 'internalField' not in data: return {'class':data.get('FoamFile',{}).get('class'),'dictionary':True,'sha256':sha(path)}
    values=data['internalField']; uniform=values[0]=='uniform'
    payload=values[1:] if uniform else values[4:-1]
    flat=[float(token) for token in payload if token not in ['(',')']]
    if not all(math.isfinite(v) for v in flat): raise ValueError(f'nonfinite field: {path}')
    return {'class':data.get('FoamFile',{}).get('class',[''])[0],'uniform':uniform,'values':flat,'components':{'volScalarField':1,'volVectorField':3,'volSymmTensorField':6,'volTensorField':9,'volSphericalTensorField':1}.get(data.get('FoamFile',{}).get('class',[''])[0],1),'count':1 if uniform else int(values[2]),'dimensions':data.get('dimensions'),'min':min(flat),'max':max(flat),'sha256':sha(path)}


def scalar_boundary(path,patch):
    data=foam.read_foam(path); b=data['boundaryField'][patch]; value=b['value']
    values=[float(value[1])] if value[0]=='uniform' else [float(v) for v in value[4:-1]]
    return {'minimum_m':min(values),'maximum_m':max(values),'mean_m':sum(values)/len(values),'mean_um':sum(values)/len(values)*1e6,'face_values_m':values,'dimensions':data.get('dimensions'),'field_sha256':sha(path)}


def scan_deliverables(workspace):
    out=[]
    for p in workspace.rglob('*'):
        if not p.is_file(): continue
        relative=p.relative_to(workspace)
        if any(part in {'source-case','execution-evidence','polyMesh','.dsh'} for part in relative.parts): continue
        if p.suffix in {'.json','.csv','.md','.py','.sh','.svg'}: out.append({'path':str(relative),'bytes':p.stat().st_size})
    return sorted(out,key=lambda item:item['path'])


def execution(workspace):
    events=[]
    for folder in (workspace/'execution-evidence').glob('*'):
        start=load(folder/'start.json'); exit=load(folder/'exit.json',{})
        if not start: continue
        log=(folder/'solver.log').read_text(errors='replace') if (folder/'solver.log').is_file() else ''
        before=folder/'before'; control=foam.read_foam(before/'system/controlDict') if (before/'system/controlDict').is_file() else {}
        unit,factor=unit_factor(control) if control else ('unknown',None)
        log_times=list(re.finditer(r'^Time\s*=\s*([-+\d.eE]+)\s*(\w+)?',log,re.M))
        log_factors={'seconds':1.,'days':86400.,'hours':3600.,'years':31536000.}
        observed=[float(m.group(1))*log_factors.get(m.group(2),factor) for m in log_times] if factor else []
        terminal=bool(log.strip()) and log.strip().splitlines()[-1].strip().lower()=='end'
        error=re.search(r'FOAM FATAL[\s\S]{0,900}',log)
        state=load(folder/'after/inventory.json',{})
        observed_log_end=max(observed) if observed else None
        saved_times=[]
        for name in state.get('time_directories',[]):
            try: saved_times.append(float(Decimal(name))*factor)
            except (InvalidOperation,ValueError,TypeError): pass
        observed_end=max(saved_times) if saved_times else observed_log_end
        events.append({'id':start['id'],'started_at_utc':start['started_at_utc'],'case_root':start['case_root'],'exit_code':exit.get('exit_code'),'wall_seconds':exit.get('wall_seconds'),'normal':exit.get('exit_code')==0 and terminal and not foam.fatal_solver_log(log),'terminal_marker':terminal,'control':control,'unit':unit,'factor':factor,'physical_times_s':observed,'physical_last_time_s':observed_end,'physical_last_log_time_s':observed_log_end,'before_state':load(folder/'before/inventory.json',{}),'after_state':state,'evidence_dir':str(folder),'error':error.group(0) if error else ('signal '+str(exit['exit_code']) if exit.get('exit_code',0)<0 else None)})
    return sorted(events,key=lambda event:event['started_at_utc'])


def p02(workspace,source,common):
    checks=common[:]; target=workspace/'target-case'; result={'checks':checks,'status':'incomplete'}
    check(checks,'target_case_exists',target.is_dir())
    prep=[p for p in [workspace/'prepare.json',target/'prepare.json'] if p.is_file()]
    check(checks,'prepare_record_present',bool(prep),paths=[str(p.relative_to(workspace)) for p in prep])
    if not (target/'rodDict').is_file(): return result
    original=ast.literal_eval((source/'rodDict').read_text()); geometry=ast.literal_eval((target/'rodDict').read_text())
    unit=float(geometry['convertToMeters']); original_unit=float(original['convertToMeters'])
    expected={'rOuterFuel':.0042,'rInnerClad':.0043,'rOuterClad':.0049}
    actual={key:[float(v)*unit for v in geometry[key]] for key in expected}
    result['geometry_radii_m']=actual
    for key,value in expected.items(): check(checks,key,len(geometry[key])==len(original[key]) and all(abs(v-value)<=1e-12 for v in actual[key]),actual_m=actual[key])
    for key in ['heightFuel','heightClad']:
        check(checks,'axis_'+key,len(geometry[key])==len(original[key]) and all(abs(float(a)*unit-float(b)*original_unit)<=1e-12 for a,b in zip(geometry[key],original[key])))
    for key in ['offsetFuel','offsetClad']: check(checks,'axis_'+key,abs(float(geometry[key])*unit-float(original[key])*original_unit)<=1e-12)
    unchanged_keys=['geometryType','nBlocksFuel','nBlocksClad','blockNameFuel','blockNameClad','nCellsRFuel','nCellsRClad','nCellsZFuel','nCellsZClad','wedgeAngle']
    check(checks,'structure_preserved',all(geometry.get(key)==original.get(key) for key in unchanged_keys))
    solver=foam.read_foam(target/'constant/solverDict'); base=foam.read_foam(source/'constant/solverDict')
    cold=solver['materials']['fuel']; result['cold_dimensions_m']={key:number(cold[key]) for key in ['DiamCold','GapCold']}
    for key,wanted in [('DiamCold',.0084),('GapCold',.0002)]: check(checks,key,abs(number(cold[key])-wanted)<=1e-12,actual_m=number(cold[key]))
    for data in [solver,base]:
        for key in ['DiamCold','GapCold']: data['materials']['fuel'].pop(key,None)
    check(checks,'other_material_and_load_settings_preserved',foam.equivalent(solver,base))
    required=[p.relative_to(source) for folder in ['0','constant','system'] for p in (source/folder).rglob('*') if p.is_file()]+[Path('rodMaker.py'),Path('rodDict'),Path('Allrun')]
    check(checks,'complete_inputs',all((target/p).is_file() for p in required))
    result.update(status='prepared' if all(c['passed'] for c in checks) else 'partial',prepare_files=[str(p.relative_to(workspace)) for p in prep])
    return result


def c04(workspace,events,common):
    checks=common[:]; completed=[e for e in events if e['normal'] and e['physical_last_time_s'] is not None and abs(e['physical_last_time_s']-1532339424.)<=1.]
    check(checks,'normal_completion_at_requested_time',bool(completed))
    result={'checks':checks,'status':'incomplete'}
    if not completed: return result
    event=completed[-1]; case=Path(event['case_root']); unit=event['unit']; factor=event['factor']
    saved=[(v,p) for v,p in times(case) if (p/'oxideThickness').is_file()]
    check(checks,'oxide_field_present',bool(saved))
    if not saved: return result
    last,p=saved[-1]; value=scalar_boundary(p/'oxideThickness','cladOuter')
    history=[]
    for time,folder in saved:
        entry=scalar_boundary(folder/'oxideThickness','cladOuter')
        history.append({'directory':folder.name,'model_time':float(time),'physical_seconds':float(time)*factor,'mean_m':entry['mean_m'],'mean_um':entry['mean_um']})
    result.update(result_root=str(case),model_time_unit=unit,final_time_directory=p.name,final_physical_seconds=float(last)*factor,final_oxide=value,saved_field_history=history)
    control=event['control']; raw=foam.read_foam(case/'0/T')['boundaryField']
    check(checks,'outer_temperature_550K',raw.get('cladOuter',{}).get('type')==['fixedValue'] and abs(number(raw['cladOuter']['value'])-550)<1e-12)
    check(checks,'inner_adiabatic',raw.get('cladInner',{}).get('type')==['zeroGradient'])
    selected=foam.read_foam(Path(event['evidence_dir'])/'before/constant/solverDict'); original=foam.read_foam(workspace/'source-case/constant/solverDict')
    check(checks,'materials_and_corrosion_preserved',foam.equivalent(selected.get('materials'),original.get('materials')) and foam.equivalent(selected.get('corrosionOptions'),original.get('corrosionOptions')) and selected.get('corrosion')==original.get('corrosion'))
    check(checks,'final_directory_time',abs(float(last)*factor-1532339424.)<=1.)
    check(checks,'nonnegative_real_boundary_thickness',value['minimum_m']>=0 and math.isfinite(value['maximum_m']))
    def delivered(path):
        return not any(part in {'source-case','sources','execution-evidence','polyMesh'} for part in path.relative_to(workspace).parts)
    history_files=[p for p in workspace.rglob('*.csv') if delivered(p) and any(word in p.name.lower() for word in ['oxide','thickness','history','saved'])]
    reports=[p for p in workspace.rglob('*.md') if delivered(p) and p.name.lower() not in ['readme_structure','readme_commands']]
    check(checks,'history_table_present',bool(history_files),files=[str(p.relative_to(workspace)) for p in history_files])
    check(checks,'report_present',bool(reports),files=[str(p.relative_to(workspace)) for p in reports])
    result['status']='completed' if all(c['passed'] for c in checks) else 'partial'
    return result


def w01(workspace,events,common):
    checks=common[:]
    normal=[e for e in events if e['normal']]
    full=[e for e in normal if abs((e['physical_last_time_s'] or -1)-1576800.)<=1e-7 and e['physical_times_s'] and abs(e['physical_times_s'][0]-78840.)<=1e-7]
    first=[e for e in normal if abs((e['physical_last_time_s'] or -1)-788400.)<=1e-7 and e['physical_times_s'] and abs(e['physical_times_s'][0]-78840.)<=1e-7]
    second=[e for e in normal if abs((e['physical_last_time_s'] or -1)-1576800.)<=1e-7 and e['physical_times_s'] and abs(e['physical_times_s'][0]-867240.)<=1e-7]
    check(checks,'continuous_A_normal',bool(full))
    check(checks,'independent_B_first_stage_normal',bool(first))
    check(checks,'B_continuation_stage_normal',bool(second))
    for e in normal:
        physical=e['physical_times_s']; beginning=physical[0]-78840 if physical else 0
        fixed=bool(physical) and all(abs((b-a)-78840)<=1e-7 for a,b in zip([beginning]+physical[:-1],physical))
        check(checks,'fixed_step_'+e['id'][:8],fixed,first_times_s=physical[:3],last_times_s=physical[-3:])
    source=foam.read_foam(workspace/'source-case/constant/solverDict')
    keys=['thermalSolver','mechanicsSolver','neutronicsSolver','heatSource','burnup','fastFlux','gapGas','fgr','corrosion']
    model_changes=[]
    for e in events:
        sourcefile=Path(e['evidence_dir'])/'before/constant/solverDict'
        if not sourcefile.is_file(): continue
        selected=foam.read_foam(sourcefile)
        diff={key:{'source':source.get(key),'actual':selected.get(key)} for key in keys if selected.get(key)!=source.get(key)}
        if diff: model_changes.append({'event_id':e['id'],'case_root':e['case_root'],'changes':diff})
    result={'checks':checks,'status':'completed' if all(c['passed'] for c in checks) else 'partial','source_model_changes':model_changes,'source_preserving':not model_changes,'normal_segments':{'continuous':[e['id'] for e in full],'B_first':[e['id'] for e in first],'B_second':[e['id'] for e in second]},'checkpoint_carry':None,'final_fields':{}}
    if first and second:
        s1=first[-1]; s2=second[-1]
        end=s1['after_state'].get('state_files',{}); begin=s2['before_state'].get('state_files',{})
        expected={k:v for k,v in end.items() if k.startswith('788400/')}
        common_names=sorted(set(expected)&set(begin)); missing=sorted(set(expected)-set(begin)); different=sorted(k for k in common_names if expected[k]!=begin[k])
        result['checkpoint_carry']={'checkpoint_files':len(expected),'same_hash':sum(expected[k]==begin[k] for k in common_names),'missing':missing,'changed_serialization_or_values':different,'note':'哈希不同可能来自合法边界字典兼容修复，需核对实际物理值，不能直接等同状态丢失。'}
        check(checks,'checkpoint_T_D_present',all('788400/'+name in begin for name in ['T','D']))
    for label,selected in [('A',full[-1] if full else None),('B',second[-1] if second else None)]:
        if not selected: continue
        case=Path(selected['case_root']); terminal=next((p for value,p in times(case) if abs(float(value)*selected['factor']-1576800.)<=1e-7),None)
        if not terminal: continue
        fields={}
        for path in sorted(terminal.iterdir()):
            if not path.is_file(): continue
            try:
                item=field(path); item.pop('values',None); fields[path.name]=item
            except Exception as exc: fields[path.name]={'read_error':str(exc)}
        result['final_fields'][label]={'result_root':str(case),'time_directory':terminal.name,'fields':fields}
        check(checks,label+'_T_D_present',all(name in fields and 'read_error' not in fields[name] for name in ['T','D']))
    tables=[p for p in workspace.rglob('*.csv') if not any(part in {'source-case','execution-evidence','polyMesh'} for part in p.relative_to(workspace).parts)]
    result['data_tables']=[str(p.relative_to(workspace)) for p in tables]
    check(checks,'data_tables_present',bool(tables))
    result['status']='completed' if all(c['passed'] for c in checks) else 'partial'
    return result


def main():
    p=argparse.ArgumentParser(); p.add_argument('run_root',type=Path); args=p.parse_args(); root=args.run_root.resolve(); manifest=load(root/'manifest.json')
    output={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'题面交付与真实执行证据，不与解析参考解比对','tasks':{}}
    for task in manifest['tasks']:
        task_id=task['id']; pair=root/task_id; output['tasks'][task_id]={}
        for arm in manifest.get('arms',['bare','skill']):
            workspace=pair/arm/'workspace'; source=pair/'source-case'; common=[]
            starts=rows(workspace/'solver-starts.jsonl'); calls=rows(workspace/'binary-invocations.jsonl'); events=execution(workspace)
            check(common,'source_unchanged',hashes(workspace/'source-case')==hashes(source))
            check(common,'start_budget',task['solver_start_cap'] is None or len(starts)<=task['solver_start_cap'],actual=len(starts),cap=task['solver_start_cap'])
            if task_id=='P02': check(common,'no_solver_started_or_attempted',not starts and not any(e['kind']=='blocked' for e in calls))
            try:
                if task_id=='P02':result=p02(workspace,source,common)
                elif task_id in ['C04','W01']:result={'C04':c04,'W01':w01}[task_id](workspace,events,common)
                elif task_id in ['C06','F02','C02','C08','F01','C05']:
                    api={'check':check,'foam':foam,'field':field,'number':number,'times':times}
                    result={'C05':capability_task_checks.c05,'C06':new_case_checks.c06,'F02':new_case_checks.f02,'C02':generalization_checks.c02,'C08':generalization_checks.c08,'F01':generalization_checks.f01}[task_id](workspace,events,common,api)
                else:raise ValueError('No independent checker for '+task_id)
            except Exception as exc: result={'status':'unverified','checks':common,'evaluation_error':str(exc)}
            result.update(run=load(pair/arm/'run.json'),solver_starts=len(starts),blocked_launch_attempts=sum(c['kind']=='blocked' for c in calls),executions=events,deliverables=scan_deliverables(workspace))
            output['tasks'][task_id][arm]=result
    output['integrity']={'plugin_unchanged':hashes(root/'frozen-plugin')==manifest['plugin_hashes'],'original_sources_unchanged':all(hashes(Path(t['source']))==t['source_evidence']['original_source_hashes'] for t in manifest['tasks']),'original_prompts_unchanged':all(sha(root/t['id']/'task.txt')==t['task_sha256'] for t in manifest['tasks'])}
    (root/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({task:{arm:{'status':a['status'],'starts':a['solver_starts'],'run_exit':a['run'].get('exit_code'),'failed_checks':[c['check'] for c in a['checks'] if not c['passed']],'evaluation_error':a.get('evaluation_error')} for arm,a in arms.items()} for task,arms in output['tasks'].items()},ensure_ascii=False))


if __name__=='__main__': main()
