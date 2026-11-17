#!/usr/bin/env python3
"""Export existing OFFBEAT results for the workbench; never starts a solver."""
from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import math
import re
import sys
from types import SimpleNamespace
from axisymmetric import dimensionality, revolve_mesh
from source_metadata import case_time_unit

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'skills/extract-offbeat-results/scripts'))
import result_api
import openfoam_parser as foam


def display_patches(path):
    """Read topology for display, permitting legal zero-face placeholder patches."""
    path=Path(path);source=str(path);tokens=foam._ascii_tokens(path.read_text(encoding='ascii'),source)
    if foam._parse_header(tokens,source)[1]!='boundary':raise ValueError('显示网格需要 boundary 边界文件')
    cursor,count=foam._counted_list_cursor(tokens,source);patches=[];names=set()
    for _ in range(count):
        name=cursor.take().text
        if name in names or name in foam._DELIMITERS:raise ValueError('显示边界名称重复或无效')
        names.add(name);opening=cursor.index;cursor.expect('{');closing=foam._matching_index(tokens,opening,'{','}',source)
        n=foam._unique_integer_entry(tokens,opening+1,closing,'nFaces',source);start=foam._unique_integer_entry(tokens,opening+1,closing,'startFace',source);kind=foam._token_entry(tokens,opening+1,closing,'type',source,required=True)
        owner=foam._optional_bool_entry(tokens,opening+1,closing,'owner',source);neighbour=foam._token_entry(tokens,opening+1,closing,'neighbourPatch',source,required=False)
        if n:patches.append(foam.BoundaryPatchTopology(name,n,start,patch_type=kind,owner=owner,neighbour_patch=neighbour))
        cursor.index=closing+1
    foam._finish_counted_list(cursor)
    return tuple(patches)


def field_unit(unit, dimensions):
    if unit and unit not in {'原生单位','未知'}:return unit
    dims=tuple(dimensions);known={(0,0,0,0,0,0,0):'1',(0,-3,0,0,1,0,0):'mol/m³',(0,2,-1,0,0,0,0):'m²/s',(1,-1,-2,0,0,0,0):'Pa',(1,1,-3,-1,0,0,0):'W/(m·K)',(1,-1,-3,0,0,0,0):'W/m³'}
    if dims in known:return known[dims]
    def token(base,power):return base if power==1 else base+{2:'²',3:'³'}.get(power,'^'+str(power))
    positive=[token(base,x) for base,x in zip(('kg','m','s','K','mol','A','cd'),dims) if x>0];negative=[token(base,-x) for base,x in zip(('kg','m','s','K','mol','A','cd'),dims) if x<0]
    numerator='·'.join(positive) or '1';denominator='·'.join(negative)
    return numerator+('/'+(denominator if len(negative)==1 else '('+denominator+')') if negative else '')


def mesh_data(case, time='latest'):
    info=result_api.describe_mesh(case,time=time);paths={k:Path(case)/v for k,v in info['primitive_sources'].items()}
    points=[[float(v) for v in p] for p in foam.parse_points(paths['points'])];faces=foam.parse_faces(paths['faces']);owners=foam.parse_label_list(paths['owner'],expected_object='owner');neighbours=foam.parse_label_list(paths['neighbour'],expected_object='neighbour');count=max(owners+neighbours)+1
    triangles=[];cells=[];edges=[set() for _ in range(count)];cell_faces=[[] for _ in range(count)]
    for i,face in enumerate(faces):
        face_edges={tuple(sorted((face[j],face[(j+1)%len(face)]))) for j in range(len(face))}
        edges[owners[i]].update(face_edges);cell_faces[owners[i]].append(face)
        if i<len(neighbours):edges[neighbours[i]].update(face_edges);cell_faces[neighbours[i]].append(face)
        else:
            for j in range(1,len(face)-1):triangles.extend((face[0],face[j],face[j+1]));cells.append(owners[i])
    dimension,view,_=dimensionality(points,faces,display_patches(paths['boundary']) if paths.get('boundary') else [])
    nonconvex=[]
    extent=max(max(p[j] for p in points)-min(p[j] for p in points) for j in range(3));tol=max(extent,1e-15)*1e-7
    for cell,fs in enumerate(cell_faces):
        vertices={i for f in fs for i in f}
        for face in fs:
            a,b,c=(points[face[j]] for j in range(3));u=[b[j]-a[j] for j in range(3)];v=[c[j]-a[j] for j in range(3)];normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];length=math.sqrt(sum(x*x for x in normal))
            if not length:continue
            distances=[sum((points[i][j]-a[j])*normal[j] for j in range(3))/length for i in vertices.difference(face)]
            if distances and min(distances)<-tol and max(distances)>tol:nonconvex.append(cell);break
    mesh={'points':points,'triangles':triangles,'cells':cells,'cellEdges':[[i for edge in sorted(cell) for i in edge] for cell in edges],'dimensionality':dimension,'preferredView':view,'nonConvexCells':nonconvex}
    signature=hashlib.sha256(b''.join(paths[k].read_bytes() for k in ('points','faces','owner','neighbour'))).hexdigest()[:20]
    return mesh,count,signature


