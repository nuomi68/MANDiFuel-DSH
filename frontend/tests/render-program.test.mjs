import test from 'node:test';
import assert from 'node:assert/strict';
import {compileExpression,compileProgram,transformMesh,bindStyle,bindOptions,bindField} from '../assets/render-program.js';
import {parameterMarkup} from '../assets/parameter-panel.js';

const rectangle={points:[[-2,0,0],[2,0,0],[2,2,0],[-2,2,0]],triangles:[0,1,2,0,2,3],cells:[0,0],cellCenters:[[0,1,0]]};
const program={label:'用户定义的形状',vertex:['centerX+(x-centerX)*mix(p.lower,p.upper,(y-minY)/sizeY)/sizeX','minY+(y-minY)*p.height/sizeY','z'],style:{wireColor:'p.outline'}};
test('a data-defined program changes a rectangle into a trapezoid without a shape-specific renderer',()=>{
 const compiled=compileProgram(program),mesh=transformMesh(rectangle,compiled,{lower:6,upper:2,height:3});
 assert.deepEqual(mesh.points,[[-3,0,0],[3,0,0],[1,3,0],[-1,3,0]]);assert.deepEqual(mesh.cells,rectangle.cells);assert.deepEqual(rectangle.points,[[-2,0,0],[2,0,0],[2,2,0],[-2,2,0]]);
 const edited=transformMesh(rectangle,compiled,{lower:4,upper:3,height:5});assert.deepEqual(edited.points,[[-2,0,0],[2,0,0],[1.5,5,0],[-1.5,5,0]]);assert.deepEqual(edited.cellCenters,[[0,2.5,0]]);
});
test('the same executor handles an unrelated shear with arbitrary parameter IDs',()=>{
 const mesh=transformMesh(rectangle,compileProgram({vertex:['x+p.lean*(y-minY)','y','z']}),{lean:.5});assert.deepEqual(mesh.points[2],[3,2,0]);
});
test('parameter bindings drive style primitives and reject invalid output',()=>{
 const p=compileProgram({style:{scaleX:'p.widen',opacity:'p.alpha',palette:'select(p.warm,"inferno","viridis")',wireColor:'p.outline'}});
 const style=bindStyle({scale:[1,1,1]},p,{widen:2,alpha:.5,warm:true,outline:'#123456'});assert.deepEqual(style.scale,[2,1,1]);assert.equal(style.palette,'inferno');assert.equal(style.wireColor,'#123456');
 assert.throws(()=>bindStyle({scale:[1,1,1]},p,{widen:0}),/范围/);
});
test('expressions are bounded data, with no JavaScript execution or property traversal',()=>{
 for(const source of ['globalThis.alert(1)','p.__proto__','p.width.constructor','x[0]','(()=>1)()','fetch("/secret")'])assert.throws(()=>compileExpression(source));
 assert.equal(compileExpression('select(p.flag, 4, sqrt(-1))')({}, {flag:true}),4);
 assert.throws(()=>transformMesh(rectangle,compileProgram({vertex:['x/0','y','z']}),{}),/无效坐标/);
});
test('generic panel labels, units and text are escaped and do not need a predefined ID',()=>{
 const html=parameterMarkup({id:'aNewDimension',type:'number',label:'上底',unit:'mm',min:1,default:3,help:'<script>no</script>'},3);
 assert.match(html,/data-control="aNewDimension"/);assert.match(html,/mm/);assert.match(html,/&lt;script&gt;/);assert(!html.includes('<script>'));
});
test('composed parameters bind actual time, camera, slice, comparison and independent color ranges',()=>{
 const p=compileProgram({options:{time:'p.savedTime',yaw:'p.angle',slicePosition:'p.section',compare:'p.dual',extremaMode:'"max"'},fields:{T:{range:['p.low','p.high'],palette:'p.colors',reversePalette:'p.flip'}}});
 const v={savedTime:50,angle:90,section:.3,dual:true,low:200,high:800,colors:'inferno',flip:true};
 assert.deepEqual(bindOptions(p,v),{time:50,yaw:90,slicePosition:.3,compare:true,extremaMode:'max'});assert.deepEqual(bindField(p,'T',v),{range:[200,800],palette:'inferno',reversePalette:true});assert.deepEqual(bindField(p,'sigma',v),{});
 assert.throws(()=>bindField(p,'T',{...v,high:100}),/下限/);assert.throws(()=>bindOptions(p,{...v,section:2}),/无效/);
});
