import test from 'node:test';
import assert from 'node:assert/strict';
import {rotationProfile,revolveMesh,meridionalMesh} from '../assets/revolve-mesh.js';

function wedge(){
 const points=[],cellEdges=[],cellCenters=[];
 for(let c=0;c<2;c++){
  const start=points.length;
  for(const z of [0,1])for(const phi of [-.02,.02])for(const r of [c+1,c+2])points.push([r*Math.cos(phi),r*Math.sin(phi),z]);
  cellEdges.push([[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]].flatMap(([a,b])=>[start+a,start+b]));
  cellCenters.push([c+1.5,0,.5]);
 }
 return{points,cellEdges,cellCenters,triangles:[],cells:[],dimensionality:2};
}
test('real wedge topology produces an axisymmetric surface with unchanged original cell IDs',()=>{
 const source=wedge(),snapshot=JSON.stringify(source),p=rotationProfile(source),m=revolveMesh(source,270);
 assert.equal(p.axis,2);assert.equal(p.polygons.length,2);assert.deepEqual(new Set(m.cells),new Set([0,1]));assert.deepEqual(m.cellCenters,source.cellCenters);
 assert(m.points.every(v=>v[2]>=0&&v[2]<=1&&Math.hypot(v[0],v[1])<=3+1e-10));assert.equal(JSON.stringify(source),snapshot);
});
test('changing the sweep changes actual geometry while keeping the field mapping and radius',()=>{
 const source=wedge(),quarter=revolveMesh(source,90),half=revolveMesh(source,180);
 assert(quarter.points.every(p=>p[0]>=-1e-10&&p[1]<=1e-10));assert(half.points.some(p=>p[0]<-2.9));
 assert.deepEqual(new Set(quarter.cells),new Set(half.cells));assert.notEqual(quarter.triangles.length,half.triangles.length);
});
test('turning off an existing partial revolution recovers a flat meridional section',()=>{
 const m=revolveMesh(wedge(),270),flat=meridionalMesh(m);
 assert(flat.points.every(p=>Math.abs(p[1])<1e-12));assert.deepEqual(new Set(flat.cells),new Set([0,1]));assert.equal(flat.reconstruction,undefined);
 assert.equal(flat.preferredView,'xz');assert.equal(revolveMesh(m,120).reconstruction.angle,120);
});
test('a full turn has no duplicate radial cut caps or seam vertices',()=>{
 const m=revolveMesh(wedge(),360);
 for(let j=0;j<m.triangles.length;j+=3){
  const ps=m.triangles.slice(j,j+3).map(i=>m.points[i]),rs=ps.map(p=>Math.hypot(p[0],p[1])),zs=ps.map(p=>p[2]);
  assert(Math.max(...rs)-Math.min(...rs)<1e-10||Math.max(...zs)-Math.min(...zs)<1e-10);
 }
 assert.equal(new Set(m.points.map(p=>p.map(v=>Math.round(v*1e9)).join(':'))).size,m.points.length);
});
test('ordinary 2D planar and 3D meshes do not get mistaken for axisymmetric wedges',()=>{
 const m=wedge();m.points=m.points.map(([x,y,z])=>[x,y<0?-.05:.05,z]);assert.equal(rotationProfile(m),null);
 const volume=wedge();volume.dimensionality=3;assert.equal(rotationProfile(volume),null);
 for(const angle of [0,361,NaN,Infinity])assert.throws(()=>revolveMesh(wedge(),angle),/1–360/);
});
test('wedge planes are recognized when motion puts near-axis points on their negative rays',()=>{
 const m=wedge();for(const phi of [-.02,.02])m.points.push([-1e-4*Math.cos(phi),-1e-4*Math.sin(phi),.5]);
 assert.equal(rotationProfile(m).axis,2);assert.equal(rotationProfile(m).polygons.length,2);
});
