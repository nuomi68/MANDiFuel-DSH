import test from 'node:test';
import assert from 'node:assert/strict';
import {rangeControls,resolveRange} from '../assets/display-controls.js';
import {ModelViewer} from '../assets/model-viewer.js';

test('custom color range has both inputs and parameter-bound ranges do not advertise competing controls',()=>{
 const controls=[{id:'scale',type:'select',options:[{value:'fixed'},{value:'custom'}]},{id:'lower',parameter:true}];
 assert.deepEqual(rangeControls(controls,null,'u').map(c=>c.id),['scale','lower','colorMin','colorMax']);
 assert.deepEqual(rangeControls(controls,{fields:{u:{range:[]}}},'u').map(c=>c.id),['lower']);
 assert.deepEqual(rangeControls(controls,{options:{scale:()=>{}}},'u').map(c=>c.id),['lower']);
 assert.equal(rangeControls([...controls,{id:'colorMin'}],null,'u').filter(c=>c.id==='colorMin').length,1);
});
test('manual range mode overrides a declared range while real parameter bindings keep authority',()=>{
 const input={declared:[0,20],fixed:[0,10],values:[2,5],scale:'frame',manual:false,custom:[1,9]};
 assert.deepEqual(resolveRange(input),[0,20]);
 assert.deepEqual(resolveRange({...input,manual:true}),[2,5]);
 assert.deepEqual(resolveRange({...input,manual:true,scale:'custom'}),[1,9]);
 assert.deepEqual(resolveRange({...input,manual:true,bound:[3,4]}),[3,4]);
});
test('spherical reconstruction maps actual radial values into its cut and rejects missing fields',()=>{
 const v=Object.create(ModelViewer.prototype),buffers=[];
 v.gl={bindBuffer(){},bufferData(_target,value){buffers.push(value);}};v.buffers={};v.canvas={dataset:{}};v.draw=()=>{};
 v.cut=false;v.cutAngle=90;v.axialScale=.16;
 const task={id:'same-task',shape:'shell',radius:2,innerRadius:1,cells:3};
 const sample=r=>r<1.3?1:r>1.7?2:5;
 v.setModel(task,sample,[1,5],'shell-a');assert.equal(JSON.parse(v.canvas.dataset.fieldMapping).sampledRange[1],2);
 v.cut=true;v.setModel(task,sample,[1,5],'shell-a');assert.equal(JSON.parse(v.canvas.dataset.fieldMapping).sampledRange[1],5);
 assert.ok(buffers.at(-1).includes(1));const key=v.geometryKey;
 v.setModel({...task,radius:3},sample,[1,5],'shell-b');assert.notEqual(v.geometryKey,key);
 assert.throws(()=>v.setModel(task,()=>undefined,[1,5],'missing'),/未映射/);
});