def export_case(case, output, *, title='OFFBEAT 结果', selectors=None, time='latest', shape='mesh', radius=None, inner_radius=0., length=None, time_unit=None, radial_bands=None, axis='z', sweep_angle=270., write_handoff=True):
    case=Path(case).resolve(); output=Path(output).resolve()
    field_labels={}
    if selectors:
        normalized=[]
        for item in selectors:
            if isinstance(item,str):selector=item
            elif isinstance(item,dict) and set(item)<= {'selector','label','symbol'}:
                selector=item.get('selector')
                for key,limit in [('label',100),('symbol',40)]:
                    if key in item and (not isinstance(item[key],str) or not item[key] or len(item[key])>limit):raise ValueError('字段显示名称无效')
            else:raise ValueError('字段选择需要 selector 及可选 label/symbol')
            if not isinstance(selector,str) or not selector or not all(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',part) for part in selector.split(':')) or selector.count(':')>1:raise ValueError('字段选择器无效')
            if isinstance(item,dict):field_labels[selector]={k:item[k] for k in ('label','symbol') if k in item}
            if selector in normalized:raise ValueError('字段选择器重复')
            normalized.append(selector)
        selectors=normalized
    if time_unit is None:
        time_unit=case_time_unit(case)
        if time_unit is None:raise ValueError('无法核验用户时间单位，请显式指定 --time-unit')
    if not selectors:
        saved=result_api.list_times(case);latest=saved[-1] if saved else None
        selectors=next(([name] for name in ('T','Cs') if latest and (case/latest/name).is_file()),None)
    if selectors:
        catalog={}
        for name in dict.fromkeys(s.partition(':')[0] for s in selectors):
            saved=result_api.list_times(case,name)
            if not saved:raise ValueError(f'字段不可用: {name}')
            field=foam.parse_field(case/saved[-1]/name)
            catalog[name]={'components':foam.component_names(field.field_kind),'unit':foam.canonical_si_unit_for_dimensions(field.dimensions)}
    else:catalog=result_api.list_variables(case,time='latest')
    if not selectors:
        pick=next((v for v in ('T','Cs') if v in catalog),next((v for v,m in catalog.items() if 'value' in m['components']),None))
        if pick is None:raise ValueError('请通过 --fields 明确选择字段及分量，例如 D:x 或 sigma:principal_max')
        selectors=[pick]
    choices=[]
    for selector in selectors:
        name,_,component=selector.partition(':');component=component or 'value'
        if name not in catalog:raise ValueError(f'字段不可用: {name}')
        choices.append((selector.replace(':','_'),name,component))
    time_sets=[set(result_api.list_times(case,name)) for _,name,_ in choices]
    times=sorted(set.intersection(*time_sets),key=float)
    if time=='latest':times=times[-1:]
    elif time!='all':
        requested=str(time).split(',')
        if any(t not in times for t in requested):raise ValueError('所选时刻缺少请求字段，请保留原字段语义并选择共同保存时刻')
        times=sorted(set(requested),key=float)
    if not times:raise ValueError('请求字段没有共同保存时刻，请分别导出对应视图')
    meshes={};frames=[];bounds={key:[math.inf,-math.inf] for key,_,_ in choices};radial=None;count=None
    for t in times:
        cache={};parsed={}
        primary=next(((name,'principal_max') for _,name,c in choices if c=='principal_max'),None)
        if primary is None:primary=(choices[0][1],'x' if choices[0][2] in {'mag','magnitude'} else 'xx' if choices[0][2]=='von_mises' else choices[0][2])
        geometry=result_api.read_field(case,primary[0],time=t,component=primary[1]);cache[primary]=geometry
        def read(name,component):
            key=(name,component)
            if key in cache:return cache[key]
            if name not in parsed:parsed[name]=foam.parse_field(case/str(t)/name)
            field=parsed[name];mapping={'vector':{'x':0,'y':1,'z':2},'symmTensor':{'xx':0,'xy':1,'xz':2,'yy':3,'yz':4,'zz':5}}
            indices=mapping.get(field.field_kind,{})
            if component!='value' and component not in indices:
                cache[key]=result_api.read_field(case,name,time=t,component=component);return cache[key]
            raw_values=field.values
            if field.storage=='uniform':raw_values=raw_values*len(geometry.labels)
            if len(raw_values)!=len(geometry.labels):raise ValueError('分量场与单元数量不一致')
            values=[float(v[0]) if isinstance(v,(tuple,list)) and len(v)==1 else float(v) for v in raw_values] if component=='value' else [float(v[indices[component]]) for v in raw_values]
            cache[key]=SimpleNamespace(labels=geometry.labels,coordinates=geometry.coordinates,unit=catalog[name]['unit'],values=values);return cache[key]
        raw=[];derived={}
        for key,name,component in choices:
            if component=='von_mises':
                parts=[read(name,c) for c in ('xx','yy','zz','xy','xz','yz')];raw.append(parts[0])
                derived[key]=[math.sqrt(.5*((xx-yy)**2+(yy-zz)**2+(zz-xx)**2)+3*(xy*xy+xz*xz+yz*yz)) for xx,yy,zz,xy,xz,yz in zip(*(p.values for p in parts),strict=True)]
            elif component in {'mag','magnitude'}:
                parts=[read(name,c) for c in ('x','y','z')];raw.append(parts[0]);derived[key]=[math.sqrt(sum(p.values[i]**2 for p in parts)) for i in range(len(parts[0].values))]
            else:raw.append(read(name,component))
        first=raw[0];labels=list(first.labels)
        if labels!=list(range(len(labels))):raise ValueError('导出要求完整内部单元场')
        if any(f.labels!=first.labels for f in raw):raise ValueError('字段单元标签不一致')
        if count is not None and count!=len(labels):raise ValueError('网格拓扑变化：请按固定拓扑时间段分别导出')
        count=len(labels);values={key:derived.get(key,list(frame.values)) for (key,_,_),frame in zip(choices,raw,strict=True)}
        coords=first.coordinates
        if any(p is None for p in coords):raise ValueError('缺少单元中心坐标')
        if shape in {'mesh','revolve'}:
            primitive=result_api.describe_mesh(case,time=t)['primitive_sources'];digest=hashlib.sha256(b''.join((case/primitive[k]).read_bytes() for k in ('points','faces','owner','neighbour'))).hexdigest()[:20]
            if digest not in meshes:
                if shape=='revolve':
                    paths={k:case/v for k,v in primitive.items()}
                    meshes[digest]=revolve_mesh([[float(v) for v in p] for p in foam.parse_points(paths['points'])],foam.parse_faces(paths['faces']),foam.parse_label_list(paths['owner'],expected_object='owner'),display_patches(paths['boundary']),coords,axis=axis,angle=sweep_angle)
                else:
                    meshes[digest],mesh_count,_=mesh_data(case,t)
                    if mesh_count!=count:raise ValueError('场与网格单元数量不一致')
                    meshes[digest]['cellCenters']=[list(p) for p in coords]
            frame={'time':float(t),'fields':values,'mesh':digest}
            r=list(range(count))
        else:
            if radius is None or radius<=0:raise ValueError('对称重建需要 --radius，所有几何尺寸使用米')
            if shape=='rod' and (length is None or length<=0):raise ValueError('燃料棒需要 --length')
            r=[math.hypot(p[0],p[1]) if shape=='rod' else math.sqrt(sum(v*v for v in p)) for p in coords]
            order=sorted(range(len(r)),key=r.__getitem__);r=[r[i] for i in order]
            values={k:[vs[i] for i in order] for k,vs in values.items()};frame={'time':float(t),'fields':values}
        if radial is None:radial=r
        elif shape not in {'mesh','revolve'} and any(abs(a-b)>max(radius*1e-8,1e-14) for a,b in zip(radial,r,strict=True)):raise ValueError('移动网格需要按原始网格导出 --shape mesh')
        for key,vs in values.items():
            if not all(math.isfinite(v) for v in vs):raise ValueError(f'非有限场值: {key}')
            bounds[key][0]=min(bounds[key][0],min(vs));bounds[key][1]=max(bounds[key][1],max(vs))
        frames.append(frame)
    variables=[]
    for (key,name,component),field in zip(choices,raw,strict=True):
        lo,hi=bounds[key];data_range=[lo,hi]
        if hi==lo:hi=max(lo+(abs(lo)*.01 if lo else 1.0),math.nextafter(lo,math.inf))
        unit=field.unit
        if not unit or unit=='原生单位':unit=field_unit(unit,foam.parse_field(case/str(times[-1])/name).dimensions)
        variables.append({'id':key,'selector':name if component=='value' else name+':'+component,'label':name if component=='value' else f'{name} · {component}','symbol':f'|{name}|' if component in {'mag','magnitude'} else name,'unit':unit,'range':[lo,hi],'dataRange':data_range})
        variables[-1].update(field_labels.get(variables[-1]['selector'],{}))
    native=shape in {'mesh','revolve'};geometry=f'轴对称旋转重建（{sweep_angle:g}°）' if shape=='revolve' else '原始网格' if native else '对称重建'
    meta={'title':title,'shape':'mesh' if native else shape,'geometry':geometry,'cells':count,'radius':radius or max(1,max(radial)),'innerRadius':inner_radius,'length':length,'radialUnit':'' if native else 'm', 'profileAxis':'cell' if native else 'radius','timeUnit':time_unit,'fields':variables,'parameters':[['结果时间',', '.join(times)],['计算单元',str(count)],['显示几何',geometry]],'supportsExtrema':True}
    if native:
        first_mesh=next(iter(meshes.values()));meta['dimensionality']=first_mesh['dimensionality'];meta['preferredView']=first_mesh['preferredView'];meta['supportsSlice']=shape=='mesh'
        meta['coordinateBounds']={'min':[min(p[i] for p in first_mesh['points']) for i in range(3)],'max':[max(p[i] for p in first_mesh['points']) for i in range(3)],'unit':'m','time':frames[0]['time']}
        if shape=='revolve':meta['reconstruction']=first_mesh['reconstruction']
    if radial_bands is not None:meta['radialBands']=radial_bands
    bundle={'schema':'mandifuel.viewer/v1','caseRoot':str(case),'task':meta,'data':{'r':radial,'frames':frames,'series':True,'meshes':meshes}}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(bundle,ensure_ascii=False,allow_nan=False,separators=(',',':')))
    inputs=[]
    for folder in ('0','constant','system'):
        if (case/folder).is_dir():inputs.extend(str(p.relative_to(case)) for p in sorted((case/folder).rglob('*')) if p.is_file() and 'polyMesh' not in p.parts)
    for name in ('Allrun','rodDict','sphereDict','input_settings.txt','blockMeshDict','rod3Ddict.json','timesteps'):
        if (case/name).is_file():inputs.append(name)
    handoff={'schema':'mandifuel.handoff/v1','viewer':str(output),'caseRoot':str(case),'inputs':[str(case/p) for p in inputs]}
    if write_handoff:(output.parent/'workbench.json').write_text(json.dumps(handoff,ensure_ascii=False,indent=2))
    return {'viewer':str(output),'handoff':str(output.parent/'workbench.json') if write_handoff else None,'frames':len(frames),'cells':count,'fields':[c[0] for c in choices]}


