"""Read-only quality checks, with independent stdlib OpenFOAM/mesh readers."""
import argparse,ast,csv,hashlib,importlib.util,json,math,re,sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('independent_foam',REPO/'benchmarks/fuel-rod-power-ab/verify_results.py')
foam=importlib.util.module_from_spec(spec);spec.loader.exec_module(foam)

def load(p,default=None):return json.loads(p.read_text()) if p.is_file() else default
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.is_file() else []
def check(out,name,passed,**evidence):out.append({'check':name,'passed':bool(passed),**evidence})
def number(tokens):return float(tokens[-1])
def close(a,b):return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12)

def counted(path,kind):
    words=foam.tokens(path.read_text());i=foam.matching(words,1,'{','}')+1;n=int(words[i]);i+=2;out=[]
    for _ in range(n):
        if kind=='point':out.append(tuple(map(float,words[i+1:i+4])));i+=5
        elif kind=='face':
            size=int(words[i]);out.append(tuple(map(int,words[i+2:i+2+size])));i+=size+3
        else:out.append(int(words[i]));i+=1
    return out

def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])

def geometry(mesh):
    points=counted(mesh/'points','point');faces=counted(mesh/'faces','face');owner=counted(mesh/'owner','label');neighbour=counted(mesh/'neighbour','label')
    cell_faces=[[] for _ in range(1+max(owner+neighbour))]
    for i,c in enumerate(owner):cell_faces[c].append(i)
    for i,c in enumerate(neighbour):cell_faces[c].append(i)
    volumes=[];centres=[]
    for indices in cell_faces:
        vertices={p for f in indices for p in faces[f]};origin=tuple(sum(points[p][j] for p in vertices)/len(vertices) for j in range(3));volume=0.;moment=[0.,0.,0.]
        for f in indices:
            polygon=faces[f];a=points[polygon[0]]
            for i in range(1,len(polygon)-1):
                b,c=points[polygon[i]],points[polygon[i+1]];v=abs(dot(sub(a,origin),cross(sub(b,origin),sub(c,origin))))/6
                volume+=v
                for j in range(3):moment[j]+=v*(origin[j]+a[j]+b[j]+c[j])/4
        if volume<=0:raise ValueError('Nonpositive cell volume')
        volumes.append(volume);centres.append(tuple(x/volume for x in moment))
    return volumes,centres

def prep(work,source):
    checks=[];target=work/'target-case';check(checks,'target_case_exists',target.is_dir())
    if not (target/'rodDict').is_file():return {'passed':False,'checks':checks}
    original=ast.literal_eval((source/'rodDict').read_text());actual=ast.literal_eval((target/'rodDict').read_text());factor=float(actual['convertToMeters'])
    for key,value in [('rOuterFuel',.00415),('rInnerClad',.00428),('rOuterClad',.00488)]:check(checks,key,len(actual[key])==len(original[key]) and all(close(float(v)*factor,value) for v in actual[key]),values_m=[v*factor for v in actual[key]])
    excluded={'rOuterFuel','rInnerClad','rOuterClad','convertToMeters'}
    check(checks,'other_geometry_and_discretization_preserved',foam.equivalent({k:v for k,v in original.items() if k not in excluded},{k:v for k,v in actual.items() if k not in excluded}))
    solver=foam.read_foam(target/'constant/solverDict');base=foam.read_foam(source/'constant/solverDict')
    for key,value in [('DiamCold',.0083),('GapCold',.00026)]:
        observed=number(solver['materials']['fuel'][key]);check(checks,key,close(observed,value),observed_m=observed)
        solver['materials']['fuel'].pop(key);base['materials']['fuel'].pop(key)
    check(checks,'other_materials_and_loads_preserved',foam.equivalent(solver,base))
    required=[p.relative_to(source) for p in source.rglob('*') if p.is_file()]
    check(checks,'complete_input_copy',all((target/p).is_file() for p in required))
    check(checks,'preparation_record',any(p.is_file() for p in [work/'prepare.json',target/'prepare.json']))
    check(checks,'zero_solver_starts',not rows(work/'solver-starts.jsonl'))
    check(checks,'no_generated_target_mesh',not (target/'constant/polyMesh/points').exists())
    return {'passed':all(c['passed'] for c in checks),'checks':checks}

