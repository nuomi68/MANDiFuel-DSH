#!/usr/bin/env python3
"""独立回读保留场与交付表；原生几何后处理只写临时副本，无OFFBEAT启动。"""
import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'benchmarks/candidate-pairs'))
import evaluate_suite as api
spec=importlib.util.spec_from_file_location('geometry_review',ROOT/'benchmarks/generalization-20261114/verify_numeric.py')
geo=importlib.util.module_from_spec(spec);spec.loader.exec_module(geo)


def csvs(work):
    out=[]
    for p in work.rglob('*.csv'):
        if any(x in ('source-case','sources','execution-evidence','polyMesh') for x in p.relative_to(work).parts):continue
        try:
            with p.open() as f:rows=list(csv.DictReader(f))
            if rows:out.append((p,rows))
        except (ValueError,UnicodeError,csv.Error):continue
    return out


def field_values(case,name,count):
    values=api.field(case/name)
    flat=values['values']*count if values['uniform'] else values['values']
    assert len(flat)==count*values['components'],(case,name,len(flat),count)
    return flat


def c05(actual,work):
    case=Path(actual['result_root']);saved={float(t):p for t,p in api.times(case)};terminal=saved[max(saved)]
    scalar=api.field(terminal/'epsilonCreep');count=scalar['count']
    probe={}
    for p in (case/'postProcessing').glob('probes/*/epsilonCreep'):
        for line in p.read_text().splitlines():
            if line.strip().startswith('#'):continue
            values=re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?',line)
            if len(values)==7:probe[float(values[0])]=[float(x) for x in values[1:]]
    checked=0;errors=[];covered=[]
    for path,rows in csvs(work):
        columns=rows[0];time=next((x for x in columns if x in ('time_s','t_s')),None)
        names=[x for x in columns if re.search(r'(?:eps|epsilon).*creep.*xx',x,re.I) and not re.search('min|max|trace',x,re.I)]
        if not time or not names:continue
        used=0
        for row in rows:
            t=float(row[time]);expected=None
            if t in saved and (saved[t]/'epsilonCreep').is_file():
                f=api.field(saved[t]/'epsilonCreep');xs=f['values'][::6];expected=math.fsum(xs)/len(xs)
            elif t in probe:expected=probe[t][0]
            if expected is None:continue
            for key in names:
                value=float(row[key]);checked+=1;used+=1
                if not math.isclose(value,expected,rel_tol=5e-5,abs_tol=1e-10):errors.append({'file':str(path.relative_to(work)),'time_s':t,'column':key,'actual':value,'raw':expected})
        covered.append({'file':str(path.relative_to(work)),'rows':len(rows),'numeric_values_checked':used})
    native={}
    for name in ('epsilon','epsEl','epsilonCreep'):
        item=api.field(terminal/name);values=item['values'][::6]
        native[name+'_xx']={'min':min(values),'max':max(values),'mean':math.fsum(values)/len(values)}
    return {'numeric_values_checked':checked,'errors':errors,'tables':covered,'final_raw_fields':native,'raw_probe_times':len(probe),'scope':'历史交付与实际写出场/原生探针的xx分量核对；应变闭合见主核对，未和理论常数评分。'}


def c08(actual,work,dest):
    case=Path(actual['result_root']);vol,xyz,zones,vertices=geo.geometric_fields(case,dest)
    truth=geo.c08(case,vol,xyz,zones,vertices);history={row['time_s']:row for row in truth['history']}
    solver=api.foam.read_foam(case/'constant/solverDict');checked=0;errors=[]
    columns={'fuel_dE_J':lambda r:r['regions']['fuel']['delta_energy_J'],'clad_dE_J':lambda r:r['regions']['cladding']['delta_energy_J'],'cladding_dE_J':lambda r:r['regions']['cladding']['delta_energy_J'],'total_dE_J':lambda r:r['delta_total_energy_J'],'domain_dE_J':lambda r:r['delta_total_energy_J']}
    for prefix,zone in [('fuel','fuel'),('clad','cladding'),('cladding','cladding')]:
        for stat in ('min','max'):
            columns[prefix+'_T_'+stat+'_K']=lambda row,z=zone,s=stat:row['regions'][z]['T_'+s+'_K']
        rho=api.number(solver['materials'][zone]['rho']);cp=api.number(solver['materials'][zone]['Cp'])
        columns[prefix+'_T_avg_K']=lambda row,z=zone,rho=rho,cp=cp:300+row['regions'][z]['delta_energy_J']/(rho*cp*row['regions'][z]['volume_m3'])
    for path,rows in csvs(work):
        if 'time_s' not in rows[0]:continue
        for row in rows:
            t=float(row['time_s']);raw=history.get(t)
            if raw is None:continue
            expected={key:fn(raw) for key,fn in columns.items() if key in row}
            power=next((item['integral_W'] for item in raw['volumetric_power_fields'] if item['field']=='Q'),None)
            if power is not None:
                for key in ('Q_in_J','cumulative_input_J'):
                    if key in row:expected[key]=power*t
            for key,value in expected.items():
                number=float(row[key]);checked+=1
                if not math.isclose(number,value,rel_tol=5e-5,abs_tol=1e-6):errors.append({'file':str(path.relative_to(work)),'time_s':t,'column':key,'actual':number,'raw':value})
    return {'numeric_values_checked':checked,'errors':errors,'raw_history':truth,'scope':'温度、实际单元区rho*Cp*DeltaT*V积分及实际Q体积分累计输入；原生C/V仅在临时副本生成。'}


