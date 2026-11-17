"""Revolve a real wedge cross-section, retaining its original cell labels.

This is display geometry only. Values are never interpolated in the meridional
plane, and azimuthal copies do not become additional solved cells.
"""
import math


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def face_normal(points, face):
    # Sum the polygon area vectors. A collapsed axis face must not count as
    # another independent empty direction after mesh motion/roundoff.
    origin=points[face[0]];normal=[0.,0.,0.]
    for j in range(1,len(face)-1):
        n=cross([points[face[j]][k]-origin[k] for k in range(3)],
                [points[face[j+1]][k]-origin[k] for k in range(3)])
        normal=[normal[k]+n[k] for k in range(3)]
    return normal


def dimensionality(points, faces, patches):
    extent=max(max(p[k] for p in points)-min(p[k] for p in points) for k in range(3))
    axes=set();wedge=[]
    for patch in patches:
        if patch.patch_type not in {'empty','wedge'} or not patch.n_faces:continue
        normals=[face_normal(points,faces[j]) for j in range(patch.start_face,patch.start_face+patch.n_faces)]
        area=[sum(abs(n[k]) for n in normals) for k in range(3)]
        if math.hypot(*area)<=extent*extent*1e-7:continue
        axes.add(max(range(3),key=area.__getitem__))
        if patch.patch_type=='wedge':wedge.append((patch,area))
    dimension=max(1,3-len(axes))
    view={0:'yz',1:'xz',2:'xy'}.get(next(iter(axes),None),'xz') if dimension==2 else '3d'
    return dimension,view,wedge


def revolve_mesh(points, faces, owners, patches, centres, *, axis='z', angle=270.):
    if axis not in {'x','y','z'}:raise ValueError('旋转轴必须为 x、y 或 z')
    if isinstance(angle,bool) or not isinstance(angle,(int,float)) or not math.isfinite(angle) or not 0<angle<=360:
        raise ValueError('旋转展开角度必须在 0–360 度之间')
    dimension,_,wedges=dimensionality(points,faces,patches)
    if dimension!=2 or len(wedges)!=2:
        raise ValueError('旋转重建需要二维轴对称 wedge 网格；普通二维平面和一维径向网格不能套用')
    axis_index='xyz'.index(axis);radial=[k for k in range(3) if k!=axis_index]
    # Check the actual wedge plane normals against the requested axis.
    normals=[]
    for patch,_ in wedges:
        ns=[face_normal(points,faces[j]) for j in range(patch.start_face,patch.start_face+patch.n_faces)]
        normal=[sum(n[k] for n in ns) for k in range(3)];size=math.hypot(*normal)
        if not size or abs(normal[axis_index])/size>1e-4:raise ValueError('指定旋转轴与 wedge 截面不相容')
        normals.append(normal)
    axis_direction=cross(*normals)
    if math.hypot(*axis_direction)==0 or abs(axis_direction[axis_index])/math.hypot(*axis_direction)<.999:
        raise ValueError('无法从 wedge 边界确认指定轴的轴对称几何')
    extent=max(max(p[k] for p in points)-min(p[k] for p in points) for k in range(3));tol=max(extent*1e-8,1e-15)
    def rz(p):return math.hypot(*(p[k] for k in radial)),p[axis_index]
    def key(p):return tuple(round(v/tol) for v in p)
    patch=wedges[0][0];polygons=[];edges={};labels=set()
    for j in range(patch.start_face,patch.start_face+patch.n_faces):
        polygon=[]
        for vertex in faces[j]:
            p=rz(points[vertex])
            if not polygon or key(p)!=key(polygon[-1]):polygon.append(p)
        if len(polygon)>1 and key(polygon[0])==key(polygon[-1]):polygon.pop()
        if len(polygon)<3:continue
        cell=owners[j];labels.add(cell);polygons.append((polygon,cell))
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            edge=tuple(sorted((key(a),key(b))))
            edges.setdefault(edge,[]).append((a,b,cell))
    if labels!=set(range(len(centres))):raise ValueError('wedge 截面未覆盖全部真实单元，无法完整映射场值')
    if any(len(v)>2 for v in edges.values()):raise ValueError('截面存在重叠或非流形边，无法旋转重建')
    start=360-angle;steps=max(1,math.ceil(angle/5));phis=[math.radians(start+angle*j/steps) for j in range(steps+1)]
    out=[];triangles=[];cells=[];vertices={}
    def xyz(p,phi):
        result=[0.,0.,0.];result[axis_index]=p[1];result[radial[0]]=p[0]*math.cos(phi);result[radial[1]]=p[0]*math.sin(phi)
        return result
    def vertex(p,phi):
        coords=xyz(p,phi);k=tuple(round(v/tol) for v in coords)
        if k not in vertices:vertices[k]=len(out);out.append(coords)
        return vertices[k]
    def add(ps,cell):
        for j in range(1,len(ps)-1):
            ids=[ps[0],ps[j],ps[j+1]]
            if len(set(ids))<3:continue
            if math.hypot(*face_normal(out,ids))<=extent*extent*1e-14:continue
            triangles.extend(ids);cells.append(cell)
    if angle<360:
        for polygon,cell in polygons:
            for phi in [phis[0],phis[-1]]:add([vertex(p,phi) for p in polygon],cell)
    for entries in edges.values():
        if len(entries)!=1:continue
        a,b,cell=entries[0]
        for p,q in zip(phis,phis[1:]):add([vertex(a,p),vertex(b,p),vertex(b,q),vertex(a,q)],cell)
    if not triangles:raise ValueError('旋转重建没有可显示的表面')
    # Positions on a cut plane represent actual meridional cell centres; every
    # azimuth has the same value by the axisymmetric model assumption.
    marker_centres=[xyz(rz(p),phis[-1]) for p in centres]
    reconstruction={'type':'axisymmetric-revolve','axis':axis,'angle':angle,'startAngle':start,'sourceDimension':2}
    return {'points':out,'triangles':triangles,'cells':cells,'cellCenters':marker_centres,
            'dimensionality':2,'preferredView':'3d','reconstruction':reconstruction}
