import test from 'node:test';import assert from 'node:assert/strict';
import {resolveSource,nearestCell} from '../assets/data-sources.js';
import {chartSVG,tableCSV} from '../assets/chart-view.js';
const mesh={points:[[0,0,0],[2,1,1]],cellCenters:[[0,0,0],[2,0,0]]};
const meta={shape:'mesh',profileAxis:'cell',timeUnit:'s',fields:[{id:'T',label:'温度',unit:'K'}]};
const data={series:true,meshes:{m:mesh},frames:[{mesh:'m',time:0,fields:{T:[300,400]}},{mesh:'m',time:10,fields:{T:[320,500]}}]};
const context={getViewData:async()=>({data,meta}),parameters:{sampleX:1.9},state:{field:'T',frame:1},time:10,timeUnit:'s'};
test('history statistics and profiles use actual stored frames and cell coordinates',async()=>{
 assert.deepEqual((await resolveSource({kind:'history',field:'T',statistic:'max'},context)).rows,[{x:0,value:400},{x:10,value:500}]);
 assert.deepEqual((await resolveSource({kind:'profile',field:'T',axis:'x'},context)).rows,[{x:0,value:320},{x:2,value:500}]);
 assert.deepEqual((await resolveSource({kind:'profile',field:'T',axis:'cell',time:0},context)).rows,[{x:0,value:300},{x:1,value:400}]);
});
test('coordinate profiles retain the verified mesh unit without inventing a conversion',async()=>{
 const ctx={...context,getViewData:async()=>({data,meta:{...meta,coordinateBounds:{unit:'m'}}})};
 const table=await resolveSource({kind:'profile',field:'T',axis:'x'},ctx);assert.equal(table.columns[0].unit,'m');assert.deepEqual(table.rows,[{x:0,value:320},{x:2,value:500}]);
 assert.equal((await resolveSource({kind:'profile',field:'T',axis:'cell'},ctx)).columns[0].unit,'');
});
test('parameterized point history and scene markers share nearest real cell sampling',async()=>{
 const table=await resolveSource({kind:'probeHistory',field:'T',position:['p.sampleX','0','0']},context);
 assert.deepEqual(table.rows.map(r=>r.value),[400,500]);assert(table.rows.every(r=>r.cell===1&&Math.abs(r.distance-.1)<1e-12));
 assert.equal(nearestCell({...mesh,reconstruction:{type:'axisymmetric-revolve',axis:'z'}},[0,2,0]).index,1);
});
test('unknown fields and missing results fail rather than generate zero-valued curves',async()=>{
 await assert.rejects(resolveSource({kind:'history',field:'missing'},context),/不存在/);
 await assert.rejects(resolveSource({kind:'profile',field:'T'},{...context,getViewData:async()=>({data:{kind:'mesh'},meta})}),/没有结果场/);
});
test('chart paths retain gaps and escape text; exports retain original zeros and missing values',()=>{
 const table={columns:[{id:'x'},{id:'value'}],rows:[{x:0,value:0},{x:1,value:null},{x:2,value:10}]};
 const svg=chartSVG({title:'<script>',type:'lineChart'},[{label:'<img>',table}]);assert(svg.includes('&lt;script&gt;'));assert(!svg.includes('<img>'));const curve=svg.match(/<path d="([^"]*)" fill="none" stroke="#2563a6"[^>]*><title>/)[1];assert.equal((curve.match(/M/g)||[]).length,2);assert(!curve.includes('L'));
 const csv=tableCSV(table);assert(csv.includes('"0","0"'));assert(csv.includes('"1",""'));
});
