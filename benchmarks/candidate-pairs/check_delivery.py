#!/usr/bin/env python3
"""Cross-check delivered tables with actual fields and preserved restart inputs."""
import argparse
import copy
import csv
import importlib.util
import json
import math
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
reader=HERE/'reference_reader.py'
if not reader.exists(): reader=HERE.parent/'fuel-rod-power-ab/verify_results.py'
spec=importlib.util.spec_from_file_location('foam_delivery_reader',reader); foam=importlib.util.module_from_spec(spec); spec.loader.exec_module(foam)


def normalized(name): return name.lower().replace('μ','u').replace('µ','u').replace('micrometers','um').replace('microns','um')
def read(path): return json.loads(path.read_text())


def csv_check(path,raw_final):
    with path.open(newline='') as stream:
        table=list(csv.DictReader(stream)); headers=list(table[0]) if table else []
    names={normalized(h):h for h in headers}; pairs=[]
    for name,header in names.items():
        if name.endswith('_m') and name[:-2]+'_um' in names: pairs.append((header,names[name[:-2]+'_um']))
        elif name.endswith('(m)') and name[:-3]+'(um)' in names: pairs.append((header,names[name[:-3]+'(um)']))
    checked=0; errors=[]; final_matches=[]
    for i,row in enumerate(table,2):
        for meters,microns in pairs:
            try: a=float(row[meters]); b=float(row[microns])
            except (ValueError,TypeError): continue
            checked+=1
            if not math.isfinite(a) or not math.isfinite(b) or not math.isclose(a*1e6,b,rel_tol=2e-6,abs_tol=1e-6): errors.append({'line':i,'m_column':meters,'um_column':microns,'m':a,'um':b})
    if table:
        for meters,_ in pairs:
            name=normalized(meters)
            if any(word in name for word in ['oxide','thick','mean']):
                try:
                    value=float(table[-1][meters]); final_matches.append({'column':meters,'last_m':value,'matches_raw_final':math.isclose(value,raw_final,rel_tol=2e-6,abs_tol=1e-11)})
                except (ValueError,TypeError): pass
    return {'rows':len(table),'columns':headers,'unit_pairs_checked':checked,'unit_errors':errors,'last_row_boundary_checks':final_matches}


def compare_checkpoint(actual):
    normal=actual['normal_segments']
    first=next((e for e in actual['executions'] if e['id'] in normal['B_first']),None)
    second=next((e for e in actual['executions'] if e['id'] in normal['B_second']),None)
    if not first or not second: return {'checked':False,'reason':'缺少独立正常B第一段或续算段'}
    source=Path(first['evidence_dir'])/'after/latest-state/788400'
    target=Path(second['evidence_dir'])/'before/latest-state/788400'
    d1=foam.read_foam(source/'D'); d2=foam.read_foam(target/'D')
    internal=foam.equivalent(d1['internalField'],d2['internalField'])
    pressure=[]
    for side,d in [('checkpoint',d1),('restart',d2)]:
        d.pop('FoamFile',None)
        for patch,bc in d.get('boundaryField',{}).items():
            removed={k:bc.pop(k) for k in list(bc) if k.startswith('coolantPressureList')}
            if removed: pressure.append({'side':side,'patch':patch,'entries':removed})
    return {'checked':True,'state_files':actual['checkpoint_carry'],'internal_D_identical':internal,'D_equal_after_excluding_pressure_serialization':foam.equivalent(d1,d2),'pressure_entries':pressure,'note':'排除压力表字典仅用于确认其余D状态；压力表修复本身仍需保留原始记录。'}


def main():
    p=argparse.ArgumentParser(); p.add_argument('run_root',type=Path); args=p.parse_args(); root=args.run_root.resolve(); verified=read(root/'verification.json'); result={'C04':{},'W01':{}}
    for arm in verified['tasks'].get('C04',{}):
        actual=verified['tasks']['C04'][arm]
        if not actual.get('final_oxide'):
            result['C04'][arm]={'checked':False,'reason':'没有正常终态氧化层场'}; continue
        case=Path(actual['result_root']); target=actual['final_oxide']['mean_m']; tables=[]
        for path in sorted((root/'C04'/arm/'workspace').rglob('*.csv')):
            if any(p in {'source-case','sources','execution-evidence','polyMesh'} for p in path.parts):continue
            if not any(word in path.name.lower() for word in ['oxide','thick','history']): continue
            checked=csv_check(path,target); checked['file']=str(path.relative_to(root)); tables.append(checked)
        result['C04'][arm]={'checked':True,'raw_final_boundary_m':target,'tables':tables,'initial_oxide_field_exists':(case/'0/oxideThickness').exists(),'actual_field_history_count':len(actual['saved_field_history'])}
    for arm in verified['tasks'].get('W01',{}): result['W01'][arm]=compare_checkpoint(verified['tasks']['W01'][arm])
    (root/'delivery-consistency.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'C04':{arm:sum(len(t['unit_errors']) for t in d.get('tables',[])) for arm,d in result['C04'].items()},'W01':{arm:d.get('checked') for arm,d in result['W01'].items()}},ensure_ascii=False))


if __name__=='__main__': main()