def export_mesh(case, output, *, title='计算网格', time='latest', write_handoff=True):
    """Geometry only: no result field is synthesized or required."""
    case=Path(case).resolve();output=Path(output).resolve()
    mesh,count,_=mesh_data(case,time)
    bundle={'schema':'mandifuel.mesh/v1','caseRoot':str(case),'task':{'title':title,'shape':'mesh','geometry':'网格预览','cells':count,'radius':1,'innerRadius':0,'fields':[],'parameters':[],'dimensionality':mesh['dimensionality'],'preferredView':mesh['preferredView']},'data':{'kind':'mesh','mesh':mesh}}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(bundle,ensure_ascii=False,allow_nan=False,separators=(',',':')))
    if write_handoff:(output.parent/'workbench.json').write_text(json.dumps({'schema':'mandifuel.handoff/v1','viewer':str(output)},ensure_ascii=False))
    return {'viewer':str(output),'cells':count,'kind':'mesh'}


def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--no-handoff',action='store_true',help='仅导出模型，由研究汇总统一登记，避免覆盖其他参数组');parser.add_argument('--mesh-only',action='store_true',help='只交付真实网格，不读取结果场');parser.add_argument('--case',type=Path,required=True);parser.add_argument('--output',type=Path,default=Path('delivery/viewer.json'));parser.add_argument('--title',default='OFFBEAT 结果');parser.add_argument('--fields',nargs='+');parser.add_argument('--time',default='latest',help='latest、all、精确时刻或逗号分隔的已保存时刻');parser.add_argument('--time-unit');parser.add_argument('--shape',choices=['mesh','rod','sphere','shell','revolve'],default='mesh');parser.add_argument('--axis',choices=['x','y','z'],default='z');parser.add_argument('--sweep-angle',type=float,default=270.);parser.add_argument('--radius',type=float);parser.add_argument('--inner-radius',type=float,default=0.);parser.add_argument('--length',type=float);parser.add_argument('--radial-bands',type=json.loads,help='实体材料区JSON：[[内半径米,外半径米,格数],...]；不列气隙')
    args=parser.parse_args()
    if args.mesh_only:
        print(json.dumps(export_mesh(args.case,args.output,title=args.title,time=args.time,write_handoff=not args.no_handoff),ensure_ascii=False));return
    print(json.dumps(export_case(args.case,args.output,title=args.title,selectors=args.fields,time=args.time,shape=args.shape,radius=args.radius,inner_radius=args.inner_radius,length=args.length,time_unit=args.time_unit,radial_bands=args.radial_bands,axis=args.axis,sweep_angle=args.sweep_angle,write_handoff=not args.no_handoff),ensure_ascii=False))

if __name__=='__main__':main()
