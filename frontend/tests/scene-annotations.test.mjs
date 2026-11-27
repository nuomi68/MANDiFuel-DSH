import test from 'node:test';
import assert from 'node:assert/strict';
import {compileProgram} from '../assets/render-program.js';
import {sceneAnnotations} from '../assets/scene-annotations.js';
const mesh={points:[[0,0,0],[2,2,2]],cellCenters:[[0,0,0],[2,2,2]]},meta=[{id:'T',unit:'K'},{id:'sigma',unit:'Pa'}];
test('point probes use current actual fields, parameters and source coordinates before display transforms',()=>{
 const p=compileProgram({vertex:['x*2','y','z'],annotations:[{id:'sample',type:'probe',position:['p.x','p.y','p.z']}]});
 const run=(coords,fields,field)=>sceneAnnotations(mesh,p,coords,fields,meta,field)[0];
 let marker=run({x:1.9,y:2,z:2},{T:[300,600]},'T');assert.equal(marker.value,600);assert.equal(marker.index,1);assert.deepEqual(marker.point,[3.8,2,2]);assert.match(marker.text,/最近单元/);
 marker=run({x:0,y:0,z:0},{T:[310,610]},'T');assert.equal(marker.value,310);assert.equal(marker.index,0);
 assert.equal(run({x:0,y:0,z:0},{sigma:[-5,10]},'sigma').value,-5);
 assert.throws(()=>run({x:0,y:0,z:0},{},'T'),/实际字段/);
});
test('axisymmetric probes sample by radius and axial position across rotated azimuths',()=>{
 const source={...mesh,cellCenters:[[1,0,0],[2,0,0]],reconstruction:{type:'axisymmetric-revolve',axis:'z'}};
 const p=compileProgram({annotations:[{id:'rotated',type:'probe',position:['0','-2','0'],field:'T'}]});
 const marker=sceneAnnotations(source,p,{}, {T:[100,200]},meta,'T')[0];assert.equal(marker.index,1);assert.equal(marker.distance,0);assert.equal(marker.value,200);
});
test('point, line, arrow, text, color and visibility compose without special parameter IDs',()=>{
 const p=compileProgram({annotations:[{id:'distance',type:'arrow',position:['0','0','0'],end:['p.endX','0','0'],text:'sqrt(p.endX**2)',color:'p.tint',visible:'p.show'}]});
 assert.deepEqual(sceneAnnotations(mesh,p,{endX:2,tint:'#123456',show:false}),[]);
 const marker=sceneAnnotations(mesh,p,{endX:2,tint:'#123456',show:true})[0];assert.deepEqual(marker.end,[2,0,0]);assert.equal(marker.color,'#123456');assert.match(marker.text,/2/);
});
test('shell surface marker uses the signed saved face value and its centre',()=>{
 const program=compileProgram({annotations:[{id:'surface',type:'boundaryProbe',patch:'outer',field:'sigma',label:'外表面 310 µm'}]});
 const source={face:99,point:[.0003,0,0],radius:.0003,fields:{sigma:-158505000}};
 const render=samples=>sceneAnnotations(mesh,program,{}, {sigma:[-186322000,-158225000]},meta,'sigma','shell',samples);
 const marker=render({outer:source})[0];
 assert.equal(marker.value,-158505000);assert.equal(marker.sourceFace,99);assert.deepEqual(marker.sourcePoint,source.point);
 assert.doesNotMatch(marker.text,/310/);
 assert.match(marker.text,/-158\.505 MPa/);assert.throws(()=>render({}),/边界面/);
});
