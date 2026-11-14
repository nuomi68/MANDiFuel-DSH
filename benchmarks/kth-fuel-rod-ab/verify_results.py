#!/usr/bin/env python3
"""用独立 ASCII 网格/场读者核对两组交付及 KTH 教材参考值；不启动求解器。"""
import argparse
import csv
from decimal import Decimal, InvalidOperation
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import sys

from independent_fields import read_case,foam,scalar_field

MESHES={'coarse':(30,10,2),'medium':(60,20,4),'fine':(120,40,8)}
QUANTITIES=['fuel_T_max_K','fuel_centerline_T_K','fuel_surface_T_K','clad_inner_T_K','clad_outer_T_K','delta_fuel_K','delta_gap_K','delta_clad_K','delta_convection_K','q_limit_W_per_m']


def load(path,default=None):
    return json.loads(path.read_text()) if path.exists() else default


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def add(checks,name,passed,**evidence):
    checks.append({'check':name,'passed':bool(passed),**evidence})


def finite(value): return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def check_case(row,workspace,starts,exits,reference):
    checks=[]; result={'id':row.get('id'),'claimed_status':row.get('status'),'checks':checks}
    name=row.get('id'); root=Path(row.get('result_root',''))
    if not root.is_absolute(): root=workspace/root
    root=root.resolve()
    if not root.is_relative_to(workspace.resolve()) or root==workspace.resolve(): raise ValueError('结果根不在当前算例工作区')
    result['result_root']=str(root)
    attempts=[s for s in starts if Path(s['cwd']).resolve()==root]
    completed=[e for e in exits if Path(e['cwd']).resolve()==root and e['kind']=='solve']
    code=completed[-1]['exit_code'] if completed else None
    log=(root/'log.offbeat').read_text(errors='replace') if (root/'log.offbeat').exists() else ''
    terminal=bool(log.strip()) and log.strip().splitlines()[-1].strip().lower()=='end'
    normal=code==0 and terminal and (root/'1/T').exists() and not foam.fatal_solver_log(log)
    result['normal_completion']=normal
    add(checks,'strict_normal_completion',normal,exit_code=code,terminal_marker=terminal,attempts=len(attempts))
    successful_statuses={'completed','success','succeeded','normal_completed','正常完成'}
    add(checks,'reported_status_matches_evidence',(str(row.get('status','')).lower() in successful_statuses)==normal,claimed=row.get('status'))
    if not (root/'1/T').exists(): return result
    data=read_case(root); quantities=data['quantities']; result['independent_quantities']=quantities
    result['mesh']=data['zones']; result['raw_field_cells']=data['field_cells']; result['field_fit_method']='独立多面体质心、燃料全区 T 对 r² 线性拟合；内部界面按两侧导热系数和法向距离重构。'
    expected_mesh=MESHES[name]
    add(checks,'requested_cell_counts',data['zones']['fuel']['cells']==expected_mesh[0] and data['zones']['clad']['cells']==expected_mesh[1] and ('gap' not in data['zones'] or data['zones']['gap']['cells']==expected_mesh[2]),actual={z:v['cells'] for z,v in data['zones'].items()})
    add(checks,'reported_cell_counts',row.get('fuel_cells')==expected_mesh[0] and row.get('clad_cells')==expected_mesh[1])
    add(checks,'height',math.isclose(data['height_m'],.1,rel_tol=1e-9,abs_tol=1e-12),height_m=data['height_m'])
    bounds={'fuel':(0.,.004125),'gap':(.004125,.004215),'clad':(.004215,.00485)}
    # A one-cell wedge replaces a curved section with planar faces; retain its
    # O(theta^2) geometric approximation explicitly rather than assuming exact radii.
    geometry_relative_tolerance=max(1e-9,1-math.cos(data['wedge_angle_rad']/2))
    for zone,limits in bounds.items():
        if zone not in data['zones']: continue
        actual=data['zones'][zone]
        passed=all(math.isclose(actual[key],target,rel_tol=geometry_relative_tolerance+1e-8,abs_tol=1e-12) for key,target in zip(['radius_min_m','radius_max_m'],limits))
        add(checks,'geometry_'+zone,passed,actual_radii_m=[actual['radius_min_m'],actual['radius_max_m']],nominal_radii_m=limits,wedge_relative_tolerance=geometry_relative_tolerance)
    for zone,target in [('fuel',2.5),('gap',.6),('clad',11.)]:
        if zone in data['zones']:
            actual=data['zones'][zone]
            add(checks,'conductivity_'+zone,math.isclose(actual['k_min'],target,abs_tol=1e-10) and math.isclose(actual['k_max'],target,abs_tol=1e-10),actual=[actual['k_min'],actual['k_max']])
    control=foam.read_foam(root/'system/controlDict'); schemes=foam.read_foam(root/'system/fvSchemes'); solver=foam.read_foam(root/'constant/solverDict')
    add(checks,'time_discretization',schemes['ddtSchemes'].get('default')==['steadyState'])
    add(checks,'time_and_write_settings',float(control['endTime'][0])==1 and control.get('userTime',{}).get('type',['seconds'])==['seconds'] and int(control.get('writePrecision',['6'])[0])>=10)
    add(checks,'disabled_nonthermal_models',solver.get('burnup')==['none'] and solver.get('gapGas')==['none'] and solver.get('fgr')==['none'] and solver.get('mechanicsSolver') in [['fromLatestTime'],['constant']])
    hs=solver['heatSourceOptions']; source=solver['heatSource'][0]
    if source=='constantLhgr': power_ok=math.isclose(float(hs['lhgr'][0]),41000,abs_tol=1e-9)
    elif source=='timeDependentLhgr':
        power_ok,_=foam.constant_power_on_interval(foam.sequence(hs['timePoints']),foam.sequence(hs['lhgr']),41000)
    else: power_ok=False
    add(checks,'linear_power_and_source_material',power_ok and hs.get('materials')==['(','fuel',')'],source=source)
    temps=foam.read_foam(root/'0/T')['boundaryField']
    convective=[v for v in temps.values() if v.get('type')==['convectiveHTC']]
    add(checks,'coolant_robin_boundary',len(convective)==1 and convective[0].get('h',[''])[0]=='uniform' and math.isclose(float(convective[0]['h'][1]),45000,abs_tol=1e-10) and convective[0].get('T0',[''])[0]=='uniform' and math.isclose(float(convective[0]['T0'][1]),600,abs_tol=1e-10))
    if (root/'1/Q').exists():
        qvalues,_=scalar_field(root/'1/Q',data['field_cells'])
        fuel_power=sum(p['volume_m3']*qvalues[p['cell']] for p in data['profiles'] if p['zone']=='fuel')
        nonfuel_power=sum(abs(p['volume_m3']*qvalues[p['cell']]) for p in data['profiles'] if p['zone']!='fuel')
        equivalent_power=fuel_power*2*math.pi/(data['wedge_angle_rad']*data['height_m'])
        result['actual_heat_source_W_per_m']=equivalent_power
        add(checks,'heat_source_field',abs(equivalent_power/41000-1)<.001 and nonfuel_power<1e-8,equivalent_W_per_m=equivalent_power,nonfuel_heat_W=nonfuel_power)
    errors={}; claimed_errors={}
    for key,target in reference['independent_full_precision_reference'].items():
        value=quantities.get(key)
        if key=='fuel_centerline_T_K': tolerance=reference['tolerances']['centerline_absolute_K']
        elif key=='q_limit_W_per_m': tolerance=abs(target)*reference['tolerances']['q_limit_relative']
        elif key.startswith('delta_'): tolerance=max(reference['tolerances']['drop_absolute_floor_K'],abs(target)*reference['tolerances']['drop_relative'])
        else: tolerance=reference['tolerances']['surface_absolute_K']
        passed=finite(value) and abs(value-target)<=tolerance
        errors[key]={'reference':target,'independent':value,'absolute_error':abs(value-target) if finite(value) else None,'relative_error':(value-target)/target if finite(value) else None,'tolerance':tolerance,'passed':passed}
        claimed=row.get(key)
        claimed_errors[key]={'claimed':claimed,'absolute_error':abs(claimed-target) if finite(claimed) else None,'passed':finite(claimed) and abs(claimed-target)<=tolerance}
    result['reference_comparison']=errors; result['claimed_reference_comparison']=claimed_errors
    add(checks,'fuel_max_from_raw_field',finite(row.get('fuel_T_max_K')) and abs(row['fuel_T_max_K']-quantities['fuel_T_max_K'])<=reference['tolerances']['raw_field_report_absolute_K'])
    outer=quantities.get('clad_outer_T_K'); claimed_outer=row.get('clad_outer_T_K')
    add(checks,'outer_surface_from_raw_field',finite(outer) and finite(claimed_outer) and abs(outer-claimed_outer)<=reference['tolerances']['raw_field_report_absolute_K'])
    add(checks,'reported_numeric_keys_present',all(finite(row.get(key)) for key in QUANTITIES))
    # Different legitimate cell-based extrapolations need not be bitwise equal.
    # Preserve discrepancies separately and use a one-kelvin provenance cross-check.
    crosscheck={key:abs(row[key]-value) for key,value in quantities.items() if key!='q_limit_W_per_m' and finite(value) and finite(row.get(key))}
    result['field_reconstruction_discrepancy_K']=crosscheck
    add(checks,'reported_temperatures_consistent_with_field',all(v<=1. for v in crosscheck.values()),discrepancies_K=crosscheck)
    result['input_and_delivery_passed']=all(c['passed'] for c in checks)
    result['reference_passed']=all(item['passed'] for item in errors.values())
    result['claimed_reference_passed']=all(item['passed'] for item in claimed_errors.values())
    result['passed']=normal and result['input_and_delivery_passed'] and result['reference_passed']
    result['profiles']=data['profiles']
    return result


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('run_root',type=Path); args=parser.parse_args()
    root=args.run_root.resolve(); reference=load(root/'references/reference-values.json')
    output={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'run_root':str(root),'reference':reference,'arms':{}}
    comparison=[]
    for arm in ['bare','skill']:
        workspace=root/arm/'workspace'; starts=lines(workspace/'solver-starts.jsonl'); exits=lines(workspace/'solver-exits.jsonl')
        submission=load(workspace/'results.json',{})
        rows=submission.get('cases',[]) if isinstance(submission,dict) else submission
        checks=[]
        add(checks,'start_budget',len(starts)<=5,actual=len(starts))
        add(checks,'requested_mesh_ids',sorted(r.get('id','') for r in rows)==sorted(MESHES))
        add(checks,'required_outputs',all((workspace/p).is_file() for p in ['results.json','results.csv','report.md']))
        csv_errors=[]
        csv_path=workspace/'results.csv'
        if csv_path.exists() and rows:
            try:
                with csv_path.open() as stream: csv_rows=list(csv.DictReader(stream))
                csv_map={r.get('id'):r for r in csv_rows}
                if len(csv_rows)!=len(rows) or set(csv_map)!={r['id'] for r in rows}:
                    csv_errors.append('CSV点身份与JSON不一致')
                for r in rows:
                    for key in QUANTITIES:
                        try:
                            text=csv_map.get(r['id'],{}).get(key,'')
                            decimal=Decimal(text)
                            tolerance=float(Decimal(10)**decimal.as_tuple().exponent)*.51+1e-8
                            if not finite(r.get(key)) or abs(float(decimal)-r[key])>tolerance:
                                csv_errors.append(f'{r["id"]}/{key} 数值不一致')
                        except (ValueError,TypeError,InvalidOperation):
                            csv_errors.append(f'{r["id"]}/{key} 缺失或非数值')
            except Exception as exc: csv_errors.append(str(exc))
            add(checks,'csv_matches_json',not csv_errors,errors=csv_errors)
        result={'actual_starts':len(starts),'normal_exit_count':sum(e['kind']=='solve' and e['exit_code']==0 for e in exits),'run':load(root/arm/'run.json'),'checks':checks,'cases':[]}
        for row in rows:
            try: record=check_case(row,workspace,starts,exits,reference)
            except Exception as e: record={'id':row.get('id'),'passed':False,'verification_error':str(e),'checks':[]}
            profiles=record.pop('profiles',[])
            if profiles:
                out=root/f'{arm}-{row.get("id")}-independent-profile.csv'
                with out.open('w') as f:
                    writer=csv.DictWriter(f,fieldnames=list(profiles[0])); writer.writeheader(); writer.writerows(profiles)
            result['cases'].append(record)
            for key,item in record.get('reference_comparison',{}).items():
                comparison.append({'arm':arm,'mesh':row['id'],'quantity':key,'claimed':row.get(key),'independent':item['independent'],'reference':item['reference'],'absolute_error':item['absolute_error'],'tolerance':item['tolerance'],'passed':item['passed']})
        result['normal_completed']=sum(c.get('normal_completion',False) for c in result['cases'])
        result['fine_reference_passed']=next((c.get('reference_passed',False) for c in result['cases'] if c.get('id')=='fine'),False)
        result['all_delivery_checks_passed']=all(c['passed'] for c in checks) and len(result['cases'])==3 and all(c.get('input_and_delivery_passed',False) for c in result['cases'])
        output['arms'][arm]=result
    (root/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    if comparison:
        with (root/'reference-comparison.csv').open('w') as f:
            writer=csv.DictWriter(f,fieldnames=list(comparison[0])); writer.writeheader(); writer.writerows(comparison)
    print(json.dumps({arm:{key:value[key] for key in ['actual_starts','normal_completed','fine_reference_passed','all_delivery_checks_passed']} for arm,value in output['arms'].items()},ensure_ascii=False))


if __name__=='__main__': main()
