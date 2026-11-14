#!/usr/bin/env python3
"""将公开剖面与库存表回对原生实际场；只读，不重算物理。"""
import bisect
import csv
import importlib.util
import json
import math
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('native_review',HERE/'evaluate.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)


def closest(sorted_radius,value):
    k=bisect.bisect_left(sorted_radius,value)
    return min((max(0,k-1),min(len(sorted_radius)-1,k)),key=lambda i:abs(sorted_radius[i]-value))


def main():
 root=Path(sys.argv[1]).resolve();verified=api.load(root/'verification.json');result={};total=0
 for tid,pair in verified['tasks'].items():
  result[tid]={}
  for arm,actual in pair.items():
   work=root/tid/arm/'workspace';cases=[]
   for item in actual['case_checks']:
    if item['passed']:
     e=next(e for e in actual['executions'] if e['id']==item['event_id']);mesh=api.load(root/'独立几何核对'/e['id']/'geometry.json');cases.append((item,e,mesh))
   checked=0;errors=[];files=[]
   for catalog in actual['data_tables']:
    path=work/catalog['file']
    with path.open() as stream:rows=list(csv.DictReader(stream))
    if not rows:continue
    key=rows[0];candidate=None
    if tid=='G01' and 'T_K' in key and ('cell' in key or 'cell_label' in key):
     wanted=[40,12] if re_search('fine|mesh40',str(path)) else [20,6]
     candidate=next((x for x in reversed(cases) if x[0]['radial_counts']==wanted),None)
    elif tid=='G02' and 'radial_profile' in path.name and ('u_r_m' in key or 'u_r_um' in key):
     for x in reversed(cases):
      name=Path(x[0]['case_root']).name
      if path.parent.name==name or path.name.startswith(name+'_'):candidate=x;break
    elif tid=='M01' and any(k in key for k in ('Cs_mol_per_m3','Cs_numeric_mol_per_m3','cs_mol_per_m3','Cs_mol_m3','release_fraction','cumulative_release_fraction')):
     for x in reversed(cases):
      try:path.relative_to(Path(x[0]['case_root']));candidate=x;break
      except ValueError:pass
     if candidate is None and arm=='skill':candidate=cases[-1]
    if candidate is None:continue
    item,event,mesh=candidate;n=mesh['cells'];end=api.terminal(event);xyz=mesh['xyz'];radii=[math.hypot(*p[:2]) if tid=='G01' else math.sqrt(sum(v*v for v in p)) for p in xyz];order=sorted(range(n),key=lambda i:radii[i]);sorted_r=[radii[i] for i in order]
    if tid=='G01':native=api.scalar_frame(end/'T',n)
    elif tid=='G02':
     D=api.vector_frame(end/'D',n,3);S=api.vector_frame(end/'sigma',n,6);native=[]
     for p,r,u,s in zip(xyz,radii,D,S):
      a,b,c=[x/r for x in p];xx,xy,xz,yy,yz,zz=s;rr=xx*a*a+2*xy*a*b+2*xz*a*c+yy*b*b+2*yz*b*c+zz*c*c
      native.append((sum(x*y/r for x,y in zip(u,p)),rr,(xx+yy+zz-rr)/2))
    else:native=api.scalar_frame(end/'Cs',n)
    in_file=0
    for row in rows:
     values={}
     if tid=='M01' and any(k in row for k in ('release_fraction','cumulative_release_fraction')):
      time_key='time_s';time=float(row[time_key]);folder=Path(event['case_root'])/format(time,'.12g')
      if not folder.is_dir():folder=next((p for t,p in api.base.times(Path(event['case_root'])) if math.isclose(float(t),time,abs_tol=1e-6)),None)
      if time==0:mean=0.6
      elif folder is not None and (folder/'Cs').exists():
       cs=api.scalar_frame(folder/'Cs',n);mean=math.fsum(c*v for c,v in zip(cs,mesh['volumes']))/math.fsum(mesh['volumes'])
      else:continue
      volume=math.fsum(mesh['volumes']);whole=4*math.pi/3*(350e-6)**3
      for k in ('release_fraction','cumulative_release_fraction'):
       if k in row:values[k]=(1-mean/.6,1e-6,2e-7)
      for k in ('M_mesh_mol','cs_inventory_in_computational_domain_mol'):
       if k in row:values[k]=(mean*volume,1e-6,1e-20)
      for k in ('M_kernel_mol','cs_inventory_whole_sphere_equivalent_mol'):
       if k in row:values[k]=(mean*whole,1e-5,1e-18)
     else:
      if tid=='G01':
       try:i=int(row.get('cell_label',row.get('cell')))
       except (TypeError,ValueError):continue
       if not 0<=i<n:continue
       values['T_K']=(native[i],1e-6,1e-5)
      else:
       if 'time_s' in row and not math.isclose(float(row['time_s']),30000,abs_tol=1e-6):continue
       r=float(row['r_m']) if 'r_m' in row else float(row['r_mm'])*.001
       i=order[closest(sorted_r,r)]
       if tid=='G02':
        for key,idx,scale,absolute in [('u_r_m',0,1,1e-11),('u_r_um',0,1e6,1e-5),('sigma_r_Pa',1,1,100),('sigma_rr_MPa',1,1e-6,1e-4),('sigma_t_mean_Pa',2,1,100),('sigma_t_MPa',2,1e-6,1e-4)]:
         if key in row:values[key]=(native[i][idx]*scale,1e-5,absolute)
       else:
        for key in ('Cs_mol_per_m3','Cs_numeric_mol_per_m3','cs_mol_per_m3','Cs_mol_m3'):
         if key in row:values[key]=(native[i],1e-5,1e-7)
     for key,(expected,relative,absolute) in values.items():
      value=float(row[key]);checked+=1;in_file+=1
      if not math.isclose(value,expected,rel_tol=relative,abs_tol=absolute) and len(errors)<30:errors.append({'file':str(path.relative_to(work)),'column':key,'reported':value,'native':expected,'rel_tol':relative,'abs_tol':absolute})
    if in_file:files.append({'file':str(path.relative_to(work)),'numeric_values_checked':in_file})
   total+=checked;result[tid][arm]={'status':'checked' if checked and not errors else 'mismatch' if errors else 'unverified','numeric_values_checked':checked,'errors':errors,'files':files}
 record={'tasks':result,'numeric_values_checked':total,'organizer_solver_starts':0,'retained_inputs_modified':False,'scope':'实际单元剖面及Cs库存/释放历史与原生场匹配；只检查报告声明的数值对象，单元中心不当成边界面值；附加解析列不作为求解结果。'}
 api.save(root/'delivery-numeric-check.json',record)
 print(json.dumps({tid:{a:{k:x[k] for k in ('status','numeric_values_checked','errors')} for a,x in p.items()} for tid,p in result.items()},ensure_ascii=False))


def re_search(pattern,text):
 import re
 return re.search(pattern,text,re.I)

if __name__=='__main__':main()