def f02(actual,work,dest):
    checked=0;errors=[];cases={}
    for label,entry in actual['pressure_cases'].items():
        case=Path(entry['result_root']);end=next(p for t,p in api.times(case) if float(t)==1)
        folder=dest/label;folder.mkdir(exist_ok=True)
        vol,xyz,zones,vertices=geo.geometric_fields(case,folder);n=len(vol)
        s=field_values(end,'sigma',n);d=field_values(end,'D',n);expected=[]
        for i,(x,y,z) in enumerate(xyz):
            radius=math.hypot(x,y);a=x/radius;b=y/radius;xx,xy,xz,yy,yz,zz=s[6*i:6*i+6]
            expected.append({'r_m':radius,'sigma_rr_Pa':xx*a*a+2*xy*a*b+yy*b*b,'sigma_tt_Pa':xx*b*b-2*xy*a*b+yy*a*a,'u_r_m':d[3*i]*a+d[3*i+1]*b})
        matched=0;maximum={k:0 for k in ('sigma_rr_Pa','sigma_tt_Pa','u_r_m')}
        for path,rows in csvs(work):
            first=rows[0]
            if path.name.startswith('xyGraph') or 'analytic' in path.name or path.name.startswith('validation'):continue
            if not any(k in first for k in ('cell','cell_local_index')):continue
            for row in rows:
                case_id=row.get('case_id',row.get('case',''))
                if case_id and case_id!='p'+label.replace('MPa',''):continue
                if not case_id and 'p'+label.replace('MPa','') not in str(path):continue
                if row.get('location') and not row['location'].endswith('_side_cell'):continue
                try:i=int(row.get('cell_local_index',row.get('cell')))
                except (TypeError,ValueError):continue
                if not 0<=i<n:errors.append({'file':str(path.relative_to(work)),'invalid_cell_label':i});continue
                zone=row.get('material_zone',row.get('zone'))
                if 'cell_local_index' in row:
                    if zone not in zones or i>=len(zones[zone]):
                        errors.append({'file':str(path.relative_to(work)),'invalid_local_cell_index':i,'zone':zone});continue
                    i=zones[zone][i]
                raw=expected[i]
                if zone and zone in zones and i not in zones[zone]:errors.append({'file':str(path.relative_to(work)),'cell':i,'invalid_zone':zone})
                mapping={'sigma_rr_Pa':'sigma_rr_Pa','sigma_tt_Pa':'sigma_tt_Pa','sigma_theta_Pa':'sigma_tt_Pa','u_r_m':'u_r_m','t_r_Pa':'sigma_rr_Pa'}
                for key,ref in mapping.items():
                    if key not in row:continue
                    value=float(row[key]);delta=abs(value-raw[ref]);maximum[ref]=max(maximum[ref],delta);checked+=1;matched+=1
                    if not math.isclose(value,raw[ref],rel_tol=3e-4,abs_tol=1e-10 if ref=='u_r_m' else 50):
                        if len(errors)<30:errors.append({'file':str(path.relative_to(work)),'cell':i,'column':key,'actual':value,'raw':raw[ref]})
        cases[label]={'numeric_values_checked':matched,'max_absolute_projection_difference':maximum,'cells':n}
    return {'numeric_values_checked':checked,'errors':errors,'cases':cases,'scope':'按真实单元ID、材料区与坐标，将笛卡尔sigma/D独立投影到圆柱径向/环向；匹配近界面单元数据，不将单元中心等同精确界面面值。'}


def main():
    p=argparse.ArgumentParser();p.add_argument('run_root',type=Path);p.add_argument('--ids',nargs='+');args=p.parse_args();root=args.run_root.resolve()
    verify=json.loads((root/'verification.json').read_text());out=root/'数值独立复核';out.mkdir(exist_ok=True);result=json.loads((out/'复核数据.json').read_text())['tasks'] if args.ids and (out/'复核数据.json').exists() else {}
    for tid,pair in verify['tasks'].items():
        if args.ids and tid not in args.ids:continue
        result[tid]={}
        for arm,actual in pair.items():
            folder=out/(tid+'_'+arm);folder.mkdir(exist_ok=True)
            try:
                if tid=='C05' and actual.get('result_root'):v=c05(actual,root/tid/arm/'workspace')
                elif tid=='C08' and actual.get('result_root'):v=c08(actual,root/tid/arm/'workspace',folder)
                elif tid=='F02':v=f02(actual,root/tid/arm/'workspace',folder)
                else:v={'numeric_values_checked':0,'errors':[],'not_checked':'缺少所需正常结果'}
                v['status']='checked' if v['numeric_values_checked'] and not v['errors'] else 'mismatch' if v['errors'] else 'unverified'
            except Exception as e:v={'status':'unverified','error':str(e),'numeric_values_checked':0}
            result[tid][arm]=v
    record={'tasks':result,'organizer_OFFBEAT_starts':0,'network_calls':0,'retained_results_modified':False}
    (out/'复核数据.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({tid:{arm:{k:v.get(k) for k in ('status','numeric_values_checked','error')} for arm,v in pair.items()} for tid,pair in result.items()},ensure_ascii=False))

if __name__=='__main__':main()
