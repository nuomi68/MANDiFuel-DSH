import test from 'node:test';import assert from 'node:assert/strict';import {sliceMesh} from '../assets/mesh-slice.js';
function fixture(){const points=[],cellEdges=[];for(let c=0;c<2;c++){const start=points.length;for(const z of [0,1])for(const y of [0,1])for(const x of [c,c+1])points.push([x,y,z]);const pairs=[[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]];cellEdges.push(pairs.flatMap(([a,b])=>[start+a,start+b]));}return{points,cellEdges,triangles:[],cells:[]};}
function area(mesh){let total=0;for(let i=0;i<mesh.triangles.length;i+=3){const [a,b,c]=mesh.triangles.slice(i,i+3).map(j=>mesh.points[j]),u=b.map((x,j)=>x-a[j]),v=c.map((x,j)=>x-a[j]);total+=Math.hypot(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])/2;}return total;}
test('horizontal cut preserves both original cell labels and exact area',()=>{const s=sliceMesh(fixture(),'z',.5);assert.deepEqual(new Set(s.cells),new Set([0,1]));assert.equal(area(s),2);assert(s.points.every(p=>p[2]===.5));});
test('cut exactly on internal cell face selects one adjacent cell without overlap',()=>{const s=sliceMesh(fixture(),'x',.5);assert.equal(area(s),1);assert.deepEqual(new Set(s.cells),new Set([0]));assert(s.points.every(p=>p[0]===1));});
test('moving the cut changes its true spatial coordinate',()=>{const s=sliceMesh(fixture(),'x',.8);assert.equal(area(s),1);assert(s.points.every(p=>Math.abs(p[0]-1.6)<1e-12));assert.deepEqual(new Set(s.cells),new Set([1]));});
test('non-convex cell is explicitly rejected rather than filled with a fake section',()=>{const m=fixture();m.nonConvexCells=[0];assert.throws(()=>sliceMesh(m,'z',.5),/非凸/);});
test('boundary-only deliveries cannot pretend to contain internal slice data',()=>{assert.throws(()=>sliceMesh({points:fixture().points},'z',.5),/内部单元拓扑/);});
test('nearly collinear section vertices on a thin wedge use section-area tolerance',()=>{
 const face=[[0,0],[-2.8e-11,-2.7e-7],[0,-2.7e-7],[3e-5,1e-6],[2.97e-5,4.4e-6],[3.3e-10,3.1e-6]];
 const points=face.flatMap(([x,z])=>[[x,-1e-7,z],[x,1e-7,z]]),edges=face.flatMap((_,i)=>[2*i,2*i+1]);
 const s=sliceMesh({points,cellEdges:[edges]},'y',.5);assert(s.triangles.length>0);assert.deepEqual(new Set(s.cells),new Set([0]));
});
