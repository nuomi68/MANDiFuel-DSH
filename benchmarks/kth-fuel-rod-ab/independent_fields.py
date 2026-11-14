"""独立读取保留的 ASCII 场与网格；不导入任何被测 MANDiFuel 模块。"""
import importlib.util
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
READER=HERE/'reference_reader.py'
if not READER.exists(): READER=HERE.parent/'fuel-rod-power-ab/verify_results.py'
spec=importlib.util.spec_from_file_location('reference_reader',READER)
foam=importlib.util.module_from_spec(spec); spec.loader.exec_module(foam)


def add(a,b): return tuple(x+y for x,y in zip(a,b))
def sub(a,b): return tuple(x-y for x,y in zip(a,b))
def scale(a,s): return tuple(x*s for x in a)
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def mean(items):
    items=list(items)
    return tuple(sum(v[j] for v in items)/len(items) for j in range(3))


def list_body(path):
    words=foam.tokens(path.read_text())
    end=foam.matching(words,1,'{','}')
    count=int(words[end+1]); opening=end+2
    if words[opening]!='(': raise ValueError(f'缺少列表起点: {path}')
    close=foam.matching(words,opening,'(',')')
    return count,words[opening+1:close]


def vectors(path):
    count,body=list_body(path); result=[]; i=0
    while i<len(body):
        if body[i]!='(': raise ValueError('向量格式错误')
        result.append(tuple(float(x) for x in body[i+1:i+4])); i+=5
    if len(result)!=count: raise ValueError('向量数目不符')
    return result


def faces(path):
    count,body=list_body(path); result=[]; i=0
    while i<len(body):
        n=int(body[i]); i+=1
        if body[i]!='(': raise ValueError('面格式错误')
        result.append([int(x) for x in body[i+1:i+1+n]]); i+=n+2
    if len(result)!=count: raise ValueError('面数目不符')
    return result


def labels(path):
    count,body=list_body(path); values=[int(x) for x in body]
    if len(values)!=count: raise ValueError('标签数目不符')
    return values


def boundary(path):
    count,body=list_body(path); result={}; i=0
    while i<len(body):
        name=body[i].strip('"'); i+=1
        if body[i]!='{': raise ValueError('边界格式错误')
        close=foam.matching(body,i,'{','}')
        result[name]=foam.dictionary(body,i+1,close); i=close+1
    if len(result)!=count: raise ValueError('边界数目不符')
    return result


def polyhedron(points,cell_faces):
    vertices={i for face in cell_faces for i in face}
    origin=mean(points[i] for i in vertices)
    total=0.; weighted=(0.,0.,0.)
    for face in cell_faces:
        middle=mean(points[i] for i in face)
        for i,j in zip(face,face[1:]+face[:1]):
            a,b=points[i],points[j]
            volume=abs(dot(sub(a,origin),cross(sub(b,origin),sub(middle,origin))))/6
            center=scale(add(add(origin,a),add(b,middle)),.25)
            total+=volume; weighted=add(weighted,scale(center,volume))
    if total<=0: raise ValueError('非正体积单元')
    return scale(weighted,1/total),total


def field_values(value,n):
    if value[0]=='uniform': return [float(value[1])]*n
    if value[:2]==['nonuniform','List<scalar>']:
        count=int(value[2]); values=[float(x) for x in value[4:-1]]
        if count!=n or len(values)!=n: raise ValueError('标量场长度不符')
        return values
    raise ValueError(f'不支持标量场: {value[:4]}')


def scalar_field(path,n):
    data=foam.read_foam(path)
    return field_values(data['internalField'],n),data


def patch_values(data,name,n):
    import re
    fields=data['boundaryField']
    entry=fields.get(name)
    if entry is None:
        entry=next((v for pattern,v in fields.items() if re.fullmatch(pattern,name)),None)
    if entry is None or 'value' not in entry: return None
    return field_values(entry['value'],n)


def intercept(x,y):
    mx=sum(x)/len(x); my=sum(y)/len(y)
    slope=sum((a-mx)*(b-my) for a,b in zip(x,y))/sum((a-mx)**2 for a in x)
    return my-slope*mx,slope


