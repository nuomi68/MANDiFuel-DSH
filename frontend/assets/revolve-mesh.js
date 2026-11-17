// Rebuild display surfaces from the real meridional cell boundaries. Every
// generated triangle keeps its original cell ID; no field values are invented.
const profiles=new WeakMap(),surfaces=new WeakMap();
const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);

function wedgeAxis(mesh,extent){
 if(mesh.dimensionality!==2||!mesh.cellEdges)return null;
 for(let axis=0;axis<3;axis++){
  const radial=[0,1,2].filter(i=>i!==axis),angles=[];
  for(const p of mesh.points)if(Math.hypot(...radial.map(i=>p[i]))>extent*1e-6)angles.push((Math.atan2(p[radial[1]],p[radial[0]])+Math.PI)%Math.PI);
  angles.sort((a,b)=>a-b);const groups=[];
  for(const angle of angles)if(!groups.length||angle-groups.at(-1)>1e-5)groups.push(angle);
  if(groups.length>1&&groups[0]+Math.PI-groups.at(-1)<1e-5)groups.pop();
  if(groups.length!==2)continue;
  const gap=groups[1]-groups[0],width=Math.min(gap,Math.PI-gap);
  if(width>1e-6&&width<Math.PI/6)return axis;
 }
 return null;
}

export function rotationProfile(mesh){
 if(!mesh?.points?.length)return null;
 if(profiles.has(mesh))return profiles.get(mesh);
 const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];
 for(const p of mesh.points)for(let k=0;k<3;k++){lo[k]=Math.min(lo[k],p[k]);hi[k]=Math.max(hi[k],p[k]);}
 const extent=Math.max(...hi.map((v,k)=>v-lo[k])),tol=Math.max(extent*1e-9,1e-15);
 const axis=mesh.reconstruction?.type==='axisymmetric-revolve'?'xyz'.indexOf(mesh.reconstruction.axis):wedgeAxis(mesh,extent);
 if(axis===null||axis<0){profiles.set(mesh,null);return null;}
 const radial=[0,1,2].filter(i=>i!==axis),points=[],vertices=new Map();
 const vertex=p=>{
  const rz=[Math.hypot(...radial.map(i=>p[i])),p[axis]],key=rz.map(v=>Math.round(v/tol)).join(':');
  if(!vertices.has(key)){vertices.set(key,points.length);points.push(rz);}
  return vertices.get(key);
 };
 const edges=new Map(),add=(cell,a,b)=>{
  if(a===b)return;if(!edges.has(cell))edges.set(cell,new Map());
  const key=a<b?`${a}:${b}`:`${b}:${a}`,set=edges.get(cell),entry=set.get(key);
  if(entry)entry.count++;else set.set(key,{a,b,count:1});
 };
 if(mesh.reconstruction){
  // Existing partial revolutions include a real cut plane at phi=360°.
  // Recover each polygon from its cap triangles, removing triangulation edges.
  for(let j=0;j<mesh.triangles.length;j+=3){
   const ps=mesh.triangles.slice(j,j+3).map(i=>mesh.points[i]);
   if(!ps.every(p=>Math.abs(p[radial[1]])<=tol&&p[radial[0]]>=-tol))continue;
   if(ps.every(p=>Math.hypot(...radial.map(i=>p[i]))<=tol))continue;
   const ids=ps.map(vertex);if(Math.abs(cross(...ids.map(i=>points[i])))<=tol*tol)continue;
   for(let k=0;k<3;k++)add(mesh.cells[j/3],ids[k],ids[(k+1)%3]);
  }
 }else{
  for(let cell=0;cell<mesh.cellEdges.length;cell++){
   const seen=new Set(),list=mesh.cellEdges[cell];
   for(let j=0;j<list.length;j+=2){
    const a=vertex(mesh.points[list[j]]),b=vertex(mesh.points[list[j+1]]),key=a<b?`${a}:${b}`:`${b}:${a}`;
    if(!seen.has(key)){add(cell,a,b);seen.add(key);}
   }
  }
 }
 const polygons=[];
 for(const[cell,set]of edges){
  const adjacency=new Map();
  for(const{a,b,count}of set.values())if(count===1){for(const[x,y]of[[a,b],[b,a]]){if(!adjacency.has(x))adjacency.set(x,[]);adjacency.get(x).push(y);}}
  if(adjacency.size<3||[...adjacency.values()].some(v=>v.length!==2)){profiles.set(mesh,null);return null;}
  const start=adjacency.keys().next().value,polygon=[];let previous=null,current=start;
  do{polygon.push(current);const next=adjacency.get(current).find(v=>v!==previous);previous=current;current=next;}while(current!==start&&polygon.length<=adjacency.size);
  if(polygon.length!==adjacency.size){profiles.set(mesh,null);return null;}
  const area=polygon.reduce((sum,a,j)=>{const b=polygon[(j+1)%polygon.length];return sum+points[a][0]*points[b][1]-points[b][0]*points[a][1];},0);
  if(area<0)polygon.reverse();
  if(polygon.some((a,j)=>cross(points[a],points[polygon[(j+1)%polygon.length]],points[polygon[(j+2)%polygon.length]]) < -Math.abs(area)*1e-7)){profiles.set(mesh,null);return null;}
  polygons.push({cell,vertices:polygon});
 }
 const count=mesh.cellCenters?.length||mesh.cellEdges?.length||mesh.cells.reduce((n,c)=>Math.max(n,c+1),0);
 const profile=polygons.length===count?{axis,radial,points,polygons,tol,centres:mesh.cellCenters}:null;
 profiles.set(mesh,profile);return profile;
}