def solve(work,expected_powers):
    checks=[];cases=[]
    for start in rows(work/'solver-starts.jsonl'):
        evidence=work/'execution-evidence'/start['id'];exit_=load(evidence/'exit.json',{});case=Path(start['case_root']);before=evidence/'before'
        log=(evidence/'solver.log').read_text(errors='replace') if (evidence/'solver.log').is_file() else ''
        s=foam.read_foam(before/'constant/solverDict');control=foam.read_foam(before/'system/controlDict')
        powers=foam.sequence(s['heatSourceOptions']['lhgr']);power=powers[0]
        entry={'id':start['id'],'case_root':str(case.relative_to(work)),'power_W_per_m':power,'normal':exit_.get('exit_code')==0 and log.rstrip().splitlines()[-1].strip().lower()=='end' and not foam.fatal_solver_log(log),'checks':[]}
        if '.mandifuel-tmp' in case.relative_to(work).parts:
            entry.update(role='diagnostic_temporary_case',passed=False);cases.append(entry);continue
        cs=entry['checks'];check(cs,'constant_requested_power',power in expected_powers and all(close(p,power) for p in powers))
        base=foam.read_foam(work/'source-case/constant/solverDict');candidate=json.loads(json.dumps(s))
        for data in [base,candidate]:
            data.pop('FoamFile',None)
            for key in ['lhgr','timePoints']:data['heatSourceOptions'].pop(key,None)
        check(cs,'other_model_and_material_settings_preserved',foam.equivalent(base,candidate))
        check(cs,'normal_solver_exit',entry['normal'],exit_code=exit_.get('exit_code'))
        check(cs,'requested_time_controls',close(number(control['endTime']),1) and close(number(control['deltaT']),1))
        check(cs,'saved_terminal_field',(case/'1/T').is_file())
        boundary=foam.read_foam(before/'0/T')['boundaryField']['cladOuter'];check(cs,'outer_temperature_620K',boundary['type']==['fixedValue'] and close(number(boundary['value']),620))
        schemes=foam.read_foam(case/'system/fvSchemes');check(cs,'steady_discretization',schemes.get('ddtSchemes',{}).get('default')==['steadyState'])
        if (case/'1/T').is_file():
            mesh=case/'constant/polyMesh';volumes,centres=geometry(mesh);zones=foam.cell_zones(mesh/'cellZones');values,field=foam.internal_temperatures(case/'1/T',len(volumes));statistics={}
            for zone in ['fuel','cladding']:
                ids=zones[zone];maximum=max(values[i] for i in ids);minimum=min(values[i] for i in ids);mean=sum(values[i]*volumes[i] for i in ids)/sum(volumes[i] for i in ids);peak=next(i for i in ids if values[i]==maximum)
                statistics[zone]={'max_K':maximum,'min_K':minimum,'volume_mean_K':mean,'max_cell':peak,'max_cell_centre_m':centres[peak],'cells':len(ids),'volume_m3':sum(volumes[i] for i in ids)}
            entry.update(statistics=statistics,values=values,field_sha256=sha(case/'1/T'))
            check(cs,'valid_temperature_and_regions',all(math.isfinite(x) and x>0 for x in values) and len(zones['fuel'])==40 and len(zones['cladding'])==12)
        entry['passed']=all(c['passed'] for c in cs);cases.append(entry)
    for power in expected_powers:check(checks,'successful_power_'+str(power),any(c['power_W_per_m']==power and c['passed'] for c in cases))
    deliveries=[]
    for p in work.rglob('*'):
        if not p.is_file() or any(part in {'source-case','execution-evidence','.dsh','.mandifuel-tmp'} for part in p.relative_to(work).parts):continue
        if p.name=='result.json' or p.suffix=='.csv':deliveries.append({'path':str(p.relative_to(work)),'bytes':p.stat().st_size})
    check(checks,'result_json_present',any(Path(d['path']).name=='result.json' for d in deliveries))
    check(checks,'csv_present',any(Path(d['path']).suffix=='.csv' for d in deliveries))
    return {'passed':all(c['passed'] for c in checks),'checks':checks,'cases':cases,'deliveries':deliveries,'solver_starts':len(cases)}