def read_case(root,time='1'):
    root=Path(root); mesh=root/'constant/polyMesh'
    points=vectors(mesh/'points'); face_list=faces(mesh/'faces')
    owner=labels(mesh/'owner'); neighbour=labels(mesh/'neighbour')
    zones=foam.cell_zones(mesh/'cellZones'); n=max(owner)+1
    by_cell=[[] for _ in range(n)]
    for i,c in enumerate(owner): by_cell[c].append(face_list[i])
    for i,c in enumerate(neighbour): by_cell[c].append(face_list[i])
    geometry=[polyhedron(points,fs) for fs in by_cell]
    centers=[c for c,v in geometry]; volumes=[v for c,v in geometry]
    values,data=foam.internal_temperatures(root/time/'T',n)
    groups={}
    for name,cells in zones.items():
        lower=name.lower()
        group='fuel' if 'fuel' in lower else 'clad' if 'clad' in lower else 'gap' if 'gap' in lower else name
        groups.setdefault(group,[]).extend(cells)
    fuel=groups['fuel']; clad=groups['clad']; gap=groups.get('gap',[])
    if (root/time/'k').exists(): k,_=scalar_field(root/time/'k',n)
    else:
        materials=foam.read_foam(root/'constant/solverDict')['materials']; k=[None]*n
        for name,cells in zones.items():
            value=float(materials[name]['k'][-1])
            for c in cells: k[c]=value
    boundary_map=boundary(mesh/'boundary')
    patch_records={}
    for name,patch in boundary_map.items():
        start=int(patch['startFace'][0]); count=int(patch['nFaces'][0])
        selected=face_list[start:start+count]
        radii=[math.hypot(points[i][0],points[i][1]) for face in selected for i in face]
        pv=patch_values(data,name,count) if count else None
        patch_records[name]={'count':count,'radius_min':min(radii) if radii else None,'radius_max':max(radii) if radii else None,'values':pv,'type':patch['type'][0]}
    outer_radius=max(math.hypot(p[0],p[1]) for p in points)
    surface=None
    for name,patch in patch_records.items():
        if patch['values'] is not None and abs(patch['radius_min']-outer_radius)<1e-10 and abs(patch['radius_max']-outer_radius)<1e-10:
            surface=sum(patch['values'])/len(patch['values'])
    interfaces={}
    membership={c:g for g,cells in groups.items() for c in cells}
    for f,nbr in enumerate(neighbour):
        own=owner[f]; pair=frozenset((membership[own],membership[nbr]))
        if len(pair)==1: continue
        vertices=[points[i] for i in face_list[f]]; fc=mean(vertices)
        normal=cross(sub(vertices[1],vertices[0]),sub(vertices[2],vertices[0]))
        length=math.sqrt(dot(normal,normal)); normal=scale(normal,1/length)
        dp=abs(dot(sub(fc,centers[own]),normal)); dn=abs(dot(sub(centers[nbr],fc),normal))
        ap=k[own]/dp; an=k[nbr]/dn
        tf=(ap*values[own]+an*values[nbr])/(ap+an)
        interfaces.setdefault('-'.join(sorted(pair)),[]).append(tf)
    interface_avg={key:sum(v)/len(v) for key,v in interfaces.items()}
    def boundary_mean(names):
        chosen=[v for name,p in patch_records.items() if name.lower() in names and p['values'] for v in p['values']]
        return sum(chosen)/len(chosen) if chosen else None
    fuel_surface=interface_avg.get('fuel-gap',boundary_mean({'fuelouter','fuelsurface'}))
    clad_inner=interface_avg.get('clad-gap',boundary_mean({'cladinner','claddinginner'}))
    radius=[math.hypot(c[0],c[1]) for c in centers]
    center,slope=intercept([radius[i]**2 for i in fuel],[values[i] for i in fuel])
    quantities={'fuel_T_max_K':max(values[i] for i in fuel),'fuel_centerline_T_K':center,'fuel_surface_T_K':fuel_surface,'clad_inner_T_K':clad_inner,'clad_outer_T_K':surface}
    if None not in (fuel_surface,clad_inner,surface):
        quantities.update(delta_fuel_K=center-fuel_surface,delta_gap_K=fuel_surface-clad_inner,delta_clad_K=clad_inner-surface,delta_convection_K=surface-600,q_limit_W_per_m=41000*(3073-600)/(center-600))
    zone_info={}
    for g,cells in groups.items():
        vertices={v for c in cells for face in by_cell[c] for v in face}
        radii=[math.hypot(points[i][0],points[i][1]) for i in vertices]
        zone_info[g]={'cells':len(cells),'radius_min_m':min(radii),'radius_max_m':max(radii),'k_min':min(k[i] for i in cells),'k_max':max(k[i] for i in cells),'volume_m3':sum(volumes[i] for i in cells)}
    return {'quantities':quantities,'zones':zone_info,'field_cells':n,'fuel_fit_slope_K_m2':slope,'interfaces':interface_avg,'height_m':max(p[2] for p in points)-min(p[2] for p in points),'profiles':[{'cell':i,'zone':membership[i],'radius_m':radius[i],'temperature_K':values[i],'volume_m3':volumes[i]} for i in range(n)],'patches':patch_records,'wedge_angle_rad':max(math.atan2(p[1],p[0]) for p in points)-min(math.atan2(p[1],p[0]) for p in points)}
