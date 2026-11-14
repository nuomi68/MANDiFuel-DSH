#!/usr/bin/env python3
"""在结果的临时副本运行原生几何后处理，独立复核实际场；不启动OFFBEAT。"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'benchmarks/candidate-pairs'))
import evaluate_suite as api
foam=api.foam


def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def expanded(path,count):
 d=api.field(path)
 v=d['values']
 if d['uniform']:v=v*count
 if len(v)!=count*d['components']:raise ValueError(f'字段长度不匹配：{path}')
 return v,d


def geometric_fields(case,output):
 with tempfile.TemporaryDirectory(prefix='mandifuel-geometry-review-') as work:
  copy=Path(work)/'case';copy.mkdir()
  for name in ('0','constant','system'):shutil.copytree(case/name,copy/name)
  subprocess.run(['foamDictionary',str(copy/'system/controlDict'),'-disableFunctionEntries','-entry','functions','-set','{}'],capture_output=True,check=True)
  for function in ('writeCellVolumes','writeCellCentres'):
   with (output/(function+'.log')).open('w') as stream:
    subprocess.run(['postProcess','-case',str(copy),'-func',function,'-time','0'],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=90)
  volumes=api.field(copy/'0/V')['values'];centres=api.field(copy/'0/C')['values']
  count=len(volumes)
  assert count>0 and len(centres)==3*count and all(v>0 for v in volumes)
  xyz=[centres[i:i+3] for i in range(0,len(centres),3)]
  zones=foam.cell_zones(copy/'constant/polyMesh/cellZones')
  items=foam.tokens((copy/'constant/polyMesh/points').read_text());end=foam.matching(items,1,'{','}')
  points=[float(v) for v in items[end+3:] if v not in ('(',')',';')]
  assert len(points)==3*int(items[end+1])
  vertices=[points[i:i+3] for i in range(0,len(points),3)]
  return volumes,xyz,zones,vertices


def error(actual,expected):
 scale=max(abs(x) for x in expected)
 return {'max_absolute':max(abs(x-y) for x,y in zip(actual,expected)),
         'max_absolute_over_reference_max':max(abs(x-y) for x,y in zip(actual,expected))/scale}


def c02(case,terminal,volumes,xyz,zones,vertices):
 d,_=expanded(terminal/'D',len(xyz));s,_=expanded(terminal/'sigma',len(xyz))
 radii=[math.sqrt(sum(x*x for x in p)) for p in xyz]
 a=min(math.sqrt(sum(x*x for x in p)) for p in vertices);b=max(math.sqrt(sum(x*x for x in p)) for p in vertices)
 mat=foam.read_foam(case/'constant/solverDict')['materials']['buffer'];E=api.number(mat['E']);nu=api.number(mat['nu'])
 A=(60e6*a**3-120e6*b**3)/(b**3-a**3);B=(60e6-120e6)*a**3*b**3/(b**3-a**3)
 ur=[];rr=[];tt=[]
 for i,(point,r) in enumerate(zip(xyz,radii)):
  x,y,z=[p/r for p in point];u=d[i*3:i*3+3];xx,xy,xz,yy,yz,zz=s[i*6:i*6+6]
  ur.append(sum(ui*pi for ui,pi in zip(u,(x,y,z))))
  radial=xx*x*x+2*xy*x*y+2*xz*x*z+yy*y*y+2*yz*y*z+zz*z*z
  rr.append(radial);tt.append((xx+yy+zz-radial)/2)
 refu=[(1-2*nu)*A*r/E+(1+nu)*B/(2*E*r*r) for r in radii]
 refr=[A-B/r**3 for r in radii];reft=[A+B/(2*r**3) for r in radii]
 return {'scope':'实际单元中心，球坐标 e_r=x/|x|；切向为两个切向正应力平均；解析量仅作附加数值诊断，不替代主完成度检查',
         'r_inner_m':a,'r_outer_m':b,'cells':len(radii),'u_r_m':{'min':min(ur),'max':max(ur)},
         'sigma_rr_Pa':{'min':min(rr),'max':max(rr)},'sigma_tt_mean_Pa':{'min':min(tt),'max':max(tt)},
         'lame_cell_centre_error':{'u_r':error(ur,refu),'sigma_rr':error(rr,refr),'sigma_tt':error(tt,reft)}}


def c08(case,volumes,xyz,zones,vertices):
 solver=foam.read_foam(case/'constant/solverDict');count=len(volumes);out=[]
 for t,folder in api.times(case):
  if float(t)<=0:continue
  values,_=expanded(folder/'T',count);row={'time_s':float(t),'regions':{}}
  for zone in ('fuel','cladding'):
   ids=zones[zone];m=solver['materials'][zone];rho=api.number(m['rho']);cp=api.number(m['Cp'])
   row['regions'][zone]={'volume_m3':math.fsum(volumes[i] for i in ids),'T_min_K':min(values[i] for i in ids),'T_max_K':max(values[i] for i in ids),'delta_energy_J':rho*cp*math.fsum((values[i]-300)*volumes[i] for i in ids)}
  row['delta_total_energy_J']=math.fsum(x['delta_energy_J'] for x in row['regions'].values())
  power=[]
  for p in folder.iterdir():
   if not p.is_file():continue
   try:d=foam.read_foam(p)
   except Exception:continue
   if d.get('dimensions')==['[','1','-1','-3','0','0','0','0',']'] and d.get('FoamFile',{}).get('class')==['volScalarField']:
    q,_=expanded(p,count);power.append({'field':p.name,'integral_W':math.fsum(q[i]*volumes[i] for i in range(count))})
  row['volumetric_power_fields']=power
  out.append(row)
 return {'scope':'实际网格域；无气隙实体单元；rho*Cp*sum((T-300)*V)，单位J；原生postProcess在临时副本生成C/V',
         'cells':count,'zone_counts':{z:len(v) for z,v in zones.items()},'history':out}


def f01(case,terminal,volumes,xyz,zones,vertices):
 values,_=expanded(terminal/'T',len(volumes));fuel=zones['fuel'];v=math.fsum(volumes[i] for i in fuel)
 rho=[math.hypot(p[0],p[1]) for p in vertices]
 result={'actual_min_mesh_radius_m':min(rho),'actual_max_mesh_radius_m':max(rho),'fuel_volume_m3':v,
         'fuel_T_min_K':min(values[i] for i in fuel),'fuel_T_max_K':max(values[i] for i in fuel),
         'clad_T_min_K':min(values[i] for i in zones['cladding']),'clad_T_max_K':max(values[i] for i in zones['cladding'])}
 if (terminal/'k').is_file():
  k,_=expanded(terminal/'k',len(volumes));result['actual_fuel_k_W_mK']=[min(k[i] for i in fuel),max(k[i] for i in fuel)]
 return result


def main():
 p=argparse.ArgumentParser();p.add_argument('run_root',type=Path);p.add_argument('--ids',nargs='+');args=p.parse_args();root=args.run_root.resolve();v=json.loads((root/'verification.json').read_text());out=root/'数值独立复核';out.mkdir(exist_ok=True);old=out/'复核数据.json';data=json.loads(old.read_text())['tasks'] if old.exists() else {}
 for tid,pair in v['tasks'].items():
  if args.ids and tid not in args.ids:continue
  data[tid]={}
  for arm,actual in pair.items():
   cases=[]
   if tid in ('C02','C08') and actual.get('result_root'):cases=[('case',Path(actual['result_root']))]
   elif tid=='F01':cases=[(name,Path(item['result_root'])) for name,item in actual.get('hole_cases',{}).items()]
   data[tid][arm]={}
   for name,case in cases:
    dest=out/(tid+'_'+arm+'_'+name);dest.mkdir(exist_ok=True)
    try:
     vol,xyz,zones,vertices=geometric_fields(case,dest)
     terminal=max(api.times(case),key=lambda x:x[0])[1]
     value={'C02':c02,'C08':c08,'F01':f01}[tid](case,terminal,vol,xyz,zones,vertices) if tid!='C08' else c08(case,vol,xyz,zones,vertices)
     data[tid][arm][name]={'status':'checked','result_root':str(case),**value}
    except Exception as e:data[tid][arm][name]={'status':'unverified','error':str(e),'result_root':str(case)}
 save(out/'复核数据.json',{'scope':'只读保留实际场，原生几何后处理仅操作临时副本；不启动OFFBEAT','tasks':data,'organizer_solver_starts':0})
 print(json.dumps({tid:{a:{n:x['status'] for n,x in cases.items()} for a,cases in pair.items()} for tid,pair in data.items()},ensure_ascii=False))

if __name__=='__main__':main()
