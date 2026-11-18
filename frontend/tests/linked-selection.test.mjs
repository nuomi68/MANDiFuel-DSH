import test from 'node:test';import assert from 'node:assert/strict';
import {resolveSource,nearestCell} from '../assets/data-sources.js';
import {chartSVG} from '../assets/chart-view.js';
import {compileProgram} from '../assets/render-program.js';
import {sceneAnnotations} from '../assets/scene-annotations.js';
import {nearestChartPoint} from '../assets/chart-navigation.js';
const table={columns:['view','time','value'].map(id=>({id})),rows:[{view:'a',time:10,value:1},{view:'b',time:10,value:2},{view:'b',time:20,value:3}]};
const context={getDataset:async()=>table,state:{view:'b'},time:10};
test('dense curve clicks select the closest saved point despite overlapping hit circles',()=>{
 const points=Array.from({length:200},(_,i)=>({id:i,x:i*3,y:100}));assert.equal(nearestChartPoint(points,99*3,100).id,99);assert.equal(nearestChartPoint(points,99*3+1,100).id,99);assert.equal(nearestChartPoint(points,300,150),null);
});
test('one shared selection binds rows and filters without replacing real values',async()=>{
 const source={kind:'dataset',dataset:'h',selection:{viewColumn:'view',timeColumn:'time',timeUnit:'s'},filter:[{column:'view',op:'eq',context:'view'},{column:'time',op:'eq',context:'time'}]};
 const result=await resolveSource(source,context);assert.equal(result.rows.length,1);assert.equal(result.rows[0].value,2);assert.deepEqual(result.rows[0].selection,{view:'b',time:10,timeUnit:'s'});
 const next=await resolveSource(source,{...context,time:20});assert.equal(next.rows[0].value,3);assert.equal(table.rows[1].selection,undefined);
 const svg=chartSVG({type:'chart'},[{label:'release',x:'time',y:'value',table:result}]);assert.match(svg,/data-linked-view="b"/);assert.match(svg,/data-linked-time="10"/);
});
test('linked spatial profiles retain exact frame and physical source coordinates',async()=>{
 const mesh={points:[[1,0,0],[2,0,0]],cellCenters:[[1,0,0],[2,0,0]]};
 const context={state:{view:'sphere',field:'Cs',frame:0},time:20,getViewData:async()=>({meta:{fields:[{id:'Cs',unit:'mol/m³'}],profileAxis:'radius',timeUnit:'s',radialUnit:'m'},data:{r:[1,2],meshes:{samples:mesh},frames:[{time:20,mesh:'samples',fields:{Cs:[.9,.1]}}]}})};
 const result=await resolveSource({kind:'profile',field:'Cs',axis:'x',selection:{timeColumn:'time',timeUnit:'s',positionColumns:['positionX','positionY','positionZ']}},context);
 assert.deepEqual(result.rows[1].selection,{view:'sphere',time:20,timeUnit:'s',position:[2,0,0]});assert.equal(result.rows[1].value,.1);
});
test('spherical reconstruction probes use radial distance and interfaces are view scoped',()=>{
 const mesh={points:[[0,0,0],[2,0,0]],cellCenters:[[1,0,0],[2,0,0]],samplingGeometry:'spherical'};
 assert.equal(nearestCell(mesh,[0,0,-2]).index,1);
 const p=compileProgram({annotations:[{id:'boundary',type:'circle',views:['layered'],position:['0','0','0'],radius:'1.5',axis:'y'},{id:'point',type:'probe',position:['0','0','-2'],field:'Cs'}]});
 const markers=sceneAnnotations(mesh,p,{}, {Cs:[1,.2]},[{id:'Cs',unit:'mol/m³'}],'Cs','layered');assert.equal(markers[0].path.length,65);assert(markers[0].path.every(p=>Math.abs(Math.hypot(...p)-1.5)<1e-12));assert.equal(markers[1].value,.2);
 assert.equal(sceneAnnotations(mesh,p,{}, {Cs:[1,.2]},[{id:'Cs',unit:'mol/m³'}],'Cs','bare').length,1);
});

test('saved history points carry their actual view, frame time and unit without a generated binding',async()=>{
 const context={state:{view:'active'},getViewData:async()=>({meta:{timeUnit:'d',fields:[{id:'T'}]},data:{frames:[{time:1.5,fields:{T:[301,302]}}]}})};
 const row=(await resolveSource({kind:'history',field:'T'},context)).rows[0];
 assert.deepEqual(row,{x:1.5,value:302,selection:{view:'active',time:1.5,timeUnit:'d'}});
 const profile=await resolveSource({kind:'profile',field:'T',axis:'cell',selection:{timeColumn:'time',timeUnit:'d'}},context);
 assert.deepEqual(profile.rows[1].selection,row.selection);
});
