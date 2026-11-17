// Slice convex finite-volume cells. Values remain the original owning-cell values.
export function sliceMesh(mesh,axis='z',fraction=.5){
 if(!mesh.cellEdges)throw new Error('该交付没有内部单元拓扑，暂不能生成真实切片。');
 const k={x:0,y:1,z:2}[axis];if(k===undefined)throw new Error('切面方向无效');
 const lo=mesh.points.reduce((v,p)=>Math.min(v,p[k]),Infinity),hi=mesh.points.reduce((v,p)=>Math.max(v,p[k]),-Infinity),span=hi-lo;if(!(span>0))throw new Error('该方向没有有效厚度');
 const p=lo+span*Math.max(1e-8,Math.min(1-1e-8,fraction)),eps=span*1e-9,other=[0,1,2].filter(i=>i!==k),points=[],triangles=[],cells=[];
 const nonConvex=new Set(mesh.nonConvexCells||[]);
 mesh.cellEdges.forEach((edges,cell)=>{
  const unique=new Map();let below=false,above=false;
  for(let j=0;j<edges.length;j+=2){const a=mesh.points[edges[j]],b=mesh.points[edges[j+1]],da=a[k]-p,db=b[k]-p;below||=da < -eps||db < -eps;above||=da > eps||db > eps;if(da*db>0&&Math.abs(da)>eps&&Math.abs(db)>eps)continue;if(Math.abs(da-db)<=eps)continue;const t=(p-a[k])/(b[k]-a[k]);if(t< -1e-8||t>1+1e-8)continue;const q=a.map((v,i)=>v+(b[i]-v)*t);const key=q.map(x=>Math.round(x/eps)).join(',');unique.set(key,q);}
  if(!below||unique.size<3)return;
  if(nonConvex.has(cell))throw new Error('当前切面涉及非凸单元，暂不支持；请选择表面视图。');
  const polygon=[...unique.values()],center=other.map(i=>polygon.reduce((s,q)=>s+q[i],0)/polygon.length);polygon.sort((a,b)=>Math.atan2(a[other[1]]-center[1],a[other[0]]-center[0])-Math.atan2(b[other[1]]-center[1],b[other[0]]-center[0]));
  // Near-collinear wedge intersections carry roundoff in model coordinates.
  // An area tolerance must follow the section size, rather than the much
  // smaller thickness of the slicing axis.
  const sectionSpan=Math.max(...other.map(j=>Math.max(...polygon.map(q=>q[j]))-Math.min(...polygon.map(q=>q[j])))),areaTolerance=Math.max(eps*eps,sectionSpan*sectionSpan*1e-10);
  let sign=0;for(let i=0;i<polygon.length;i++){const a=polygon[i],b=polygon[(i+1)%polygon.length],c=polygon[(i+2)%polygon.length],cross=(b[other[0]]-a[other[0]])*(c[other[1]]-b[other[1]])-(b[other[1]]-a[other[1]])*(c[other[0]]-b[other[0]]);if(Math.abs(cross)<=areaTolerance)continue;if(sign&&Math.sign(cross)!==sign)throw new Error('当前切面包含非凸截面，暂不支持；请选择表面视图。');sign=Math.sign(cross);}
  const start=points.length;points.push(...polygon);for(let i=1;i<polygon.length-1;i++){triangles.push(start,start+i,start+i+1);cells.push(cell);}
 });
 if(!triangles.length)throw new Error('当前切面没有相交单元，请调整方向或位置。');
 return{points,triangles,cells,dimensionality:2,preferredView:{x:'yz',y:'xz',z:'xy'}[axis],slice:{axis,fraction,coordinate:p}};
}