export function revolveMesh(mesh,angle=270){
 if(!Number.isFinite(angle)||angle<1||angle>360)throw new Error('旋转角度须在 1–360° 之间');
 const p=rotationProfile(mesh);if(!p)throw new Error('当前网格没有可旋转的二维轴对称截面');
 const cached=surfaces.get(mesh);if(cached?.angle===angle)return cached.mesh;
 const out=build(p,angle);surfaces.set(mesh,{angle,mesh:out});return out;
}

export function meridionalMesh(mesh){
 if(!mesh.reconstruction)return mesh;
 const p=rotationProfile(mesh);if(!p)throw new Error('当前交付缺少原始二维截面');
 if(!p.flat)p.flat=build(p,0);return p.flat;
}

function build(p,angle){
 const points=[],triangles=[],cells=[],indices=new Map(),boundary=new Map();
 const xyz=(rz,phi)=>{const v=[0,0,0];v[p.axis]=rz[1];v[p.radial[0]]=rz[0]*Math.cos(phi);v[p.radial[1]]=rz[0]*Math.sin(phi);return v;};
 const vertex=(id,phi)=>{
  const v=xyz(p.points[id],phi),key=v.map(x=>Math.round(x/p.tol)).join(':');
  if(!indices.has(key)){indices.set(key,points.length);points.push(v);}return indices.get(key);
 };
 const add=(ids,cell)=>{for(let j=1;j<ids.length-1;j++){const tri=[ids[0],ids[j],ids[j+1]];if(new Set(tri).size===3){triangles.push(...tri);cells.push(cell);}}};
 const start=(360-angle)*Math.PI/180,end=2*Math.PI,steps=Math.max(1,Math.ceil(angle/5));
 for(const{cell,vertices}of p.polygons){
  if(angle===0)add(vertices.map(i=>vertex(i,0)),cell);
  else if(angle<360){add(vertices.map(i=>vertex(i,start)),cell);add([...vertices].reverse().map(i=>vertex(i,end)),cell);}
  for(let j=0;j<vertices.length;j++){
   const a=vertices[j],b=vertices[(j+1)%vertices.length],key=a<b?`${a}:${b}`:`${b}:${a}`;
   if(boundary.has(key))boundary.get(key).count++;else boundary.set(key,{a,b,cell,count:1});
  }
 }
 if(angle>0)for(const{a,b,cell,count}of boundary.values())if(count===1)for(let j=0;j<steps;j++){
  const phi=start+(end-start)*j/steps,next=start+(end-start)*(j+1)/steps;
  add([vertex(a,phi),vertex(b,phi),vertex(b,next),vertex(a,next)],cell);
 }
 const result={points,triangles,cells,dimensionality:2,preferredView:angle?'3d':['yz','xz','xy'][p.radial[1]]};
 if(p.centres)result.cellCenters=p.centres.map(c=>xyz([Math.hypot(...p.radial.map(i=>c[i])),c[p.axis]],0));
 if(angle)result.reconstruction={type:'axisymmetric-revolve',axis:'xyz'[p.axis],angle,startAngle:360-angle,sourceDimension:2};
 return result;
}