def delivered(work,tid,arm,result):
    checks=[];errors=[];references={}
    path=work/'result.json'
    if not path.is_file():path=work/'results/result.json'
    data=load(path,{})
    def bind(power,root):
        case=Path(root);case=(case if case.is_absolute() else work/case).resolve()
        if not case.is_relative_to(work.resolve()):raise ValueError('Declared result root escapes task workspace')
        relative=str(case.relative_to(work));matches=[c for c in result['cases'] if c['passed'] and c['case_root']==relative and c['power_W_per_m']==power]
        if not matches:raise ValueError('Declared result has no matching successful execution: '+relative)
        references[power]=matches[-1]
    if tid=='T02':bind(18000,data['solver_session']['case_root'] if arm=='bare' else data['result_root'])
    else:
        for point in data['cases'] if arm=='bare' else data['points']:
            power=point['parameter']['lhgr_W_per_m'] if arm=='bare' else point['lhgr_W_per_m']
            bind(power,point['case_dir'] if arm=='bare' else point['result_root'])
    result['selected_cases']={str(power):c['case_root'] for power,c in references.items()}
    def compare(label,actual,expected,tolerance=.001):
        error=abs(float(actual)-expected);errors.append(error);check(checks,label,error<=tolerance,actual=actual,expected=expected,absolute_error=error,tolerance=tolerance)
    if tid=='T02':
        zones=data['results'] if arm=='bare' else data['zones'];expected=references[18000]['statistics']
        for zone in ['fuel','cladding']:
            for key,reported in [('max_K','T_max_K'),('min_K','T_min_K'),('volume_mean_K','T_volavg_K' if arm=='bare' else 'T_volume_weighted_mean_K')]:compare('json/'+zone+'/'+key,zones[zone][reported],expected[zone][key])
        coordinate=zones['fuel']['T_max_cell_center_m' if arm=='bare' else 'T_max_cell_centre_m']
        for axis,(actual,wanted) in enumerate(zip(coordinate,expected['fuel']['max_cell_centre_m'])):compare('json/maximum_coordinate/'+str(axis),actual,wanted,1e-8)
        path=work/'response.csv' if arm=='bare' else work/'results/responses.csv'
        table=list(csv.DictReader(path.open()))
        names={'temperature_max':'max_K','temperature_min':'min_K','temperature_volume_weighted_average':'volume_mean_K','T_max':'max_K','T_min':'min_K','T_volume_weighted_mean':'volume_mean_K'}
        seen=set()
        for row in table:
            zone=row.get('region',row.get('zone'));key=names.get(row.get('quantity'))
            if zone in expected and key:
                seen.add((zone,key));compare('csv/'+zone+'/'+key,row['value'],expected[zone][key]);check(checks,'csv/'+zone+'/'+key+'/unit',row['unit']=='K')
        check(checks,'csv/all_six_responses',len(seen)==6)
    else:
        points=data['cases'] if arm=='bare' else data['points']
        mapping={'fuel_max_T_K':('fuel','max_K'),'fuel_volAvg_T_K':('fuel','volume_mean_K'),'cladding_max_T_K':('cladding','max_K'),'cladding_volAvg_T_K':('cladding','volume_mean_K')} if arm=='bare' else {'fuel_T_max_K':('fuel','max_K'),'fuel_T_volavg_K':('fuel','volume_mean_K'),'cladding_T_max_K':('cladding','max_K'),'cladding_T_volavg_K':('cladding','volume_mean_K')}
        seen=set()
        for point in points:
            power=point['parameter']['lhgr_W_per_m'] if arm=='bare' else point['lhgr_W_per_m'];seen.add(power);responses=point['response'] if arm=='bare' else point
            for key,(zone,operation) in mapping.items():compare('json/'+str(power)+'/'+key,responses[key],references[power]['statistics'][zone][operation])
        check(checks,'json/all_three_points',seen=={12000,18000,24000})
        path=work/'results/parameter_state_response.csv' if arm=='bare' else work/'params-status-response.csv';table=list(csv.DictReader(path.open()));seen=set()
        for row in table:
            power=float(row['lhgr_W_per_m']);seen.add(power)
            for key,(zone,operation) in mapping.items():compare('csv/'+str(power)+'/'+key,row[key],references[power]['statistics'][zone][operation])
        check(checks,'csv/all_three_points',seen=={12000,18000,24000})
    result['delivery_checks']=checks;result['delivered_values_passed']=all(c['passed'] for c in checks);result['maximum_reported_value_absolute_error']=max(errors,default=0);result['passed']=result['passed'] and result['delivered_values_passed']
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('run_root',type=Path);args=parser.parse_args();root=args.run_root.resolve();out={'scope':'Independent input, exit, stored-field and mesh-statistics verification; does not start a solver or call a model. JSON and CSV quantities are checked against independently recomputed stored-field statistics (temperature tolerance 0.001 K, position 1e-8 m). Temporary diagnostic solver starts remain counted, but cannot satisfy a requested result.','tasks':{}}
    for tid in ['T01','T02','T03']:
        out['tasks'][tid]={}
        for arm in ['bare','skill']:
            work=root/tid/arm/'workspace'
            try:
                result=prep(work,root/tid/'source-case') if tid=='T01' else solve(work,[18000] if tid=='T02' else [12000,18000,24000])
                if tid!='T01' and result['passed']:result=delivered(work,tid,arm,result)
            except Exception as exc:result={'passed':False,'verification_error':str(exc)}
            out['tasks'][tid][arm]=result
    out['cross_arm_saved_fields']={}
    for tid,powers in [('T02',[18000]),('T03',[12000,18000,24000])]:
        pair=out['tasks'][tid];mapped={}
        for arm in ['bare','skill']:
            selected=set(pair[arm].get('selected_cases',{}).values());mapped[arm]={c['power_W_per_m']:c for c in pair[arm].get('cases',[]) if c['passed'] and c['case_root'] in selected}
        for power in powers:
            if all(power in mapped[a] for a in mapped):
                a=mapped['bare'][power]['values'];b=mapped['skill'][power]['values'];out['cross_arm_saved_fields'][tid+'/'+str(power)]={'cells':len(a),'same_size':len(a)==len(b),'max_absolute_temperature_difference_K':max(abs(x-y) for x,y in zip(a,b))}
    out['all_passed']=all(v['passed'] for pair in out['tasks'].values() for v in pair.values())
    (root/'verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'all_passed':out['all_passed'],'tasks':{k:{a:v['passed'] for a,v in p.items()} for k,p in out['tasks'].items()}},ensure_ascii=False))

if __name__=='__main__':main()
